# Security policy

## Scope

This repository is a research and portfolio project. It performs technical
analysis and backtesting; it does not place orders, manage funds, or require
exchange trading keys.

## Secret handling

- Never commit `.env`, API keys, database credentials, research cutoff tokens,
  private keys, database dumps, or local runtime data.
- `.env.example` contains development-only placeholders. Production starts in
  fail-closed mode when the PostgreSQL credential is missing, weak, or a known
  placeholder.
- Supply production secrets through the deployment environment or a secret
  manager. Rotate a credential immediately if it is ever committed, even when
  the commit is later removed.
- PostgreSQL is internal to the default Compose network. Host exposure is an
  explicit development-only overlay bound to `127.0.0.1`.

## Database safety boundary

PostgreSQL is the authoritative persistence boundary. Versioned migrations add
named row-validity constraints and triggers that reject changes to historical,
lifecycle, execution, and AI-validation evidence. Application checks are an
additional layer and are not treated as a substitute for database enforcement.

See [deployment security](docs/deployment-security.md) and
[signal persistence integrity](docs/signal-persistence-integrity.md) for the
implemented controls and test boundaries.

## Reporting a vulnerability

Do not open a public issue containing a credential, exploit payload, or private
data. Contact the repository owner privately with the affected component,
reproduction steps, impact, and a minimal redacted proof. No production service
or financial account is operated from this repository.
