"""Additive append-only observation evidence and safely delivered checkpoints."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.types import UtcTimestamp
from app.execution.records import DOCUMENT


class ObservationRecord(Base):
    __tablename__ = 'market_observations'
    __table_args__ = (CheckConstraint('closed_at <= retrieved_at', name='observation_closed'),)
    source: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(128), primary_key=True)
    open_at: Mapped[datetime] = mapped_column(UtcTimestamp(), primary_key=True)
    closed_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candle: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    provenance: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)


class ObservationDeliveryRecord(Base):
    __tablename__ = 'market_observation_deliveries'
    __table_args__ = (CheckConstraint('first_at < cutoff_at AND cutoff_at <= processed_at', name='delivery_visible'),)
    source: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_accounts.account_id'), primary_key=True)
    cutoff_at: Mapped[datetime] = mapped_column(UtcTimestamp(), primary_key=True)
    first_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    batch_hash: Mapped[str] = mapped_column(String(64), nullable=False)


def _immutable(*_args) -> None:
    raise ValueError('immutable market observation evidence')


for _model in (ObservationRecord, ObservationDeliveryRecord):
    event.listen(_model, 'before_update', _immutable)
    event.listen(_model, 'before_delete', _immutable)

TABLES = [ObservationRecord.__table__, ObservationDeliveryRecord.__table__]
