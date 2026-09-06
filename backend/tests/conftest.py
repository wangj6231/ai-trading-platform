import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        market_data_default_limit=100,
        market_data_max_limit=1000,
    )


@pytest.fixture
def client(test_settings: Settings):
    application = create_app(test_settings)
    with TestClient(application) as test_client:
        yield test_client

