class MarketDataError(Exception):
    """Base class for provider-neutral market-data failures."""


class UnsupportedSymbolError(MarketDataError):
    pass


class ProviderRequestError(MarketDataError):
    pass


class ProviderTimeoutError(MarketDataError):
    pass


class ProviderRateLimitError(MarketDataError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        super().__init__("The provider rate-limited the market-data request")
        self.retry_after_seconds = retry_after_seconds


class InvalidProviderPayloadError(MarketDataError):
    pass


class DuplicateTimestampError(MarketDataError):
    pass


class OutOfOrderTimestampError(MarketDataError):
    pass


class MissingCandleError(MarketDataError):
    pass


class TimeframeAlignmentError(MarketDataError):
    pass


class EmptyCandleSetError(MarketDataError):
    pass


class UnclosedCandleError(MarketDataError):
    pass


class SessionCalendarCoverageError(MarketDataError):
    pass


class SessionCalendarMismatchError(MarketDataError):
    pass
