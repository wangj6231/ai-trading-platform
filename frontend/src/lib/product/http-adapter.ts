import { z } from "zod";
import { createProductSnapshot, ready, unloaded, type Account, type Attachment, type Order, type OrderIntent, type Page, type PageQuery, type ProductApis, type Resource, type Trade, type MetadataPatch, type ExecutionResponse } from "./contracts";
import { httpMetadataBody, httpOrderBody, normalizeHttpAccount, normalizeHttpAnalytics, normalizeHttpAttachment, normalizeHttpFill, normalizeHttpOrder, normalizeHttpPage, normalizeHttpPosition, normalizeHttpTrade } from "./http-contract";
import { PaperHttpError, paperFailure, safePaperCode } from "./http-errors";
import { ProductResourceStore } from "./resource-store";

const presentation = { source: "HTTP / BACKEND", environmentLabel: "PAPER / HTTP", notice: "Backend execution and financial facts only. No fixture fallback. An acknowledged order does not prove a fill or an observation worker." };
const queryNames = { limit: "limit", cursor: "cursor", asOf: "as_of", symbol: "symbol", side: "side", result: "result", closedFrom: "closed_from", closedTo: "closed_to", tag: "tag" } as const;
function queryString(query: PageQuery = {}) { const params = new URLSearchParams(); for (const [name, value] of Object.entries(query)) if (value !== undefined) params.set(queryNames[name as keyof typeof queryNames], String(value)); return params.size ? `?${params}` : ""; }
type MainResource = "account" | "orders" | "positions" | "trades" | "journal" | "analytics";
type DetailResource = "tradeDetails" | "attachments" | "fills";

export class HttpProductAdapter extends ProductResourceStore {
  readonly apis: ProductApis;
  private epoch = 0;
  private blocked: PaperHttpError | null = null;
  private disposed = false;
  private controllers = new Set<AbortController>();
  private sequences = new Map<string, number>();
  private initialized: Promise<void> | null = null;
  constructor(readonly accountId: string, private fetcher: typeof fetch = (input, init) => fetch(input, init)) {
    super(accountId, presentation);
    this.apis = {
      account: { getAccount: () => this.account() },
      execution: { submit: intent => this.submit(intent), refreshOrder: id => this.orderCommand(id), cancel: id => this.orderCommand(id, true), getOrders: query => this.orders(query), getPositions: () => this.positions() },
      journal: { getTrades: query => this.trades("trades", query), getJournal: query => this.trades("journal", query), getTrade: id => this.trade(id), getAttachments: (id, query) => this.attachments(id, query), getFills: (id, query) => this.fills(id, query), saveMetadata: (id, patch) => this.metadata(id, patch), addUpload: async () => { throw new PaperHttpError("ATTACHMENT_FAILED"); } },
      analytics: { getAnalytics: () => this.analytics() },
    };
  }
  override initialize = () => { if (this.disposed) { this.disposed = false; this.blocked = null; this.initialized = null; } return this.initialized ??= this.refresh(); };
  dispose = () => { this.disposed = true; this.epoch++; this.controllers.forEach(controller => controller.abort()); this.controllers.clear(); this.update(createProductSnapshot(this.accountId, presentation)); };
  private deny(error: PaperHttpError) {
    this.blocked = error; this.epoch++; this.controllers.forEach(controller => controller.abort());
    const blank = createProductSnapshot(this.accountId, presentation);
    const failure = this.failed(error);
    const details = (key: DetailResource) => Object.fromEntries(Object.keys(this.getSnapshot()[key]).map(id => [id, failure]));
    this.update({ ...blank, account: failure, orders: failure, positions: failure, trades: failure, journal: failure, analytics: failure, tradeDetails: details("tradeDetails"), attachments: details("attachments"), fills: details("fills") });
  }
  private failed(error: PaperHttpError): Resource<never> { return { status: error.httpStatus === 503 || error.httpStatus === 504 ? "UNAVAILABLE" : "ERROR", message: error.message, data: null, error: { code: error.code, httpStatus: error.httpStatus, requestId: error.requestId } }; }
  private async request(path: string, init: RequestInit = {}) {
    if (this.disposed) throw new PaperHttpError("REQUEST_CANCELLED");
    if (this.blocked) throw this.blocked;
    const epoch = this.epoch; const controller = new AbortController(); this.controllers.add(controller);
    try {
      const response = await this.fetcher(`/api/paper/accounts/${encodeURIComponent(this.accountId)}${path}`, { ...init, credentials: "omit", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}) } });
      const text = await response.text();
      if (epoch !== this.epoch || this.disposed) throw new PaperHttpError("REQUEST_CANCELLED");
      if (new TextEncoder().encode(text).byteLength > 2 * 1024 * 1024) throw new PaperHttpError("INVALID_RESPONSE", 502);
      let body: unknown; try { body = JSON.parse(text); } catch { throw new PaperHttpError("INVALID_RESPONSE", 502); }
      if (!response.ok) {
        const error = new PaperHttpError(safePaperCode((body as { error?: { code?: unknown } })?.error?.code, response.status), response.status, response.headers.get("X-Request-ID"));
        if (response.status === 401 || response.status === 403) this.deny(error);
        throw error;
      }
      return body;
    } catch (error) {
      if (error instanceof PaperHttpError) throw error;
      throw new PaperHttpError(epoch !== this.epoch || this.disposed ? "REQUEST_CANCELLED" : "BACKEND_UNAVAILABLE", 503);
    } finally { this.controllers.delete(controller); }
  }
  private assertAccount<T extends { accountId: string }>(item: T): T { if (item.accountId !== this.accountId) throw new PaperHttpError("INVALID_RESPONSE", 502); return item; }
  private setResource(key: MainResource | DetailResource, value: Resource<unknown>, id?: string) {
    if (id) this.update({ [key]: { ...(this.getSnapshot()[key as DetailResource]), [id]: value } }); else this.update({ [key]: value });
  }
  private async read<T>(key: MainResource | DetailResource, loader: () => Promise<T>, id?: string): Promise<T> {
    if (this.blocked) { this.setResource(key, this.failed(this.blocked), id); throw this.blocked; }
    if (this.disposed) throw new PaperHttpError("REQUEST_CANCELLED");
    const sequenceKey = `${key}:${id ?? ""}`; const sequence = (this.sequences.get(sequenceKey) ?? 0) + 1; this.sequences.set(sequenceKey, sequence);
    const epoch = this.epoch;
    // Detail refresh must not unmount the editor and erase a conflicted draft.
    const old = id ? this.getSnapshot()[key as DetailResource][id] : null;
    if (!old?.data && !this.blocked && !this.disposed) this.setResource(key, unloaded(), id);
    try {
      const data = await loader();
      if (epoch !== this.epoch || this.disposed || this.sequences.get(sequenceKey) !== sequence) throw new PaperHttpError("REQUEST_CANCELLED");
      this.setResource(key, ready(data), id); return data;
    } catch (caught) {
      const error = paperFailure(caught);
      if (!this.blocked && !this.disposed && epoch === this.epoch && this.sequences.get(sequenceKey) === sequence) {
        if (old?.data && key === "tradeDetails") this.setResource(key, { ...old, message: error.message, error: { code: error.code, httpStatus: error.httpStatus, requestId: error.requestId } }, id);
        else this.setResource(key, this.failed(error), id);
      }
      throw error;
    }
  }
  private account(): Promise<Account> { return this.read("account", async () => { const account = this.assertAccount(normalizeHttpAccount(await this.request(""))); this.update({ journalCapabilities: { metadata: true, setup: false, userUpload: false, strategyFilter: false } }); return account; }); }
  private orders(query?: PageQuery) { return this.read("orders", async () => normalizeHttpPage(await this.request(`/orders${queryString(query)}`), item => this.assertAccount(normalizeHttpOrder(item)))); }
  private positions() { return this.read("positions", async () => normalizeHttpPage(await this.request("/positions"), item => this.assertAccount(normalizeHttpPosition(item)))); }
  private trades(key: "trades" | "journal", query?: PageQuery) { return this.read(key, async () => normalizeHttpPage(await this.request(`/${key}${queryString(query)}`), item => this.assertAccount(normalizeHttpTrade(item)))); }
  private trade(id: string): Promise<Trade> { return this.read("tradeDetails", async () => { const trade = this.assertAccount(normalizeHttpTrade(await this.request(`/trades/${encodeURIComponent(id)}`))); if (trade.tradeId !== id) throw new PaperHttpError("INVALID_RESPONSE", 502); return trade; }, id); }
  private attachments(id: string, query?: PageQuery): Promise<Page<Attachment>> { return this.read("attachments", async () => normalizeHttpPage(await this.request(`/trades/${encodeURIComponent(id)}/attachments${queryString(query)}`), item => { const attachment = normalizeHttpAttachment(item); if (attachment.accountId !== this.accountId || attachment.tradeId !== id || attachment.url !== null) throw new PaperHttpError("INVALID_RESPONSE", 502); return attachment; }), id); }
  private fills(id: string, query?: PageQuery) { return this.read("fills", async () => normalizeHttpPage(await this.request(`/trades/${encodeURIComponent(id)}/fills${queryString(query)}`), item => { const fill = this.assertAccount(normalizeHttpFill(item)); if (fill.tradeId !== id) throw new PaperHttpError("INVALID_RESPONSE", 502); return fill; }), id); }
  private analytics() { return this.read("analytics", async () => this.assertAccount(normalizeHttpAnalytics(await this.request("/analytics"), presentation.source))); }
  private async refresh() {
    // Read the account after the orders: a fill learned by this cohort must not
    // be paired with an account response sampled before that order read.
    await Promise.allSettled([this.orders()]);
    await Promise.allSettled([this.account(), this.positions(), this.trades("trades"), this.trades("journal"), this.analytics()]);
  }
  private async command(loader: () => Promise<Order>): Promise<ExecutionResponse> {
    try { const order = await loader(); await this.refresh(); return { kind: "ORDER", order }; }
    catch (caught) { const error = paperFailure(caught); return { kind: "ERROR", code: error.code, message: error.message }; }
  }
  private submit(intent: OrderIntent) {
    if (intent.accountId !== this.accountId) return Promise.resolve<ExecutionResponse>({ kind: "ERROR", code: "FORBIDDEN", message: new PaperHttpError("FORBIDDEN").message });
    return this.command(async () => this.assertAccount(normalizeHttpOrder(await this.request("/orders", { method: "POST", body: JSON.stringify(httpOrderBody(intent)) }))));
  }
  private orderCommand(id: string, cancel = false) { return this.command(async () => { const order = this.assertAccount(normalizeHttpOrder(await this.request(`/orders/${encodeURIComponent(id)}${cancel ? "/cancel" : ""}`, cancel ? { method: "POST" } : {}))); if (order.orderId !== id) throw new PaperHttpError("INVALID_RESPONSE", 502); return order; }); }
  private async metadata(id: string, patch: MetadataPatch) {
    try {
      const response = z.object({ annotations: z.object({ notes: z.string(), tags: z.array(z.string()), version: z.number().int().positive(), created_at: z.iso.datetime(), updated_at: z.iso.datetime() }) }).parse(await this.request(`/journal/${encodeURIComponent(id)}/metadata`, { method: "PATCH", body: JSON.stringify(httpMetadataBody(patch)) }));
      const existing = this.getSnapshot().tradeDetails[id]?.data;
      if (existing) this.update({ tradeDetails: { ...this.getSnapshot().tradeDetails, [id]: ready({ ...existing, notes: response.annotations.notes, tags: response.annotations.tags, metadataVersion: response.annotations.version, metadataCreatedAt: response.annotations.created_at, metadataUpdatedAt: response.annotations.updated_at }) } });
      return { kind: "SAVED" as const, metadataVersion: response.annotations.version };
    } catch (caught) {
      const error = paperFailure(caught);
      if (error.code === "CONFLICT") { void this.trade(id).catch(() => {}); return { kind: "CONFLICT" as const, message: error.message }; }
      return { kind: "ERROR" as const, message: error.message };
    }
  }
}
export function createHttpProduct(accountId: string, fetcher?: typeof fetch) { const store = new HttpProductAdapter(accountId, fetcher); return { store, apis: store.apis }; }

export function unavailableHttpProduct(code: string) {
  const store = new HttpProductAdapter("BOOTSTRAP_REQUIRED", async () => { throw new PaperHttpError("BOOTSTRAP_REQUIRED", 503); });
  const failure: Resource<never> = { status: "UNAVAILABLE", data: null, message: new PaperHttpError("BOOTSTRAP_REQUIRED").message, error: { code, httpStatus: 503, requestId: null } };
  store.update({ account: failure, orders: failure, positions: failure, trades: failure, journal: failure, analytics: failure });
  return { store, apis: store.apis };
}
