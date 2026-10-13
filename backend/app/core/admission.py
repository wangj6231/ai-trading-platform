"""Server-side resource admission, separate from order rejection/strategy decisions."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from time import monotonic
from typing import Protocol

from app.core.errors import AppError


class CostClass(StrEnum):
    CHEAP_READ = 'CHEAP_READ'
    HISTORY_READ = 'HISTORY_READ'
    ANALYTICS_READ = 'ANALYTICS_READ'
    FINANCIAL_COMMAND = 'FINANCIAL_COMMAND'
    PROVIDER_TRIGGERING = 'PROVIDER_TRIGGERING'
    ADMIN_SECURITY = 'ADMIN_SECURITY'


@dataclass(frozen=True)
class AdmissionContext:
    route: str
    cost: CostClass
    subject: str | None = None
    account: str | None = None


class AdmissionBackend(Protocol):
    def check(self, context: AdmissionContext) -> None: ...


class ResourceAdmissionError(AppError):
    """A technical admission failure, never a provider/financial verdict."""


def admission_error(status: int = 503) -> ResourceAdmissionError:
    return ResourceAdmissionError(status_code=status,
        code='RESOURCE_RATE_LIMITED' if status == 429 else 'RESOURCE_UNAVAILABLE',
        message='The request could not be admitted within the server resource budget.')


def check_admission(backend: AdmissionBackend, context: AdmissionContext) -> None:
    try:
        # Runtime guard: None is the only successful verdict in this Interface.
        invoke: Callable[[AdmissionContext], object] = backend.check
        result = invoke(context)
        if result is not None:
            raise admission_error()
    except AppError as exc:
        # Never trust an injected/remote backend's message/details as public evidence.
        raise admission_error(429 if exc.status_code == 429 else 503) from None
    except Exception:
        raise admission_error() from None


class LocalCostBudget:
    """One app-wide finite fixed-window budget; NOT a distributed/public limiter."""
    def __init__(self, limits: Mapping[str, int], *, window_seconds: float = 60,
                 max_keys: int = 4096, clock: Callable[[], float] = monotonic):
        if set(limits) != {c.value for c in CostClass} or any(
                isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 1000000 for v in limits.values()):
            raise ValueError('all cost classes require finite positive quotas')
        if not 1 <= window_seconds <= 3600 or not 16 <= max_keys <= 100000:
            raise ValueError('invalid budget bounds')
        self.limits, self.window, self.max_keys, self.clock = dict(limits), window_seconds, max_keys, clock
        self._counts: dict[tuple, int] = {}
        self._window: int | None = None
        self._lock = Lock()

    def check(self, context: AdmissionContext) -> None:
        with self._lock:
            current = int(self.clock() // self.window)
            if self._window != current:
                self._counts.clear()
                self._window = current
            # Global shared class budget cannot be evaded by anonymous identity churn.
            keys: list[tuple[CostClass, str | None, str | None]] = [(context.cost, None, None)]
            if context.subject is not None:
                keys.append((context.cost, context.subject, context.account))
            if len(self._counts) + sum(k not in self._counts for k in keys) > self.max_keys:
                raise admission_error()
            if any(self._counts.get(k, 0) >= self.limits[context.cost] for k in keys):
                raise admission_error(429)
            for key in keys:
                self._counts[key] = self._counts.get(key, 0) + 1


def operation_cost(route: str, method: str) -> CostClass:
    if '/paper/' in route:
        if method != 'GET':
            return CostClass.FINANCIAL_COMMAND
        if route.endswith('/analytics'):
            return CostClass.ANALYTICS_READ
        if any(part in route for part in ('/journal', '/trades', '/fills', '/retention-candidate')):
            return CostClass.HISTORY_READ
        return CostClass.CHEAP_READ
    if any(part in route for part in ('/analysis', '/signals', '/evaluations', '/market')):
        return CostClass.PROVIDER_TRIGGERING
    return CostClass.CHEAP_READ
