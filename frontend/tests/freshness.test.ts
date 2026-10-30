import { expect, it } from "vitest";
import { snapshotStatus } from "@/lib/freshness";
import { signalFixture } from "./fixtures/mtf-contract";
import { parseSignalPayload } from "@/lib/api";

const provenance = parseSignalPayload(signalFixture, "BTCUSDT").provenance!;

it("ages a 15m snapshot on the next close without changing its decision", () => {
  const data = provenance;
  expect(snapshotStatus(data, Date.parse("2025-01-01T00:44:59Z"))).toBe("CURRENT");
  expect(snapshotStatus(data, Date.parse("2025-01-01T00:45:00Z"))).toBe("STALE");
  expect(signalFixture.final_decision).toBe("LONG");
});
it("shows server lag and missing provenance distinctly", () => {
  expect(snapshotStatus({ ...provenance, lag_seconds: 60 }, Date.parse(signalFixture.retrieved_at))).toBe("STALE");
  expect(snapshotStatus(undefined, Date.now())).toBe("UNKNOWN");
});
it("uses Monday UTC weekly closes rather than epoch Thursday", () => {
  const weekly = { ...provenance, timeframe: "1w" as const, data_cutoff_at: "2024-12-30T00:00:00Z" };
  expect(snapshotStatus(weekly, Date.parse("2025-01-05T23:59:59Z"))).toBe("CURRENT");
  expect(snapshotStatus(weekly, Date.parse("2025-01-06T00:00:00Z"))).toBe("STALE");
});
