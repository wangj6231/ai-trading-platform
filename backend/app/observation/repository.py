"""Operational evidence only; execution transactions remain gateway-owned."""
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import Connection, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.database.db import Database
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.gateway import ExecutionGateway
from app.execution.models import SubmissionStatus, content_hash
from app.execution.records import ExecutionAccountRecord, ExecutionOrderRecord
from app.execution.repository import document
from app.market_data.timeframes import timeframe_bucket_start
from app.observation.records import ObservationDeliveryRecord, ObservationRecord
from app.schemas.market import ValidatedMarketData
from app.schemas.types import Timeframe
from app.core.time import normalize_utc_datetime
from app.observation.active_work import FINGERPRINT_SQL, VERSION, VIEW, install_v1


class ActiveWorkNotReady(RuntimeError):
    """Incomplete/unhealthy/over-budget discovery: do not dispatch a subset."""


class ObservationRepository:
    def __init__(self, database: Database, *, max_work_items: int = 100000,
                 max_accounts: int = 10000, checkpoint_page_size: int = 100) -> None:
        if (not 1 <= max_work_items <= 1000000 or not 1 <= max_accounts <= 100000
                or not 1 <= checkpoint_page_size <= 1000):
            raise ValueError('invalid active work infrastructure limits')
        self.database = database
        self.max_work_items, self.max_accounts = max_work_items, max_accounts
        self.checkpoint_page_size = checkpoint_page_size

    def targets(self, gateway: ExecutionGateway, symbol: str, cutoff: datetime) -> dict[str, datetime]:
        if self.database.engine.dialect.name == 'postgresql':
            return self.projected_targets(gateway, symbol, cutoff)
        # SQLite is an isolated seam-test adapter, not enabled production worker.
        return self.canonical_targets(gateway, symbol, cutoff)

    def canonical_targets(self, gateway: ExecutionGateway, symbol: str, cutoff: datetime) -> dict[str, datetime]:
        """Read durable per-order cursor; never infer eligibility from watermark.

        Open positions also receive current valuation through gateway.observe.
        No ownership binding is created/changed by this internal infrastructure.
        """
        with self.database.read_session() as session:
            return self._canonical_targets(session, gateway, symbol, cutoff)

    def _canonical_targets(self, session: Session, gateway: ExecutionGateway,
                           symbol: str, cutoff: datetime) -> dict[str, datetime]:
        targets = {}
        accounts = session.scalars(select(ExecutionAccountRecord).order_by(ExecutionAccountRecord.account_id)).all()
        for row in accounts:
            if not isinstance(gateway.registry.resolve(row.execution_provider), PaperExecutionAdapter):
                continue
            account = gateway.repository.parse_account(session, row)
            starts = []
            orders = session.scalars(select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.account_id == row.account_id).order_by(ExecutionOrderRecord.command_sequence)).all()
            for order_row in orders:
                order = gateway.repository.parse_order(order_row)
                if (order.intent.symbol == symbol and order.submission_status is SubmissionStatus.ACKNOWLEDGED
                        and order.cancelled_at is None and order.filled_quantity < order.intent.quantity):
                    starts.append(order.last_observation_at + timedelta(minutes=1) if order.last_observation_at else
                                  timeframe_bucket_start(order.accepted_at, Timeframe.ONE_MINUTE) + timedelta(minutes=1))
            if any(p.symbol == symbol and p.quantity for p in account.positions):
                starts.append(cutoff - timedelta(minutes=1))
            eligible = [s for s in starts if s < cutoff]
            if eligible:
                targets[row.account_id] = min(eligible)
        return targets

    def projected_targets(self, gateway: ExecutionGateway, symbol: str, cutoff: datetime) -> dict[str, datetime]:
        """Only thin candidate identities/cursors; Gateway still validates facts."""
        if self.database.engine.dialect.name != 'postgresql':
            raise ActiveWorkNotReady('PostgreSQL active work required')
        try:
            with self.database.read_session() as session:
                return self._projected_targets(session, gateway, symbol, cutoff)
        except SQLAlchemyError:
            raise ActiveWorkNotReady('active work schema unavailable') from None

    def _projected_targets(self, session: Session, gateway: ExecutionGateway,
                           symbol: str, cutoff: datetime) -> dict[str, datetime]:
        cutoff = normalize_utc_datetime(cutoff)
        # SHARE protects schema fingerprint/query against concurrent rebuild DDL,
        # not canonical DML. Release the read transaction before provider IO.
        session.execute(text(f'LOCK TABLE {VIEW} IN ACCESS SHARE MODE'))
        healthy = session.scalar(text(f"""SELECT version=:version AND definition_hash=({FINGERPRINT_SQL})
            AND (SELECT bool_and(indisvalid) FROM pg_index WHERE indexrelid IN
              ('ix_observation_pending_symbol'::regclass))
            FROM observation_work_schema WHERE singleton=1"""), {'version': VERSION})
        if healthy is not True:
            raise ActiveWorkNotReady('active work schema not ready')
        unsupported = session.scalar(select(ExecutionAccountRecord.account_id).where(
            ExecutionAccountRecord.execution_provider.not_in(gateway.registry.providers)).limit(1))
        if unsupported is not None:
            # Preserve old fail-closed registry behavior, never silently omit an
            # account whose server adapter binding has disappeared.
            raise ActiveWorkNotReady('execution registry incomplete')
        providers = tuple(p for p in gateway.registry.providers
                          if isinstance(gateway.registry.resolve(p), PaperExecutionAdapter))
        rows = session.execute(text(f"""WITH bounded AS MATERIALIZED (
            SELECT account_id, COALESCE(next_open_at, :cutoff - interval '1 minute') AS first_at
            FROM {VIEW} WHERE symbol=:symbol AND execution_provider = ANY(:providers)
            AND COALESCE(next_open_at, :cutoff - interval '1 minute') < :cutoff
            LIMIT :work_limit), grouped AS (
            SELECT account_id, min(first_at) AS first_at, count(*) AS work_count
            FROM bounded GROUP BY account_id)
            SELECT account_id, first_at, sum(work_count) OVER () AS total_work
            FROM grouped ORDER BY account_id LIMIT :account_limit"""),
            {'cutoff': cutoff, 'symbol': symbol, 'providers': list(providers),
             'work_limit': self.max_work_items + 1, 'account_limit': self.max_accounts + 1}).all()
        if len(rows) > self.max_accounts or (rows and rows[0].total_work > self.max_work_items):
            raise ActiveWorkNotReady('active work budget exceeded')
        return {row.account_id: normalize_utc_datetime(row.first_at) for row in rows}

    def shadow_parity(self, gateway: ExecutionGateway, symbol: str, cutoff: datetime) -> dict[str, datetime]:
        """Diagnostic old/new comparison on ONE repeatable-read canonical state."""
        with self.database.engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
            with Session(connection) as session:
                canonical = self._canonical_targets(session, gateway, symbol, cutoff)
                projected = self._projected_targets(session, gateway, symbol, cutoff)
                if canonical != projected:
                    raise AssertionError('active work canonical candidate/cursor mismatch')
                return projected

    def rebuild(self) -> None:
        """Controlled maintenance; no financial row changes or public route."""
        if self.database.engine.dialect.name != 'postgresql':
            raise ActiveWorkNotReady('PostgreSQL active work required')
        with self.database.engine.begin() as connection:
            install_v1(connection)

    def checkpoint(self, account_id: str, symbol: str, source: str | None = None) -> datetime | None:
        with self.database.read_session() as session:
            query = select(func.max(ObservationDeliveryRecord.cutoff_at)).where(
                ObservationDeliveryRecord.account_id == account_id, ObservationDeliveryRecord.symbol == symbol)
            if source is not None:
                query = query.where(ObservationDeliveryRecord.source == source)
            return session.scalar(query)

    def checkpoints(self, account_ids: list[str], symbol: str, source: str) -> dict[str, datetime | None]:
        """Finite pages; absence is not a financial cursor or permission grant."""
        if len(account_ids) > self.max_accounts:
            raise ActiveWorkNotReady('checkpoint account budget exceeded')
        result: dict[str, datetime | None] = dict.fromkeys(account_ids)
        with self.database.read_session() as session:
            for start in range(0, len(account_ids), self.checkpoint_page_size):
                page = account_ids[start:start + self.checkpoint_page_size]
                rows = session.execute(select(ObservationDeliveryRecord.account_id,
                    func.max(ObservationDeliveryRecord.cutoff_at)).where(
                    ObservationDeliveryRecord.account_id.in_(page), ObservationDeliveryRecord.symbol == symbol,
                    ObservationDeliveryRecord.source == source).group_by(ObservationDeliveryRecord.account_id))
                for account, at in rows:
                    result[account] = at
        return result

    def capture(self, market: ValidatedMarketData) -> None:
        with self.database.transaction() as session:
            for candle in market.candles:
                identity = (market.source, market.symbol.value, candle.timestamp)
                row = session.get(ObservationRecord, identity)
                digest = content_hash({'source': market.source, 'symbol': market.symbol.value, 'timeframe': '1m', 'candle': candle})
                if row is not None:
                    if row.observation_hash != digest or row.candle != document(candle):
                        raise ValueError('CONFLICT: immutable canonical observation')
                else:
                    session.add(ObservationRecord(source=market.source, symbol=market.symbol.value,
                        open_at=candle.timestamp, closed_at=candle.timestamp + timedelta(minutes=1),
                        retrieved_at=market.retrieved_at, observation_hash=digest,
                        candle=document(candle), provenance=document(market.provenance)))

    def delivered(self, account_id: str, market: ValidatedMarketData, now: datetime) -> None:
        identity = (market.source, market.symbol.value, account_id, market.provenance.data_cutoff_at)
        digest = content_hash({'source': market.source, 'symbol': market.symbol.value, 'candles': market.candles})
        with self.database.transaction() as session:
            row = session.get(ObservationDeliveryRecord, identity)
            if row is not None:
                if row.batch_hash != digest:
                    raise ValueError('CONFLICT: observation delivery evidence')
                return
            session.add(ObservationDeliveryRecord(source=market.source, symbol=market.symbol.value,
                account_id=account_id, cutoff_at=market.provenance.data_cutoff_at,
                first_at=market.candles[0].timestamp, processed_at=now, batch_hash=digest))

    def acquire(self, source: str, symbol: str) -> Connection | None:
        """PostgreSQL session advisory lock: no financial row lock during IO.

        SQLite is only a seam-test adapter; lifespan-enabled worker requires PG.
        Process death releases the session lock, without lease expiry assumptions.
        """
        connection = self.database.engine.connect()
        try:
            if connection.dialect.name == 'postgresql':
                key = int.from_bytes(sha256(f'OBSERVATION_V1/{source}/{symbol}'.encode()).digest()[:8], signed=True)
                acquired = connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': key})
                connection.commit()
                if not acquired:
                    connection.close()
                    return None
            return connection
        except BaseException:
            # Never return a potentially session-locked connection to the pool.
            connection.invalidate()
            connection.close()
            raise

    def release(self, connection: Connection, source: str, symbol: str) -> None:
        try:
            if connection.dialect.name == 'postgresql':
                key = int.from_bytes(sha256(f'OBSERVATION_V1/{source}/{symbol}'.encode()).digest()[:8], signed=True)
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                connection.commit()
        except BaseException:
            connection.invalidate()
            raise
        finally:
            connection.close()
