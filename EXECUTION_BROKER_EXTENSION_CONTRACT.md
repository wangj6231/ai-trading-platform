# Provider extension — Canonical seam and supported profile

2026-10-08。Internal PAPER implementation and independent FakeExecutionAdapter conformance tested.

## Change budget

Same supported SYNTHETIC_DIRECTIONAL / ONE_WAY_NET_POSITION / USDT BASE_UNITS accounting semantics:
new adapter + credentials/settings binding + server registry entry + instrument/capability mapping + connector tests.
No strategy engine, account reducer, canonical financial fill, Journal PnL or analytics provider-name branch.

ExecutionAdapter: submit_order, cancel_order, get_order, get_positions, get_account, normalize_event.
Server adapter capability accepts_external_fills distinguishes connector ingestion from PAPER's
validated observation generation; fabricated PAPER payloads cannot become new fills.
Canonical typed OrderSubmission/Cancellation distinguish acknowledgment/rejection/unknown.
get_account/get_positions are connector observation/reconciliation interfaces, NOT authority to overwrite
server monetary projections; only admitted fills enter the reducer.

Generic ExecutionEvent retains exact quantity/price/complete fee list/UTC/order/source/account/scoped sequence.
Provider-specific translation stops here. Fake connector supports multiple canonical partial fills of one order;
PAPER observation's whole fill restriction does not contaminate generic accounting.

## Current supported capability / rejection

Only PAPER environment enabled (including test-only same-profile connector in seam tests).
USDT settlement/reporting, nonnegative complete USDT fees, BASE_UNITS profile.
Unknown providers have no fallback. Unsupported order/profile/precision/currency reject.
LIVE, margin, FX, hedge, multiplier/perpetual/funding/fee corrections/busts require later approved versioned
capability/accounting contracts, not a name-based conditional.
PAPER must never be relabeled LIVE.

## Conformance / limitations

Economically identical Paper/Fake fills yield identical monetary account/position/trade allocation,
entry notional, gross/net PnL, fees, percent and zero residual.
IDs/source/provenance differ honestly; source is part of economic dedup identity.
Only adapters and registry/observation dispatch know provider capabilities;
accounting/repository do not use provider name to choose prices/fees/PnL.
Paper fee formula lives only in PaperExecutionAdapter.
No LIVE credentials, SDK connector, automatic orders, public auth endpoints, Journal or analytics implementation added.

Historical storage captures supported accounting/numeric versions and frozen instrument profile.
Future connector MUST preserve trustworthy scoped economic ordering; otherwise explicit reconciliation,
not random ID sorting, silent fallback or fabricated fee zero.
