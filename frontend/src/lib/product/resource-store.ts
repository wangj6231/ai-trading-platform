import { createProductSnapshot, normalizeProductSnapshot, type ProductSnapshot } from "./contracts";

// Resource state only. Transport/provider wiring is deliberately outside this reconciliation.
export class ProductResourceStore {
  private snapshot: ProductSnapshot;
  private listeners = new Set<() => void>();
  constructor(accountId: string, presentation: Pick<ProductSnapshot, "source" | "environmentLabel" | "notice">) {
    this.snapshot = createProductSnapshot(accountId, presentation);
  }
  getSnapshot = () => this.snapshot;
  subscribe = (callback: () => void) => { this.listeners.add(callback); return () => { this.listeners.delete(callback); }; };
  async initialize() { return; }
  update(patch: Partial<Omit<ProductSnapshot, "accountId">>) {
    this.snapshot = normalizeProductSnapshot({ ...this.snapshot, ...patch });
    this.listeners.forEach(callback => callback());
  }
}
