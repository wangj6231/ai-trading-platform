"use client";
import type { ResourceStatus } from "@/lib/product/contracts";
import { fixtureIntentInstructions, fixtureLongPlan, fixtureScenarios, fixtureShortPlan, type FixtureScenario } from "@/lib/product/fixtures";
import { useProduct } from "./product-provider";
export function FixtureControls() {
  const { snapshot, fixtureControls, openPlan } = useProduct();
  if (!fixtureControls) return null;
  const load = (id: FixtureScenario) => { fixtureControls.scenario(id); openPlan(id === "A" ? fixtureLongPlan : id === "E" ? fixtureShortPlan : null); };
  return <details className="fixture-controls"><summary>DEV / FIXTURE controls · scenario {snapshot.fixtureOnly?.scenario} · {snapshot.fixtureOnly?.status}</summary><div className="fixture-controls-inner">
    <label>Scenario<select aria-label="Fixture scenario" value={snapshot.fixtureOnly?.scenario} onChange={(event) => { load(event.target.value as FixtureScenario); }}>{fixtureScenarios.map((row) => <option value={row.id} key={row.id}>{row.label}</option>)}</select></label>
    <label>Module state<select aria-label="Fixture module state" value={snapshot.fixtureOnly?.status} onChange={(event) => fixtureControls.resource(event.target.value as ResourceStatus)}>{["READY", "LOADING", "EMPTY", "ERROR", "UNAVAILABLE"].map((state) => <option key={state}>{state}</option>)}</select></label>
    <div className="product-actions"><button type="button" onClick={() => load(snapshot.fixtureOnly?.scenario as FixtureScenario)}>Load selected scenario</button><button type="button" onClick={() => load("A")}>Reset fixture session</button></div>
    <p>{fixtureIntentInstructions}</p><p>Explicit demonstration only. Scenario changes reset session data. A → fills → B scale in → C partial close → D close. E keeps a SHORT plan with a separately chosen BUY order.</p>
  </div></details>;
}
