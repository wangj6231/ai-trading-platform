# Security policy

## Scope

This repository is a research and portfolio project. It performs technical
analysis, backtesting, and account-scoped Paper execution. It does not place
LIVE exchange or broker orders, manage real funds, or require exchange trading
keys.

## Secret handling

- Never commit `.env`, API keys, database credentials, research cutoff tokens,
  private keys, database dumps, or local runtime data.
- `.env.example` contains development-only placeholders. Production starts in
  fail-closed mode when the PostgreSQL credential is missing, weak, or a known
  placeholder.
- Supply production secrets through the deployment environment or a secret
  manager. Rotate a credential immediately if it is ever committed, even when
  the commit is later removed.
- The Paper HTTP bearer credential is configured only on the backend-facing
  server boundary. It must not be exposed through browser bundles, client-side
  environment variables, logs, screenshots, or fixture fallbacks.
- PostgreSQL is internal to the default Compose network. Host exposure is an
  explicit development-only overlay bound to `127.0.0.1`.

## Database safety boundary

PostgreSQL is the authoritative persistence boundary. Versioned migrations add
named row-validity constraints and triggers that reject changes to historical,
lifecycle, execution, Journal, attachment, retention, and AI-validation
evidence. Application checks are an additional layer and are not treated as a
substitute for database enforcement. Account scope is revalidated at command,
read, and completion boundaries; a successful Paper test is not permission to
connect a LIVE provider.

See [deployment security](docs/deployment-security.md) and
[signal persistence integrity](docs/signal-persistence-integrity.md) for the
implemented controls and test boundaries.

## Reporting a vulnerability

Do not open a public issue containing a credential, exploit payload, or private
data. Contact the repository owner privately with the affected component,
reproduction steps, impact, and a minimal redacted proof. No production service
or financial account is operated from this repository.
