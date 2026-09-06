const ITEMS = [
  ["Support", "support"], ["Resistance", "resistance"], ["Swing H/L", "swing"],
  ["BOS", "bos"], ["MSS", "mss"], ["FVG", "fvg"], ["Order Block", "ob"],
  ["Entry Zone", "entry"], ["TP", "tp"], ["SL", "sl"],
] as const;

export function OverlayLegend({ analysisAvailable, signalAvailable }: { analysisAvailable: boolean; signalAvailable: boolean }) {
  return (
    <div className="overlay-legend" aria-label="Chart overlay legend">
      {ITEMS.map(([label, kind]) => {
        const needsSignal = ["entry", "tp", "sl"].includes(kind);
        const available = needsSignal ? signalAvailable : analysisAvailable;
        return <span className={!available ? "unavailable" : ""} key={kind}><i className={kind} />{label}</span>;
      })}
    </div>
  );
}
