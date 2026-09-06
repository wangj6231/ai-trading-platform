from sqlalchemy import inspect

from app.database.db import Base, Database
from app.models import SignalRecord  # noqa: F401


def test_database_connection_and_signal_metadata() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    try:
        database.ping()
        Base.metadata.create_all(database.engine)
        assert "signals" in inspect(database.engine).get_table_names()
        columns = {
            column["name"] for column in inspect(database.engine).get_columns("signals")
        }
        assert {
            "id",
            "symbol",
            "timeframe",
            "direction",
            "entry_min",
            "entry_max",
            "take_profit",
            "stop_loss",
            "risk_reward",
            "algorithm_score",
            "ai_confidence",
            "algorithm_decision",
            "ai_decision",
            "final_decision",
            "ai_validation_status",
            "ai_validation_evidence_schema_version",
            "ai_validation_evidence",
            "ai_validation_evidence_hash",
            "status",
            "created_at",
            "activated_at",
            "closed_at",
            "result",
            "pnl_r",
            "analysis_snapshot",
            "snapshot_schema_version",
            "analysis_snapshot_hash",
            "lifecycle_events",
            "strategy_version",
            "config_hash",
            "algorithm_build_hash",
        }.issubset(columns)
    finally:
        database.dispose()
