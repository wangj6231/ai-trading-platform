import { describe, expect, it } from "vitest";
import {
  levelAvailabilityStart,
  projectZoneWindows,
  projectStructureMarkers,
  projectSwingMarkers,
  zoneAvailabilityStart,
  zoneAvailabilityWindow,
} from "@/lib/chart-view-model";
import { normalizeAnalysis } from "@/lib/api";

const PIVOT_AT = "2025-01-01T00:05:00Z";
const CONFIRMED_AT = "2025-01-01T00:07:00Z";
const FVG_CONFIRMED_AT = "2025-01-01T00:09:00Z";
const FVG_CREATED_AT = FVG_CONFIRMED_AT;
const FVG_SOURCE_AT = "2025-01-01T00:08:00Z";
const OB_CREATED_AT = "2025-01-01T00:10:00Z";
const OB_VALIDATED_AT = "2025-01-01T00:12:00Z";
const FVG_FILLED_AT = "2025-01-01T00:15:00Z";

const payload = {
  symbol: "BTCUSDT",
  timeframe: "5m",
  source: "server-provider",
  retrieved_at: "2025-01-01T00:21:00Z",
  data_cutoff_at: "2025-01-01T00:20:00Z",
  provenance: {
    provider: "server-provider",
    data_mode: "SERVER_PROVIDER",
    symbol: "BTCUSDT",
    timeframe: "5m",
    first_candle_at: "2024-12-31T18:00:00Z",
    last_candle_at: "2025-01-01T00:15:00Z",
    data_cutoff_at: "2025-01-01T00:20:00Z",
    expected_latest_closed_candle_at: "2025-01-01T00:20:00Z",
    retrieved_at: "2025-01-01T00:21:00Z",
    requested_candles: 500,
    received_candles: 500,
    lag_seconds: 0,
    market_schedule_mode: "CONTINUOUS_24_7",
    session_calendar_id: null,
    session_calendar_version: null,
    session_calendar_hash: null,
    validated: true,
  },
  evaluation: {
    indicator_snapshot: null,
    market_structure_snapshot: {
      "5m": {
        confirmed_swings: [
          {
            swing_id: "swing-1",
            kind: "HIGH",
            pivot_timestamp: PIVOT_AT,
            confirmed_at: CONFIRMED_AT,
            price: 110,
          },
        ],
        support_candidates: [
          {
            zone_id: "support-1",
            kind: "SUPPORT",
            lower_bound: 99,
            upper_bound: 100,
            anchor_price: 100,
            created_at: CONFIRMED_AT,
          },
        ],
        resistance_candidates: [],
        structure_events: [
          {
            type: "MSS",
            direction: "bearish",
            timestamp: PIVOT_AT,
            confirmed_at: CONFIRMED_AT,
            price: 99,
            broken_structure_id: "swing-1",
          },
        ],
      },
    },
    smc_ict_snapshot: {
      fvg: {
        zones: [
          {
            zone_id: "fvg-1",
            type: "FVG",
            direction: "bullish",
            lower: 101,
            upper: 103,
            created_at: FVG_CREATED_AT,
            confirmed_at: FVG_CONFIRMED_AT,
            status: "OPEN",
            lifecycle_state: "ACTIVE",
            last_updated_at: FVG_CONFIRMED_AT,
            lifecycle: [
              {
                event_type: "FVG_CREATED",
                zone_id: "fvg-1",
                bar_timestamp: FVG_SOURCE_AT,
                occurred_at: FVG_CONFIRMED_AT,
                from_state: null,
                to_state: "ACTIVE",
                fill_fraction: 0,
                retest_count: 0,
              },
            ],
          },
        ],
      },
      order_blocks: {
        order_blocks: [
          {
            zone_id: "ob-1",
            direction: "bullish",
            zone_low: 97,
            zone_high: 99,
            created_at: OB_CREATED_AT,
            validated_at: OB_VALIDATED_AT,
            mitigated_at: null,
            invalidated_at: null,
            status: "VALIDATED",
            lifecycle: [
              {
                event_id: "ob-1:created",
                type: "OB_CREATED",
                zone_id: "ob-1",
                bar_timestamp: OB_CREATED_AT,
                confirmed_at: OB_CREATED_AT,
                from_status: null,
                to_status: "CANDIDATE",
                mean_threshold_held: null,
              },
              {
                event_id: "ob-1:validated",
                type: "OB_VALIDATED",
                zone_id: "ob-1",
                bar_timestamp: OB_VALIDATED_AT,
                confirmed_at: OB_VALIDATED_AT,
                from_status: "CANDIDATE",
                to_status: "VALIDATED",
                mean_threshold_held: null,
              },
            ],
          },
        ],
      },
    },
  },
};

function terminalOrderBlock(
  zoneId: string,
  status: "INVALIDATED" | "EXPIRED",
  terminalAt: string,
) {
  const base = payload.evaluation.smc_ict_snapshot.order_blocks.order_blocks[0];
  return {
    ...base,
    zone_id: zoneId,
    status,
    invalidated_at: status === "INVALIDATED" ? terminalAt : null,
    lifecycle: [
      ...base.lifecycle.map((event) => ({ ...event, zone_id: zoneId })),
      {
        event_id: `${zoneId}:terminal`,
        type: status === "INVALIDATED" ? "OB_INVALIDATED" : "OB_EXPIRED",
        zone_id: zoneId,
        bar_timestamp: terminalAt,
        confirmed_at: terminalAt,
        from_status: "VALIDATED",
        to_status: status,
        mean_threshold_held: null,
      },
    ],
  };
}

describe("point-in-time chart projections", () => {
  it("distinguishes a swing pivot from its confirmation timestamp", () => {
    const analysis = normalizeAnalysis(payload, "BTCUSDT", "5m");
    const markers = projectSwingMarkers(analysis.swings);

    expect(markers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ at: PIVOT_AT, availability: "PIVOT_ONLY", label: "SH PIVOT" }),
        expect.objectContaining({ at: CONFIRMED_AT, availability: "CONFIRMED", label: "SH CONFIRMED" }),
      ]),
    );
    expect(projectStructureMarkers(analysis.structures)[0].at).toBe(CONFIRMED_AT);
  });

  it("starts SR, FVG, and OB rendering at their real availability timestamps", () => {
    const analysis = normalizeAnalysis(payload, "BTCUSDT", "5m");
    const fvg = analysis.zones.find((zone) => zone.kind === "FVG")!;
    const orderBlock = analysis.zones.find((zone) => zone.kind === "ORDER_BLOCK")!;

    expect(levelAvailabilityStart(analysis.supports[0])).toBe(CONFIRMED_AT);
    expect(analysis.supports[0].confirmedAt).toBeNull();
    expect(zoneAvailabilityStart(fvg)).toBe(FVG_CONFIRMED_AT);
    expect(fvg.createdAt).toBe(FVG_CREATED_AT);
    expect(zoneAvailabilityStart(orderBlock)).toBe(OB_VALIDATED_AT);
    expect(zoneAvailabilityStart(orderBlock)).not.toBe(OB_CREATED_AT);
  });

  it("retains the terminal FVG lifecycle needed to audit its historical window", () => {
    const terminalPayload = {
      ...payload,
      evaluation: {
        ...payload.evaluation,
        smc_ict_snapshot: {
          ...payload.evaluation.smc_ict_snapshot,
          fvg: {
            zones: [
              {
                ...payload.evaluation.smc_ict_snapshot.fvg.zones[0],
                status: "FILLED",
                lifecycle_state: "FILLED",
                last_updated_at: FVG_FILLED_AT,
                lifecycle: [
                  {
                    event_type: "FVG_CREATED",
                    zone_id: "fvg-1",
                    bar_timestamp: FVG_CREATED_AT,
                    occurred_at: FVG_CONFIRMED_AT,
                    from_state: null,
                    to_state: "ACTIVE",
                    fill_fraction: 0,
                    retest_count: 0,
                  },
                  {
                    event_type: "FVG_FILLED",
                    zone_id: "fvg-1",
                    bar_timestamp: FVG_FILLED_AT,
                    occurred_at: FVG_FILLED_AT,
                    from_state: "ACTIVE",
                    to_state: "FILLED",
                    fill_fraction: 1,
                    retest_count: 1,
                  },
                ],
              },
            ],
          },
        },
      },
    };

    const fvg = normalizeAnalysis(terminalPayload, "BTCUSDT", "5m").zones[0];

    expect(fvg).toMatchObject({
      status: "FILLED",
      lifecycleState: "FILLED",
      updatedAt: FVG_FILLED_AT,
      terminalAt: FVG_FILLED_AT,
      isTerminal: true,
    });
    expect(
      zoneAvailabilityWindow(fvg, "2025-01-01T01:00:00Z"),
    ).toEqual({
      from: FVG_CONFIRMED_AT,
      to: FVG_FILLED_AT,
      terminal: true,
    });
    expect(zoneAvailabilityWindow(fvg, "2025-01-02T00:00:00Z")).toEqual(
      zoneAvailabilityWindow(fvg, "2025-01-03T00:00:00Z"),
    );
  });

  it("keeps invalidated and expired order blocks as frozen historical segments", () => {
    const invalidatedAt = "2025-01-01T00:16:00Z";
    const expiredAt = "2025-01-01T00:17:00Z";
    const terminalPayload = {
      ...payload,
      evaluation: {
        ...payload.evaluation,
        smc_ict_snapshot: {
          ...payload.evaluation.smc_ict_snapshot,
          order_blocks: {
            order_blocks: [
              terminalOrderBlock("ob-invalidated", "INVALIDATED", invalidatedAt),
              terminalOrderBlock("ob-expired", "EXPIRED", expiredAt),
            ],
          },
        },
      },
    };

    const projections = projectZoneWindows(
      normalizeAnalysis(terminalPayload, "BTCUSDT", "5m").zones.filter(
        (zone) => zone.kind === "ORDER_BLOCK",
      ),
      "2025-01-02T00:00:00Z",
    );

    expect(projections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          to: invalidatedAt,
          terminal: true,
          zone: expect.objectContaining({
            id: "ob-invalidated",
            lifecycleState: "INVALIDATED",
            invalidatedAt,
          }),
        }),
        expect.objectContaining({
          to: expiredAt,
          terminal: true,
          zone: expect.objectContaining({
            id: "ob-expired",
            lifecycleState: "EXPIRED",
          }),
        }),
      ]),
    );
  });

  it("retains an order-block mitigation timestamp without treating it as terminal", () => {
    const mitigatedAt = "2025-01-01T00:14:00Z";
    const base = payload.evaluation.smc_ict_snapshot.order_blocks.order_blocks[0];
    const mitigatedPayload = {
      ...payload,
      evaluation: {
        ...payload.evaluation,
        smc_ict_snapshot: {
          ...payload.evaluation.smc_ict_snapshot,
          order_blocks: {
            order_blocks: [
              {
                ...base,
                status: "MITIGATED",
                mitigated_at: mitigatedAt,
                lifecycle: [
                  ...base.lifecycle,
                  {
                    event_id: "ob-1:mitigated",
                    type: "OB_MITIGATED",
                    zone_id: "ob-1",
                    bar_timestamp: mitigatedAt,
                    confirmed_at: mitigatedAt,
                    from_status: "VALIDATED",
                    to_status: "MITIGATED",
                    mean_threshold_held: true,
                  },
                ],
              },
            ],
          },
        },
      },
    };

    const orderBlock = normalizeAnalysis(mitigatedPayload, "BTCUSDT", "5m").zones.find(
      (zone) => zone.kind === "ORDER_BLOCK",
    )!;

    expect(orderBlock).toMatchObject({
      lifecycleState: "MITIGATED",
      updatedAt: mitigatedAt,
      mitigatedAt,
      invalidatedAt: null,
      terminalAt: null,
      isTerminal: false,
    });
    expect(zoneAvailabilityWindow(orderBlock, "2025-01-01T00:20:00Z")).toEqual({
      from: OB_VALIDATED_AT,
      to: "2025-01-01T00:20:00Z",
      terminal: false,
    });
  });

  it("extends only non-terminal zones to the current chart end", () => {
    const chartEndAt = "2025-01-01T00:20:00Z";
    const projections = projectZoneWindows(
      normalizeAnalysis(payload, "BTCUSDT", "5m").zones,
      chartEndAt,
    );

    expect(projections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          to: chartEndAt,
          terminal: false,
          zone: expect.objectContaining({ id: "fvg-1" }),
        }),
        expect.objectContaining({
          to: chartEndAt,
          terminal: false,
          zone: expect.objectContaining({ id: "ob-1" }),
        }),
      ]),
    );
  });

  it("rejects unknown or inconsistent lifecycle values", () => {
    const fvg = payload.evaluation.smc_ict_snapshot.fvg.zones[0];
    const invalidStatusPayload = {
      ...payload,
      evaluation: {
        ...payload.evaluation,
        smc_ict_snapshot: {
          ...payload.evaluation.smc_ict_snapshot,
          fvg: { zones: [{ ...fvg, status: "MAGIC_WIN" }] },
        },
      },
    };
    const inconsistentLifecyclePayload = {
      ...payload,
      evaluation: {
        ...payload.evaluation,
        smc_ict_snapshot: {
          ...payload.evaluation.smc_ict_snapshot,
          fvg: { zones: [{ ...fvg, lifecycle_state: "FILLED" }] },
        },
      },
    };

    expect(() =>
      normalizeAnalysis(invalidStatusPayload, "BTCUSDT", "5m"),
    ).toThrow();
    expect(() =>
      normalizeAnalysis(inconsistentLifecyclePayload, "BTCUSDT", "5m"),
    ).toThrow();
  });
});
