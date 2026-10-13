"""Current owner check for trusted server-principal module callers, no admin bypass."""
from sqlalchemy.orm import Session

from app.auth.records import AuthSubjectRecord, PaperAccountOwnershipRecord


def require_owned_account(session: Session, principal: object, account_id: str) -> None:
    from app.paper_http.service import TrustedPrincipal
    if not isinstance(principal, TrustedPrincipal):
        raise PermissionError('ATTACHMENT_FORBIDDEN')
    try:
        grant = TrustedPrincipal.model_validate(principal.model_dump(mode='python'))
    except ValueError:
        raise PermissionError('ATTACHMENT_FORBIDDEN') from None
    owner = session.get(PaperAccountOwnershipRecord, account_id)
    if (account_id not in grant.account_ids or session.get(AuthSubjectRecord, grant.subject) is None
            or owner is None or owner.subject_id != grant.subject):
        raise PermissionError('ATTACHMENT_FORBIDDEN')
