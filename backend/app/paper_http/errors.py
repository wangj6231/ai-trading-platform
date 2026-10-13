"""Explicit bounded domain translation; provider strings never escape."""
from enum import Enum
from app.core.errors import AppError


class ErrorCode(str, Enum):
    VALIDATION_ERROR = 'VALIDATION_ERROR'
    NOT_FOUND = 'NOT_FOUND'
    CONFLICT = 'CONFLICT'
    ORDER_REJECTED = 'ORDER_REJECTED'
    ORDER_ALREADY_TERMINAL = 'ORDER_ALREADY_TERMINAL'
    INSUFFICIENT_BALANCE = 'INSUFFICIENT_BALANCE'
    POSITION_CONFLICT = 'POSITION_CONFLICT'
    DUPLICATE_REQUEST = 'DUPLICATE_REQUEST'
    DUPLICATE_FILL = 'DUPLICATE_FILL'
    PROVIDER_UNAVAILABLE = 'PROVIDER_UNAVAILABLE'
    EXECUTION_UNKNOWN = 'EXECUTION_UNKNOWN'
    EXECUTION_INTERNAL_ERROR = 'EXECUTION_INTERNAL_ERROR'
    ATTACHMENT_FAILED = 'ATTACHMENT_FAILED'
    AUTH_REQUIRED = 'AUTH_REQUIRED'
    FORBIDDEN = 'FORBIDDEN'
    ACCOUNT_CLOSED = 'ACCOUNT_CLOSED'
    CLOSURE_REJECTED = 'CLOSURE_REJECTED'


MESSAGES = {
    ErrorCode.VALIDATION_ERROR: 'The request failed validation.',
    ErrorCode.NOT_FOUND: 'The scoped resource was not found.',
    ErrorCode.CONFLICT: 'The request conflicts with current canonical state.',
    ErrorCode.ORDER_REJECTED: 'The order was rejected.',
    ErrorCode.ORDER_ALREADY_TERMINAL: 'The order is already terminal.',
    ErrorCode.INSUFFICIENT_BALANCE: 'Insufficient available collateral.',
    ErrorCode.POSITION_CONFLICT: 'The order conflicts with the existing position.',
    ErrorCode.DUPLICATE_REQUEST: 'A conflicting request identity was supplied.',
    ErrorCode.DUPLICATE_FILL: 'A conflicting fill identity was supplied.',
    ErrorCode.PROVIDER_UNAVAILABLE: 'The configured execution provider is unavailable.',
    ErrorCode.EXECUTION_UNKNOWN: 'Execution outcome is unknown; no rejection or fill is inferred.',
    ErrorCode.EXECUTION_INTERNAL_ERROR: 'The execution request could not be processed safely.',
    ErrorCode.ATTACHMENT_FAILED: 'The attachment is unavailable.',
    ErrorCode.AUTH_REQUIRED: 'A trusted server principal is required.',
    ErrorCode.FORBIDDEN: 'The principal is not authorized for this account.',
    ErrorCode.ACCOUNT_CLOSED: 'The account is closed; no new financial command is admitted.',
    ErrorCode.CLOSURE_REJECTED: 'Closure requires no non-terminal orders and exactly zero position quantities.',
}


def error(code: ErrorCode, status: int) -> AppError:
    return AppError(status_code=status, code=code.value, message=MESSAGES[code])


def translate(exc: ValueError) -> AppError:
    from app.journal.readmodel import JournalReadNotReady
    if isinstance(exc, JournalReadNotReady):
        # Existing error vocabulary; transient derived-state unavailability,
        # not a fabricated empty response or a financial decision.
        return error(ErrorCode.EXECUTION_INTERNAL_ERROR, 503)
    # Match exact known internal reasons, not arbitrary substring/error parsing.
    reason = str(exc)
    if reason in {'ACCOUNT_CLOSED', 'CLOSURE_REJECTED'}:
        return error(ErrorCode(reason), 409)
    if reason == 'lifecycle account forbidden':
        return error(ErrorCode.FORBIDDEN, 403)
    if reason in {'scoped order not found', 'scoped journal trade not found',
                  'scoped journal account not found', 'journal account not found',
                  'analytics account not found', 'execution account not found',
                  'scoped attachment not found', 'account not found'}:
        return error(ErrorCode.NOT_FOUND, 404)
    if reason in {'CONFLICT: command changed', 'annotation version conflict'}:
        return error(ErrorCode.CONFLICT, 409)
    if reason in {'unsupported instrument precision/increment', 'quantity below instrument minimum',
                  'only LIMIT requires limit_price', 'instrument UNSUPPORTED / NOT_READY'}:
        return error(ErrorCode.VALIDATION_ERROR, 422)
    if reason == 'execution provider UNSUPPORTED / NOT_READY':
        return error(ErrorCode.PROVIDER_UNAVAILABLE, 503)
    return error(ErrorCode.EXECUTION_INTERNAL_ERROR, 500)


def order_error(status: str, reason: str | None) -> ErrorCode | None:
    if status == 'UNKNOWN':
        return ErrorCode.EXECUTION_UNKNOWN
    if status != 'REJECTED':
        return None
    if reason == 'insufficient available balance':
        return ErrorCode.INSUFFICIENT_BALANCE
    if reason in {'over-close / implicit reversal', 'over-close / implicit reversal rejected'}:
        return ErrorCode.POSITION_CONFLICT
    return ErrorCode.ORDER_REJECTED
