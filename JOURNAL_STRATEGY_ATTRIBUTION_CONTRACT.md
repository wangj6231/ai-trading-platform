# Journal strategy attribution V1

`strategy_attribution=null` is the implemented, valid contract.

Existing OrderIntent/Trade.plan_reference is an opaque immutable opening-plan reference.
It has no approved FK/resolver to a persisted evaluation identity, and later scale-ins may use different strings.
It is therefore NOT evidence of strategy name/version/config hash/build hash/signal cutoff/timeframe.
No JournalStrategyAttribution rows, fake PlannedTrade, inferred 15m identity or massive analysis copy are created.

Clients and annotations cannot set trusted attribution or financial results. The strict annotation input rejects those fields.
A future approved resolver must prove immutable account-scoped linkage and define mixed-order attribution before it is enabled.
That work is outside this phase. Strategy recommendation remains independent from confirmed execution truth.
No strategy predicates/config/MTF/Entry/TP/SL, identity semantics or OpenAI workflow were changed.
R remains null; an opaque plan string does not establish monetary initial risk.
