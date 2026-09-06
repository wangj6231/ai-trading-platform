from enum import Enum
from typing import TypeVar


_K = TypeVar("_K")
_V = TypeVar("_V")


class FrozenDict(dict[_K, _V]):
    """Serializable mapping that rejects mutation after validated construction."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("validated strategy mappings are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def freeze_mapping(value: dict[_K, _V]) -> FrozenDict[_K, _V]:
    return FrozenDict(value)


class MarketSymbol(str, Enum):
    XAUUSD = "XAUUSD"
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"


class Timeframe(str, Enum):
    ONE_MINUTE = "1m"
    THREE_MINUTES = "3m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
