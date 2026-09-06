import type {
  LevelOverlay,
  SignalViewModel,
  StructureOverlay,
  SwingOverlay,
  ZoneOverlay,
} from "@/types/trading";

export interface LifecycleMarkerProjection {
  id: string;
  at: string;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "circle" | "arrowUp" | "arrowDown";
  label: string;
  availability: "PIVOT_ONLY" | "CONFIRMED";
}

export function projectSwingMarkers(swings: SwingOverlay[]): LifecycleMarkerProjection[] {
  return swings.flatMap((swing) => {
    const position = swing.kind === "HIGH" ? "aboveBar" : "belowBar";
    return [
      {
        id: `${swing.id}:pivot`,
        at: swing.pivotAt,
        position,
        color: "#59677a",
        shape: "circle",
        label: `${swing.kind === "HIGH" ? "SH" : "SL"} PIVOT`,
        availability: "PIVOT_ONLY",
      },
      {
        id: `${swing.id}:confirmed`,
        at: swing.confirmedAt,
        position,
        color: swing.kind === "HIGH" ? "#e0a65b" : "#50b9ff",
        shape: "circle",
        label: `${swing.kind === "HIGH" ? "SH" : "SL"} CONFIRMED`,
        availability: "CONFIRMED",
      },
    ];
  });
}

export function projectStructureMarkers(
  events: StructureOverlay[],
): LifecycleMarkerProjection[] {
  return events.map((event) => ({
    id: event.id,
    at: event.confirmedAt,
    position: event.direction === "bullish" ? "belowBar" : "aboveBar",
    color: event.type === "MSS" ? "#c185ff" : "#f1c75b",
    shape: event.direction === "bullish" ? "arrowUp" : "arrowDown",
    label: `${event.type} CONFIRMED`,
    availability: "CONFIRMED",
  }));
}

export function levelAvailabilityStart(level: LevelOverlay): string {
  return level.confirmedAt ?? level.createdAt;
}

export function zoneAvailabilityStart(zone: ZoneOverlay): string | null {
  if (zone.kind === "ORDER_BLOCK") return zone.validatedAt;
  return zone.confirmedAt;
}

export interface ZoneAvailabilityWindow {
  from: string;
  to: string;
  terminal: boolean;
}

export function zoneAvailabilityWindow(
  zone: ZoneOverlay,
  chartEndAt: string,
): ZoneAvailabilityWindow | null {
  const from = zoneAvailabilityStart(zone);
  if (from === null) return null;
  return {
    from,
    to: zone.terminalAt ?? chartEndAt,
    terminal: zone.isTerminal,
  };
}

export interface ZoneRenderProjection extends ZoneAvailabilityWindow {
  zone: ZoneOverlay;
}

export function projectZoneWindows(
  zones: ZoneOverlay[],
  chartEndAt: string,
): ZoneRenderProjection[] {
  return zones.flatMap((zone) => {
    const window = zoneAvailabilityWindow(zone, chartEndAt);
    return window === null ? [] : [{ zone, ...window }];
  });
}

export function signalAvailabilityStart(signal: SignalViewModel): string {
  return signal.validatedAt;
}
