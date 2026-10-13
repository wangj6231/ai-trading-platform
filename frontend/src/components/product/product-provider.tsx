"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import type { ProductApis, ProductSnapshot, ResourceStatus, StrategyPlan, RuntimeSelection } from "@/lib/product/contracts";
import { createHttpProduct, unavailableHttpProduct } from "@/lib/product/http-adapter";
import { createFixtureProduct } from "@/lib/product/fixture-adapters";
import type { FixtureScenario } from "@/lib/product/fixtures";

export interface ProductRuntime {
  apis: ProductApis;
  store: { getSnapshot: () => ProductSnapshot; subscribe: (callback: () => void) => () => void; initialize: () => Promise<void>; dispose?: () => void };
  fixtureControls?: { scenario: (id: FixtureScenario) => void; resource: (state: ResourceStatus) => void };
}
interface ProductContextValue { snapshot: ProductSnapshot; apis: ProductApis; plan: StrategyPlan | null; openPlan: (plan: StrategyPlan | null) => void; fixtureControls?: ProductRuntime["fixtureControls"] }
const ProductContext = createContext<ProductContextValue | null>(null);
function fixtureRuntime(): ProductRuntime {
  const { store, apis } = createFixtureProduct();
  return { store, apis, fixtureControls: { scenario: (id) => store.scenario(id), resource: (state) => store.resource(state) } };
}
export function ProductProvider({ children, runtime, selection = { mode: "FIXTURE" } }: { children: ReactNode; runtime?: ProductRuntime; selection?: RuntimeSelection }) {
  return <ProductSession key={runtime ? undefined : JSON.stringify(selection)} runtime={runtime} selection={selection}>{children}</ProductSession>;
}
function ProductSession({ children, runtime, selection }: { children: ReactNode; runtime?: ProductRuntime; selection: RuntimeSelection }) {
  const [active] = useState<ProductRuntime>(() => runtime ?? (selection.mode === "HTTP" ? createHttpProduct(selection.accountId) : selection.mode === "UNAVAILABLE" ? unavailableHttpProduct(selection.code) : fixtureRuntime()));
  const [plan, openPlan] = useState<StrategyPlan | null>(null);
  const snapshot = useSyncExternalStore(active.store.subscribe, active.store.getSnapshot, active.store.getSnapshot);
  useEffect(() => { void active.store.initialize(); return () => active.store.dispose?.(); }, [active]);
  return <ProductContext.Provider value={{ snapshot, apis: active.apis, plan, openPlan, fixtureControls: active.fixtureControls }}>{children}</ProductContext.Provider>;
}
export function useProduct() {
  const context = useContext(ProductContext);
  if (!context) throw new Error("ProductProvider is required.");
  return context;
}
