from pathlib import Path

from pydantic import ValidationError
import pytest
import yaml

from app.core.config import REPOSITORY_ROOT, Settings
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import canonical_strategy_config, strategy_config_hash


STRONG_PASSWORD = "UnitTestOnly_Strong-Db!2026"
SECOND_STRONG_PASSWORD = "UnitTestOnly_Other-Db!2026"


def database_url(
    *,
    username: str = "production_app_role",
    password: str | None = STRONG_PASSWORD,
) -> str:
    authority = username if password is None else f"{username}:{password}"
    return f"postgresql+psycopg://{authority}@db.internal:5432/trading"


@pytest.mark.parametrize(
    "placeholder",
    (
        "postgres",
        "password",
        "changeme",
        "change-me",
        "secret",
        "default",
        "change-me-local-only",
    ),
)
def test_production_rejects_placeholder_database_passwords(placeholder: str) -> None:
    with pytest.raises(ValidationError, match="known placeholder"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url=database_url(password=placeholder),
        )


@pytest.mark.parametrize("password", (None, "", "%20%20%20"))
def test_production_rejects_missing_empty_or_whitespace_database_password(
    password: str | None,
) -> None:
    with pytest.raises(ValidationError, match="database password is required"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url=database_url(password=password),
        )


def test_production_rejects_development_database_username() -> None:
    with pytest.raises(ValidationError, match="username uses a development placeholder"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url=database_url(username="ai_trading"),
        )


def test_production_accepts_strong_externally_supplied_credential_without_openai() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=database_url(),
        openai_validation_enabled=False,
        openai_api_key=None,
    )

    assert settings.app_env == "production"
    assert settings.openai_api_key is None


def test_development_allows_documented_local_credential() -> None:
    settings = Settings(_env_file=None, app_env="development")

    assert "change-me-local-only" in settings.database_url.get_secret_value()


def test_test_environment_allows_ephemeral_test_credential() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=(
            "postgresql+psycopg://ai_trading_test:local-ephemeral-test-only"
            "@127.0.0.1:55432/ai_trading_test"
        ),
    )

    assert settings.app_env == "test"


def test_database_url_environment_variable_cannot_bypass_production_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        database_url(password="change-me-local-only"),
    )

    with pytest.raises(ValidationError, match="known placeholder"):
        Settings(_env_file=None)


def test_production_rejects_malformed_or_non_postgresql_database_url() -> None:
    with pytest.raises(ValidationError, match="database URL is malformed"):
        Settings(_env_file=None, app_env="production", database_url="not a URL")
    with pytest.raises(ValidationError, match="must use PostgreSQL"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="sqlite+pysqlite:///production.sqlite3",
        )


def test_validation_exception_does_not_expose_database_password() -> None:
    password = "NeverLogThis_DbPassword!2026"

    with pytest.raises(ValidationError) as captured:
        Settings(
            _env_file=None,
            app_env="production",
            database_url=database_url(username="postgres", password=password),
        )

    assert password not in str(captured.value)
    assert "postgresql+psycopg://" not in str(captured.value)


def test_settings_repr_and_json_do_not_expose_database_password() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=database_url(),
    )

    assert STRONG_PASSWORD not in repr(settings)
    assert STRONG_PASSWORD not in settings.model_dump_json()
    assert "**********" in repr(settings)


def test_default_compose_does_not_publish_postgresql() -> None:
    compose = _yaml(REPOSITORY_ROOT / "docker-compose.yml")

    assert "ports" not in compose["services"]["postgres"]
    backend_url = compose["services"]["backend"]["environment"]["DATABASE_URL"]
    assert "@postgres:5432/" in backend_url


def test_development_compose_exposes_postgresql_on_loopback_only() -> None:
    compose = _yaml(REPOSITORY_ROOT / "docker-compose.dev.yml")
    ports = compose["services"]["postgres"]["ports"]

    assert ports == ["127.0.0.1:${POSTGRES_DEV_PORT:-5432}:5432"]


def test_postgresql_test_compose_remains_explicit_ephemeral_and_loopback_only() -> None:
    compose = _yaml(REPOSITORY_ROOT / "docker-compose.postgres-test.yml")
    service = compose["services"]["postgres-test"]

    assert service["ports"] == ["127.0.0.1:55432:5432"]
    assert "/var/lib/postgresql/data" in service["tmpfs"]


def test_deployment_secret_is_absent_from_strategy_config_and_identity() -> None:
    strategy = load_strategy_config()
    first_settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=database_url(password=STRONG_PASSWORD),
    )
    second_settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=database_url(password=SECOND_STRONG_PASSWORD),
    )
    serialized = canonical_strategy_config(strategy)

    assert first_settings.database_url != second_settings.database_url
    assert STRONG_PASSWORD.encode() not in serialized
    assert SECOND_STRONG_PASSWORD.encode() not in serialized
    assert b"database_url" not in serialized
    assert strategy_config_hash(strategy) == strategy_config_hash(load_strategy_config())


def test_dotenv_files_remain_ignored_except_for_the_documented_example() -> None:
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".env\n" in gitignore.replace("\r\n", "\n")
    assert ".env.*" in gitignore
    assert "!.env.example" in gitignore


def _yaml(path: Path) -> dict:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content
