from collections.abc import Mapping

from app.execution.adapters.base import ExecutionAdapter


class ExecutionRegistry:
    """Server-owned adapter bindings. No automatic provider fallback."""

    def __init__(self, adapters: Mapping[str, ExecutionAdapter]) -> None:
        self._adapters = dict(adapters)
        if any(key != adapter.provider for key, adapter in self._adapters.items()):
            raise ValueError('provider registry identity mismatch')

    def resolve(self, provider: str) -> ExecutionAdapter:
        try:
            return self._adapters[provider]
        except KeyError:
            raise ValueError('execution provider UNSUPPORTED / NOT_READY') from None

    @property
    def providers(self) -> tuple[str, ...]:
        """Read-only server bindings for infrastructure capability selection."""
        return tuple(sorted(self._adapters))
