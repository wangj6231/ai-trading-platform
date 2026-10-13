"""Authenticated canonical Paper HTTP. Defaults remain fail-closed."""
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.admission import AdmissionContext, check_admission, operation_cost
from app.execution.models import Identifier, canonical_json
from app.journal.analytics_models import AnalyticsQuery
from app.paper_http.errors import ErrorCode, error, translate
from app.paper_http.models import (
    AccountDTO, AnalyticsDTO, AttachmentDTO, FillDTO, HttpModel, ListQuery,
    MetadataDTO, MetadataPatch, OrderDTO, Page, PositionDTO, SubmitOrder, TradeDTO,
    LifecycleCommand, AccountLifecycleDTO, RetentionEvaluationDTO,
)
from app.paper_http.service import AccountScope, PaperHttpService, TrustedPrincipal

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


_bearer = HTTPBearer(auto_error=False)


def principal_dependency(request: Request,
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> TrustedPrincipal:
    # No body/localStorage identity, fake user, or permissive fallback.
    auth = getattr(request.app.state, 'paper_auth_service', None)
    headers = request.headers.getlist('authorization')
    if auth is None or credential is None or len(headers) != 1:
        raise error(ErrorCode.AUTH_REQUIRED, 401)
    principal = auth.authenticate(headers[0])
    request.state.authenticated = True
    return principal


def service_dependency(request: Request) -> PaperHttpService:
    service = getattr(request.app.state, 'paper_http_service', None)
    if service is None:
        raise error(ErrorCode.PROVIDER_UNAVAILABLE, 503)
    return service


Principal = Annotated[TrustedPrincipal, Depends(principal_dependency)]
Service = Annotated[PaperHttpService, Depends(service_dependency)]
Queries = Annotated[ListQuery, Query()]


def private_response(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'


def paper_admission(request: Request, account_id: str, principal: Principal, service: Service) -> None:
    request.state.authenticated = True
    service.scoped(principal, account_id)  # Current server ownership before costly work.
    route = request.scope['route'].path
    context = AdmissionContext(route, operation_cost(route, request.method), principal.subject, account_id)
    check_admission(request.app.state.admission_backend, context)


router = APIRouter(prefix='/paper/accounts/{account_id}', tags=['paper-contract'],
                   dependencies=[Depends(private_response), Depends(paper_admission)])


def invoke(service: PaperHttpService, principal: TrustedPrincipal, account_id: str,
           action: Callable[[AccountScope], HttpModel]) -> HttpModel:
    try:
        result = action(service.scoped(principal, account_id))
        if len(canonical_json(result).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise error(ErrorCode.EXECUTION_INTERNAL_ERROR, 500)
        return result
    except AppError:
        raise
    except ValueError as exc:
        raise translate(exc) from None
    except Exception:
        raise error(ErrorCode.EXECUTION_INTERNAL_ERROR, 500) from None


@router.get('', response_model=AccountDTO)
def account(account_id: Identifier, principal: Principal, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return invoke(service, principal, account_id, lambda scope: scope.account())


@router.post('/lifecycle/close', response_model=AccountLifecycleDTO)
def close_account(account_id: Identifier, principal: Principal, service: Service,
                  body: LifecycleCommand | None = None):
    return invoke(service, principal, account_id, lambda scope:
        AccountLifecycleDTO.model_validate(scope.close_account().model_dump(mode='python')))


@router.post('/lifecycle/deletion-request', response_model=AccountLifecycleDTO)
def request_deletion(account_id: Identifier, principal: Principal, service: Service,
                     body: LifecycleCommand | None = None):
    return invoke(service, principal, account_id, lambda scope:
        AccountLifecycleDTO.model_validate(scope.request_deletion().model_dump(mode='python')))


@router.get('/lifecycle', response_model=AccountLifecycleDTO)
def lifecycle(account_id: Identifier, principal: Principal, service: Service):
    return invoke(service, principal, account_id, lambda scope:
        AccountLifecycleDTO.model_validate(scope.lifecycle().model_dump(mode='python')))


@router.get('/lifecycle/retention-candidate', response_model=RetentionEvaluationDTO)
def retention_candidate(account_id: Identifier, principal: Principal, service: Service):
    return invoke(service, principal, account_id, lambda scope:
        RetentionEvaluationDTO.model_validate(scope.retention_candidate().model_dump(mode='python')))


@router.post('/orders', response_model=OrderDTO)
def submit(account_id: Identifier, principal: Principal, service: Service, body: SubmitOrder):
    return invoke(service, principal, account_id, lambda scope: scope.submit(body))


@router.get('/orders', response_model=Page[OrderDTO])
def orders(account_id: Identifier, principal: Principal, service: Service, query: Queries):
    return invoke(service, principal, account_id, lambda scope: scope.orders(query))


@router.get('/orders/{order_id}', response_model=OrderDTO)
def order(account_id: Identifier, order_id: Identifier, principal: Principal, service: Service):
    return invoke(service, principal, account_id, lambda scope: scope.order(order_id))


@router.post('/orders/{order_id}/cancel', response_model=OrderDTO)
def cancel(account_id: Identifier, order_id: Identifier, principal: Principal, service: Service):
    return invoke(service, principal, account_id, lambda scope: scope.cancel(order_id))


@router.get('/positions', response_model=Page[PositionDTO])
def positions(account_id: Identifier, principal: Principal, service: Service):
    def read(scope):
        return Page[PositionDTO](items=scope.positions(), next_cursor=None, has_more=False, as_of=scope._now())
    return invoke(service, principal, account_id, read)


@router.get('/trades', response_model=Page[TradeDTO])
def trades(account_id: Identifier, principal: Principal, service: Service, query: Queries):
    return invoke(service, principal, account_id, lambda scope: scope.trades(query))


@router.get('/journal', response_model=Page[TradeDTO])
def journal(account_id: Identifier, principal: Principal, service: Service, query: Queries):
    return invoke(service, principal, account_id, lambda scope: scope.trades(query, journal=True))


@router.get('/trades/{trade_id}', response_model=TradeDTO)
@router.get('/journal/{trade_id}', response_model=TradeDTO)
def trade(account_id: Identifier, trade_id: Identifier, principal: Principal, service: Service):
    return invoke(service, principal, account_id, lambda scope: scope.trade(trade_id))


@router.get('/trades/{trade_id}/fills', response_model=Page[FillDTO])
def fills(account_id: Identifier, trade_id: Identifier, principal: Principal, service: Service, query: Queries):
    return invoke(service, principal, account_id, lambda scope: scope.fills(trade_id, query))


@router.patch('/journal/{trade_id}/metadata', response_model=MetadataDTO)
def metadata(account_id: Identifier, trade_id: Identifier, principal: Principal, service: Service,
             body: MetadataPatch, response: Response):
    result = invoke(service, principal, account_id, lambda scope: scope.metadata(trade_id, body))
    assert isinstance(result, MetadataDTO)
    response.headers['ETag'] = f'"{result.annotations.version}"'
    return result


@router.get('/analytics', response_model=AnalyticsDTO)
def analytics(account_id: Identifier, principal: Principal, service: Service,
              query: Annotated[AnalyticsQuery, Query()]):
    return invoke(service, principal, account_id, lambda scope: scope.analytics(query))


@router.get('/trades/{trade_id}/attachments', response_model=Page[AttachmentDTO])
def attachments(account_id: Identifier, trade_id: Identifier, principal: Principal, service: Service, query: Queries):
    return invoke(service, principal, account_id, lambda scope: scope.attachments(trade_id, query))
