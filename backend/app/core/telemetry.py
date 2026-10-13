"""Bounded operational evidence, never financial authority or payload logging."""
import json
import logging
import math
from collections import Counter, deque
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Literal

Event = Literal['http', 'db_query', 'db_transaction', 'provider', 'worker', 'admission', 'error']
EVENTS = frozenset({'http', 'db_query', 'db_transaction', 'provider', 'worker', 'admission', 'error'})
OUTCOMES = frozenset({'ok', 'error', 'timeout', 'rate_limit', 'denied', 'busy', 'unknown'})
FIELDS = frozenset({'request_id', 'correlation_id', 'route', 'method', 'status_class',
    'duration_seconds', 'authenticated', 'operation', 'query_count', 'query_seconds',
    'symbol', 'http_status', 'retry_after_seconds', 'lag_seconds', 'admission_lag_seconds',
    'backlog_candles', 'targets', 'admissions', 'replay_suppressed', 'checkpoints',
    'lock_seconds', 'slow', 'outcome'})


@dataclass
class QueryMeasurement:
    count: int = 0
    seconds: float = 0


query_measurement: ContextVar[QueryMeasurement | None] = ContextVar('query_measurement', default=None)


class Telemetry:
    """Finite ring + fixed-dimension totals. No arbitrary labels or exporter callbacks."""
    def __init__(self, max_events: int = 1024, *, log_sample_every: int = 0) -> None:
        if not 1 <= max_events <= 4096 or not 0 <= log_sample_every <= 1000000:
            raise ValueError('invalid telemetry limits')
        self._events: deque[dict] = deque(maxlen=max_events)
        self._counts: Counter[tuple[str, str]] = Counter()
        self._lock = Lock()
        self._sample = log_sample_every
        self._seen = 0

    def emit(self, event: Event, **fields) -> None:
        # Strict typed/allowlisted dimensions. Reject free-form payload/context.
        if event not in EVENTS or fields.keys() - FIELDS:
            raise ValueError('unsupported telemetry field')
        result: dict = {'event': event}
        for key, value in fields.items():
            if value is None:
                result[key] = 'UNKNOWN'
            elif key in {'request_id', 'correlation_id'}:
                # Only generated IDs enter telemetry, never arbitrary header contents.
                if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('telemetry identity must be server generated')
                result[key] = value
            elif key == 'route':
                # Routes must come from trusted router templates, supplied by middleware.
                if not isinstance(value, str) or len(value) > 256:
                    raise ValueError('invalid route template')
                result[key] = value
            elif key == 'symbol':
                result[key] = value if value in {'BTCUSDT', 'ETHUSDT', 'XAUUSD'} else 'UNKNOWN'
            elif key == 'method':
                result[key] = value if value in {'GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'} else 'UNKNOWN'
            elif key == 'operation':
                allowed = {'CHEAP_READ', 'HISTORY_READ', 'ANALYTICS_READ', 'FINANCIAL_COMMAND',
                           'PROVIDER_TRIGGERING', 'ADMIN_SECURITY', 'OBSERVATION'}
                result[key] = value if value in allowed else 'UNKNOWN'
            elif key == 'outcome':
                result[key] = value if value in OUTCOMES else 'unknown'
            elif isinstance(value, (int, float, bool)) and math.isfinite(value) and abs(value) <= 1e15:
                result[key] = value
            else:
                raise ValueError('invalid telemetry value')
        with self._lock:
            self._events.append(result)
            self._counts[(event, result.get('outcome', 'unknown'))] += 1
            self._seen += 1
            sampled = self._sample > 0 and self._seen % self._sample == 0
        if sampled:
            try:
                logging.getLogger('app.operational').info(json.dumps(result, sort_keys=True, separators=(',', ':')))
            except Exception:
                # Diagnostics cannot roll back or redispatch financial work.
                pass

    def snapshot(self) -> dict:
        with self._lock:
            return {'events': list(self._events), 'totals': [
                {'event': event, 'outcome': outcome, 'count': count}
                for (event, outcome), count in sorted(self._counts.items())]}


DEFAULT_TELEMETRY = Telemetry()
