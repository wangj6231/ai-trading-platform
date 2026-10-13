import { normalizeProductSnapshot, orderIntentSchema, orderSchema, type AccountApi, type AnalyticsApi, type ExecutionApi, type ExecutionResponse, type JournalApi, type Order, type OrderIntent, type ProductApis, type ResourceStatus, type MetadataPatch, type MetadataResult, type Trade } from "./contracts";
import { baseFixtureSnapshot, toProductSnapshot, fixturePage, type FixtureSnapshot, directCloseFixture, fixtureAnalytics, fixtureTime, lifecycleOrders, lifecycleTrade, positionFromTrade, type FixtureScenario, type LifecycleStep } from "./fixtures";

// Entirely session-local DEV simulation. No HTTP execution or accounting algorithm lives here.
export class FixtureProductStore {
  private snapshot: FixtureSnapshot = { ...baseFixtureSnapshot(), status: "LOADING" };
  private view = toProductSnapshot(this.snapshot);
  private commands = new Map<string, { intent: string; orderId: string }>();
  private listeners = new Set<() => void>();
  private sequence = 0;
  private epoch = 0;
  private busy = false;
  private initializing = true;
  private uploadUrls: string[] = [];
  step: LifecycleStep | null = null;
  constructor(private delayMs = 180) {}
  getSnapshot = () => this.view;
  subscribe = (callback: () => void) => { this.listeners.add(callback); return () => { this.listeners.delete(callback); }; };
  publish(snapshot: FixtureSnapshot) { this.view = normalizeProductSnapshot(toProductSnapshot(snapshot)); this.snapshot = snapshot; this.listeners.forEach((listener) => listener()); }
  patch(patch: Partial<FixtureSnapshot>) { this.publish({ ...this.snapshot, ...patch }); }
  async pause() { if (this.delayMs) await new Promise((resolve) => setTimeout(resolve, this.delayMs)); }
  async initialize() { const epoch = this.epoch; await this.pause(); if (epoch === this.epoch && this.initializing) { this.initializing = false; this.patch({ status: "READY" }); } }
  scenario(id: FixtureScenario) {
    this.epoch++; this.initializing = false; this.busy = false; this.step = null; this.sequence = 0; this.commands.clear();
    this.uploadUrls.forEach((url) => URL.revokeObjectURL(url)); this.uploadUrls = [];
    this.publish({ ...baseFixtureSnapshot(id), sessionReference: `dev-session-${this.epoch}` });
  }
  resource(status: ResourceStatus) { this.initializing = false; this.patch({ status, message: status === "ERROR" ? "DEV fixture service error. No execution outcome inferred." : status === "UNAVAILABLE" ? "This module's backend adapter is not connected." : null }); }
  async exclusive(operation: () => Promise<ExecutionResponse>): Promise<ExecutionResponse> {
    if (this.busy) return { kind: "ERROR", message: "Another fixture command is pending. Wait for its response." };
    if (this.snapshot.status !== "READY") return { kind: "ERROR", message: "Account data is not ready." };
    this.busy = true;
    const epoch = this.epoch;
    try { return await operation(); } finally { if (epoch === this.epoch) this.busy = false; }
  }
  async submit(input: OrderIntent): Promise<ExecutionResponse> {
    return this.exclusive(async () => {
      const parsed = orderIntentSchema.safeParse(input);
      if (!parsed.success) return { kind: "ERROR", message: parsed.error.issues[0].message };
      const intent = parsed.data;
      const identity = JSON.stringify({ accountId: intent.accountId, symbol: intent.symbol, side: intent.side, type: intent.type, quantity: intent.quantity, limitPrice: intent.limitPrice });
      const prior = this.commands.get(intent.commandId);
      if (prior) {
        if (prior.intent !== identity) return { kind: "ERROR", code: "CONFLICT", message: "Command identity already belongs to a different intent." };
        const priorOrder = this.snapshot.orders.find(row => row.orderId === prior.orderId);
        if (priorOrder) return { kind: "ORDER", order: structuredClone(priorOrder) };
      }
      if (intent.accountId !== this.snapshot.account?.accountId) return { kind: "ERROR", message: "Account identity mismatch." };
      const capability = this.snapshot.account.capabilities;
      if ((intent.type === "MARKET" && !capability.supportsMarketOrder) || (intent.type === "LIMIT" && !capability.supportsLimitOrder) || (intent.side === "SELL" && !capability.supportsShort)) return { kind: "ERROR", message: "Account capability does not support this intent." };
      if (this.snapshot.scenario === "TECHNICAL") { await this.pause(); return { kind: "ERROR", message: "Technical connection error. No order acknowledgment or rejection received." }; }
      const epoch = this.epoch;
      const order = orderSchema.parse({ ...lifecycleOrders[0], ...intent, orderId: `dev-intent-${++this.sequence}`, status: "ACKNOWLEDGED", filledQuantity: "0", averageFill: null, submittedAt: fixtureTime, executionProvider: this.snapshot.account.executionProvider, environment: this.snapshot.account.environment, message: null });
      await this.pause();
      if (epoch !== this.epoch) return { kind: "ERROR", message: "Fixture scenario changed; prior command disconnected." };
      const supported = intent.symbol === "BTCUSDT" && intent.side === "BUY" && intent.quantity === "0.1" && (intent.type === "MARKET" || intent.limitPrice === "105") && this.step === null && !["H", "K"].includes(this.snapshot.scenario);
      const status = this.snapshot.scenario === "G" ? "UNKNOWN" : this.snapshot.scenario === "F" || !supported ? "REJECTED" : "ACKNOWLEDGED";
      const next: Order = { ...order, status, message: status === "UNKNOWN" ? "Outcome is unknown. Await reconciliation; no confirmed fills." : status === "REJECTED" ? "DEV script rejected this intent. Supported demo: BTCUSDT BUY 0.1, MARKET or LIMIT 105; start from a fresh scenario." : "Acknowledged only. Advance the DEV fixture to receive confirmed fills." };
      this.commands.set(intent.commandId, { intent: identity, orderId: order.orderId });
      this.patch({ orders: [...this.snapshot.orders, next] });
      return { kind: "ORDER", order: next };
    });
  }
  async confirm(orderId: string): Promise<ExecutionResponse> {
    return this.exclusive(async () => {
      const order = this.snapshot.orders.find((row) => row.orderId === orderId);
      if (!order || !["ACKNOWLEDGED", "PARTIALLY_FILLED"].includes(order.status) || order.filledQuantity === "0" && this.step !== null) return { kind: "ERROR", message: "No eligible fixture order to advance." };
      const epoch = this.epoch; await this.pause();
      if (epoch !== this.epoch) return { kind: "ERROR", message: "Fixture scenario changed." };
      const step = order.status === "ACKNOWLEDGED" ? "PARTIAL_FILL" : "OPEN";
      const next: Order = { ...order, status: step === "PARTIAL_FILL" ? "PARTIALLY_FILLED" : "FILLED", filledQuantity: step === "PARTIAL_FILL" ? "0.06" : "0.1", averageFill: step === "PARTIAL_FILL" ? "99" : "100", message: "Confirmed DEV adapter fills, not market execution." };
      const trade = lifecycleTrade(step, order.plan ?? null);
      trade.fills = trade.fills.map((fill) => ({ ...fill, orderId }));
      this.step = step;
      this.applyTrade(trade, this.snapshot.orders.map((row) => row.orderId === orderId ? next : row));
      return { kind: "ORDER", order: next };
    });
  }
  private applyTrade(trade: Trade, orders: Order[]) {
    const account = {
      PARTIAL_FILL: { balance: "9999.995", equity: "10000.055", realizedPnl: "0", unrealizedPnl: "0.06" },
      OPEN: { balance: "9999.99", equity: "10000.39", realizedPnl: "0", unrealizedPnl: "0.40" },
      SCALED: { balance: "9999.985", equity: "10000.435", realizedPnl: "0", unrealizedPnl: "0.45" },
      PARTIAL_CLOSE: { balance: "10000.13", equity: "10000.43", realizedPnl: "0.16", unrealizedPnl: "0.30" },
      CLOSED: { balance: "10000.62", equity: "10000.62", realizedPnl: "0.65", unrealizedPnl: "0" },
    }[this.step ?? "OPEN"];
    this.patch({ orders, positions: [positionFromTrade(trade)], trades: [trade], account: { ...this.snapshot.account!, ...account }, analytics: fixtureAnalytics([trade]) });
  }
  async cancel(orderId: string): Promise<ExecutionResponse> {
    return this.exclusive(async () => {
      const order = this.snapshot.orders.find((row) => row.orderId === orderId);
      if (!order || !["ACKNOWLEDGED", "PARTIALLY_FILLED"].includes(order.status)) return { kind: "ERROR", message: "This outcome cannot be cancelled in the DEV script. UNKNOWN requires reconciliation." };
      const next: Order = { ...order, status: "CANCELLED", message: "Fixture cancel confirmed; any previous fills remain immutable." };
      this.patch({ orders: this.snapshot.orders.map((row) => row.orderId === orderId ? next : row) });
      return { kind: "ORDER", order: next };
    });
  }
  async positionAction(positionId: string, action: "SCALE_IN" | "PARTIAL_CLOSE" | "CLOSE"): Promise<ExecutionResponse> {
    return this.exclusive(async () => {
      const trade = this.snapshot.trades.find((row) => row.positionId === positionId);
      if (trade && action === "CLOSE" && this.step && ["PARTIAL_FILL", "OPEN", "SCALED"].includes(this.step)) {
        const epoch = this.epoch; await this.pause(); if (epoch !== this.epoch) return { kind: "ERROR", message: "Fixture scenario changed." };
        const closed = directCloseFixture(trade, this.step as "PARTIAL_FILL" | "OPEN" | "SCALED");
        this.step = "CLOSED";
        const orders = this.snapshot.orders.map((order) => order.status === "PARTIALLY_FILLED" ? { ...order, status: "CANCELLED" as const, message: "Remaining fixture quantity cancelled; confirmed fills retained." } : order);
        this.patch({ orders: [...orders, closed.order], positions: [positionFromTrade(closed.trade)], trades: [closed.trade], account: { ...this.snapshot.account!, ...closed.account }, analytics: fixtureAnalytics([closed.trade]) });
        return { kind: "ORDER", order: closed.order };
      }
      const expected = action === "SCALE_IN" ? "OPEN" : action === "PARTIAL_CLOSE" ? "SCALED" : "PARTIAL_CLOSE";
      if (!trade || this.step !== expected) return { kind: "ERROR", message: "This deterministic fixture follows B scale in → C partial close → D close. Use the next supported step." };
      const epoch = this.epoch; await this.pause(); if (epoch !== this.epoch) return { kind: "ERROR", message: "Fixture scenario changed." };
      const order = structuredClone(lifecycleOrders[action === "SCALE_IN" ? 1 : action === "PARTIAL_CLOSE" ? 2 : 3]);
      this.step = action === "SCALE_IN" ? "SCALED" : action === "PARTIAL_CLOSE" ? "PARTIAL_CLOSE" : "CLOSED";
      const next = lifecycleTrade(this.step, trade.plan ?? null);
      next.fills = [...trade.fills, ...next.fills.slice(trade.fills.length)];
      next.notes = trade.notes; next.tags = trade.tags; next.setup = trade.setup; next.metadataVersion = trade.metadataVersion; next.fixtureOnly!.attachments = trade.fixtureOnly!.attachments;
      this.applyTrade(next, [...this.snapshot.orders, order]);
      return { kind: "ORDER", order };
    });
  }
  saveMetadata(tradeId: string, metadata: MetadataPatch): MetadataResult {
    const trade = this.snapshot.trades.find(row => row.tradeId === tradeId);
    if (!trade) return { kind: "ERROR", message: "Trade not found." };
    if (metadata.expectedVersion !== trade.metadataVersion) return { kind: "CONFLICT", message: "Review metadata changed. Reload the latest version before saving." };
    if (this.snapshot.scenario === "K" && metadata.setup !== undefined) return { kind: "ERROR", message: "Setup is NOT_READY." };
    const { notes, tags, setup } = metadata;
    const metadataVersion = trade.metadataVersion + 1;
    this.patch({ trades: this.snapshot.trades.map(row => row.tradeId === tradeId ? { ...row, notes, tags, ...(setup === undefined ? {} : { setup }), metadataVersion } : row) });
    return { kind: "SAVED", metadataVersion };
  }
  upload(tradeId: string, file: File) {
    if (this.snapshot.scenario === "K") throw new Error("USER_UPLOAD is NOT_READY.");
    if (!this.snapshot.trades.some((trade) => trade.tradeId === tradeId)) throw new Error("Trade not found.");
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 5_000_000) throw new Error("Choose a PNG, JPEG or WebP image up to 5 MB.");
    const url = URL.createObjectURL(file); this.uploadUrls.push(url);
    this.patch({ trades: this.snapshot.trades.map((trade) => trade.tradeId !== tradeId ? trade : { ...trade, fixtureOnly: { ...trade.fixtureOnly!, attachments: [...trade.fixtureOnly!.attachments, { attachmentId: `dev-upload-${++this.sequence}`, kind: "USER_UPLOAD", status: "READY", url, message: "Session-only local upload; no backend storage.", source: "DEV / FIXTURE · LOCAL UPLOAD" }] } }) });
  }
}
export class FixtureAccountApi implements AccountApi { constructor(private store: FixtureProductStore) {} async getAccount() { return structuredClone(this.store.getSnapshot().account.data); } }
export class FixtureExecutionApi implements ExecutionApi {
  constructor(private store: FixtureProductStore) {}
  submit(intent: OrderIntent) { return this.store.submit(intent); }
  refreshOrder(orderId: string) { return this.store.confirm(orderId); }
  cancel(orderId: string) { return this.store.cancel(orderId); }
  positionAction(positionId: string, action: "SCALE_IN" | "PARTIAL_CLOSE" | "CLOSE") { return this.store.positionAction(positionId, action); }
  async getOrders() { return structuredClone(this.store.getSnapshot().orders.data!); }
  async getPositions() { return structuredClone(this.store.getSnapshot().positions.data!); }
}
export class FixtureJournalApi implements JournalApi {
  constructor(private store: FixtureProductStore) {}
  async getTrades() { return structuredClone(this.store.getSnapshot().trades.data!); }
  async getJournal() { return structuredClone(this.store.getSnapshot().journal.data!); }
  async getTrade(tradeId: string) { return structuredClone(this.store.getSnapshot().tradeDetails[tradeId]?.data ?? null); }
  async getAttachments(tradeId: string) { return structuredClone(this.store.getSnapshot().attachments[tradeId]?.data ?? fixturePage([])); }
  async saveMetadata(tradeId: string, metadata: MetadataPatch) { return this.store.saveMetadata(tradeId, metadata); }
  async addUpload(tradeId: string, file: File) { this.store.upload(tradeId, file); }
}
export class FixtureAnalyticsApi implements AnalyticsApi { constructor(private store: FixtureProductStore) {} async getAnalytics() { return structuredClone(this.store.getSnapshot().analytics.data); } }
export function createFixtureProduct(delayMs = 180): { store: FixtureProductStore; apis: ProductApis } {
  const store = new FixtureProductStore(delayMs);
  return { store, apis: { account: new FixtureAccountApi(store), execution: new FixtureExecutionApi(store), journal: new FixtureJournalApi(store), analytics: new FixtureAnalyticsApi(store) } };
}
