# Independent raw-to-effective dataset recheck

Performed during run 1 without evaluating the strategy again.

- Raw page row counts: 440 and 1,000; total 1,440.
- Both HTTP responses were status 200 from the existing Binance Spot public
  `/api/v3/klines` path; exact query URLs and actual retrieval timestamps are
  retained in per-response provenance JSON.
- The saved raw bytes were decoded again with the existing Binance parser,
  reconstructed through the strict Candle schema, and passed through existing
  supplied-order validation. No sorting, filtering, replacement or synthesis.
- Every reconstructed candle equaled its frozen effective-dataset counterpart.
- Recomputed CanonicalDatasetIdentity:
  `dd6d62331afd43c064f38ba9186f084bde60840c1764b439bd08887a442573e8`.
- Raw page 1 SHA-256:
  `db2fbbad945d96a04667e4a18abd577952df05fd279191a7272897aa7d31c8a6`.
- Raw page 2 SHA-256:
  `b93e6036672ff7d6b3c5544280f32f8c4d93174a62ae5c3a38ffc3f37c35ee06`.

The provider's injected historical request cutoff controls the existing public
`endTime` parameter only. MarketDataService retained the real retrieval clock,
so its provenance correctly shows that these are old candles with a large lag
relative to current time. No current/live-freshness claim is made. Backtesting
uses each historical evaluation cutoff, not retrieval time, and the unchanged
runner exposes only candles closed by that cutoff.

No global DATABASE_URL, OpenAI credential, broker account, private API, or
current production analysis endpoint was used for this research acquisition.
