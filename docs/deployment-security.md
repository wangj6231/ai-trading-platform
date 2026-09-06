# Deployment security

## Environment modes

`APP_ENV` is an explicit validated setting with four supported values:
`development`, `test`, `staging`, and `production`. The application does not
infer production from logging or debug settings and never silently changes the
selected environment.

- `development` permits the documented local database credential so a new
  checkout remains convenient to run.
- `test` permits isolated ephemeral test credentials and SQLite unit-test URLs.
- `staging` remains a separately declared environment; operators should provide
  deployment-managed credentials.
- `production` enables mandatory fail-closed PostgreSQL credential validation.

## Production database requirements

Production must receive `DATABASE_URL` from the deployment environment or a
secret manager. The URL must:

- use PostgreSQL;
- include a host and database name;
- include a non-empty username and password;
- avoid the repository's development/default usernames;
- avoid known placeholder passwords such as `postgres`, `password`, `changeme`,
  `change-me`, `secret`, `default`, and repository sample values;
- use a password of at least 16 characters.

Credentials embedded in `DATABASE_URL` are parsed and validated; embedding them
does not bypass the production checks. Unsafe production settings abort Settings
construction. The Docker entrypoint invokes Alembic through the same validated
Settings path, so an unsafe production deployment fails before migrations and
before Uvicorn serves requests. No warning-and-continue, SQLite fallback,
generated password, environment downgrade, or persistence disablement occurs.

Do not put deployment secrets in `.env.example`, `docker-compose.yml`, source
code, documentation, tests, or `config/strategy.yaml`. `.env` and `.env.*` remain
ignored, except for the committed `.env.example` template. Production secret
rotation must happen through the deployment platform rather than a repository
commit.

## PostgreSQL network exposure

The default Compose deployment does not publish PostgreSQL port 5432 to the
host. The backend reaches `postgres:5432` through the internal Compose network:

```text
backend container -> Compose internal network -> postgres:5432
```

Normal startup therefore needs no database host port:

```powershell
docker compose -f docker-compose.yml up --build
```

When direct local database access is explicitly required for development, add
the development overlay:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The overlay publishes `127.0.0.1:${POSTGRES_DEV_PORT:-5432}:5432`. It binds to
loopback only and must not be used as a production deployment file. Developers
who do not need host access should omit it.

`docker-compose.postgres-test.yml` is separate, explicit test infrastructure. It
uses tmpfs and publishes only `127.0.0.1:55432` for ephemeral PostgreSQL 16
integration tests. This exception does not change default deployment exposure.

## Secret redaction and application output

`DATABASE_URL`, OpenAI API keys, and authorized research tokens use Pydantic
secret-aware values. Their `repr` and JSON serialization are masked. Settings
validation hides input values, and production database validation messages name
only the invalid property; they do not include a password or full connection
URL. Health responses expose the environment name but no configuration secrets.

The OpenAI API key remains optional because deterministic analysis can run
without OpenAI. OpenAI validation remains disabled by default and retains its
existing fail-safe behavior.

## Strategy identity separation

Deployment Settings and canonical StrategyConfig remain different trust domains:

```text
deployment environment -> Settings -> database/network/OpenAI runtime
config/strategy.yaml    -> StrategyConfig -> StrategyIdentity
```

Database users, passwords and URLs never enter canonical strategy serialization.
Changing a database password therefore does not change `strategy_version`,
`config_hash`, or `algorithm_build_hash`.

## Required deployment checks

Before a production deployment:

1. Set `APP_ENV=production` explicitly.
2. Inject a dedicated non-default PostgreSQL role and strong password through the
   deployment secret mechanism.
3. Do not include `docker-compose.dev.yml`.
4. Confirm rendered Compose has no PostgreSQL host port.
5. Run Alembic and application startup; any credential validation failure must be
   corrected rather than bypassed.
6. Confirm no `.env`, credential-bearing URL, API key, or research token is
   committed or printed in deployment logs.

These controls reduce configuration risk; they do not by themselves make the
trading platform production-ready.
