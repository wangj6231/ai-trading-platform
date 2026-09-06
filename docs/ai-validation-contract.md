# AI validation contract

## Authority boundary

The deterministic strategy remains the sole authority for direction, Entry
Zone, one Take Profit and one Stop Loss. OpenAI is an optional secondary
validator. It can confirm, reject or reduce confidence, but it cannot upgrade a
deterministic `NO_TRADE`, reverse direction, manufacture evidence or change any
deterministic level.

The production signal endpoint is currently deterministic-only. Every response
therefore states:

```text
decision_mode = DETERMINISTIC_ONLY
ai_validation_status = NOT_REQUESTED
ai_decision = null
confidence = null
```

Its `final_decision` is the deterministic decision, not an AI-confirmed
decision. A separate AI-enabled public route has not been introduced.

## Validation-state taxonomy

The typed secondary-validation service distinguishes these states:

| State | Meaning |
|---|---|
| `NOT_REQUESTED` | The deterministic-only path never requested AI validation. |
| `SKIPPED_ALGORITHM_NO_TRADE` | The deterministic engine returned `NO_TRADE`; the AI call was skipped. |
| `DISABLED` | Optional validation is disabled. |
| `UNAVAILABLE` | The configured client or model is unavailable. |
| `CONFIRMED` | A valid structured response exactly echoed the deterministic candidate and met the configured confidence policy. |
| `REJECTED` | The AI explicitly returned `NO_TRADE`. |
| `REDUCED_CONFIDENCE` | The response matched the plan but did not meet the configured confidence policy. |
| `CONSTRAINT_REJECTED` | The AI attempted to change direction or Entry/TP/SL/RR. |
| `TIMEOUT` | The request timed out. |
| `INVALID_RESPONSE` | The response failed strict structured validation. |
| `API_ERROR` | Another provider/transport failure occurred. |

Skipped, unavailable, timeout, malformed and technical-error states are not AI
approval or AI rejection. If validation was attempted but did not produce a
valid confirmation, the secondary-validation result fails closed to
`NO_TRADE`. The deterministic candidate remains available as historical input
evidence, but it is not promoted as AI-confirmed.

## Evidence V1

`OpenAIValidationEvidenceV1` is strict, frozen and bounded. It records only the
typed evidence appropriate to its state:

- schema version and explicit status;
- server-configured provider/model identity when a request occurred;
- UTC request and completion timestamps;
- SHA-256 of the canonical deterministic input sent for validation;
- the parsed `OpenAIValidationOutput`, when a structurally valid response was
  received.

The structured response forbids unknown fields, requires the documented enum
and level fields, bounds confidence to 0–100, and bounds its reason list and
individual reason strings. Raw SDK responses, API keys, Authorization headers
and internal stack traces are not persisted.

The input hash covers the exact canonical structured validation context. The
evidence hash covers the canonical evidence document. These hashes are
server-generated in the validation/persistence flow and are not accepted by a
public client API.

## Persistence and immutability

Every trusted new signal write carries explicit AI-validation evidence,
including `NOT_REQUESTED` for deterministic-only results. The repository
re-parses the snapshot, AI evidence and complete create schema before hashing or
inserting, so `model_construct()` and detached `ai_decision` or
`ai_confidence` values cannot bypass validation.

For `CONFIRMED`, the structured direction, Entry Zone, TP, SL and RR must equal
the immutable deterministic Snapshot V2 plan. The repository derives the
stored AI decision and confidence from that structured response. For
`NOT_REQUESTED`, both remain null. Non-confirming attempted-validation states
can only produce persisted `NO_TRADE`.

PostgreSQL stores the evidence as JSONB with its schema version, status and
SHA-256 alongside it. Named constraints bind decision mode to final decision;
a trigger and ORM guard make the complete provenance immutable after insert.
This evidence is separate from future lifecycle and execution evidence.

Rows created before Evidence V1 may have all provenance fields null. They are
legacy/unknown and must never be relabeled as AI-confirmed. The migration does
not backfill model identity, timestamps, hashes or verdicts.

## Snapshot and identity boundaries

Snapshot V2 remains the deterministic point-in-time decision snapshot. Later
AI response/provenance is not injected into it. AI response content does not
change `StrategyIdentity`, `config_hash`, `algorithm_build_hash`, dataset hash,
run-spec hash or `BacktestRunIdentity`. Deterministic backtests continue without
external LLM calls.

## Frontend semantics

The signal client strictly accepts only the current deterministic endpoint
contract. Missing or unknown decision modes, non-`NOT_REQUESTED` AI states,
non-null AI decisions/confidence, contradictory decisions and malformed trade
geometry fail safely before a ViewModel is created.

The panel is labeled `DETERMINISTIC CANDIDATE`, shows `AI NOT REQUESTED`, and
does not display AI confidence. It never infers confirmation from a reason,
score or confidence value. Technical API errors remain error states rather than
AI verdicts or strategy `NO_TRADE` opinions.

## Limitations

This contract makes provenance explicit and auditable; it does not claim that
AI validation improves trading performance. It does not execute broker orders
and does not make the platform production-ready or profitable.
