const messages = {
  AUTH_REQUIRED: "Authentication required. Protected account data has been cleared.",
  FORBIDDEN: "Access to this account is forbidden. Protected data has been cleared.",
  NOT_FOUND: "This account-scoped resource was not found.",
  CONFLICT: "The command, metadata version or page membership conflicts. Reload before retrying.",
  VALIDATION_ERROR: "The request does not satisfy the backend contract.",
  ORDER_REJECTED: "The provider reported an order rejection.",
  ORDER_ALREADY_TERMINAL: "This order is already terminal.",
  INSUFFICIENT_BALANCE: "The backend reported insufficient available balance at fill admission.",
  POSITION_CONFLICT: "The backend reported a position conflict.",
  PROVIDER_UNAVAILABLE: "The execution provider is unavailable.",
  EXECUTION_UNKNOWN: "Execution outcome is unknown. Refresh this order; do not infer a rejection.",
  EXECUTION_INTERNAL_ERROR: "The execution service could not complete this request.",
  ATTACHMENT_FAILED: "The attachment operation failed.",
  BACKEND_TIMEOUT: "The backend request timed out. No execution outcome has been established.",
  BACKEND_UNAVAILABLE: "The backend is unavailable. No fixture fallback is enabled.",
  INVALID_RESPONSE: "The backend response did not satisfy the canonical contract.",
  BOOTSTRAP_REQUIRED: "Private HTTP runtime requires an explicitly provisioned account and server credential.",
  REQUEST_CANCELLED: "The resource scope changed; this response was discarded.",
} as const;
export type PaperErrorCode = keyof typeof messages;
export function safePaperCode(value: unknown, status: number): PaperErrorCode {
  if (status === 401) return "AUTH_REQUIRED";
  if (status === 403) return "FORBIDDEN";
  if (typeof value === "string" && Object.hasOwn(messages, value)) return value as PaperErrorCode;
  return status === 404 ? "NOT_FOUND" : status === 409 ? "CONFLICT" : status === 422 ? "VALIDATION_ERROR" : "EXECUTION_INTERNAL_ERROR";
}
export class PaperHttpError extends Error {
  constructor(readonly code: PaperErrorCode, readonly httpStatus = 0, readonly requestId: string | null = null) { super(messages[code]); }
}
export function paperFailure(error: unknown) { return error instanceof PaperHttpError ? error : new PaperHttpError("INVALID_RESPONSE"); }
