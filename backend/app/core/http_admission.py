"""ASGI pre-parse bounds; finite body buffering before business dispatch."""
import asyncio
import json
import re
from time import perf_counter
from uuid import uuid4

from starlette.routing import compile_path

from app.core.admission import AdmissionContext, CostClass, check_admission, operation_cost
from app.core.errors import AppError
from app.core.telemetry import QueryMeasurement, query_measurement

ID_GRAMMAR = re.compile(r'^[A-Za-z0-9_-]{1,64}$', re.ASCII)


class HttpAdmissionMiddleware:
    def __init__(self, app, *, owner, settings):
        self.app, self.owner, self.settings = app, owner, settings
        # Public effective OpenAPI paths include nested FastAPI router prefixes.
        self.routes = [(compile_path(path)[0], frozenset(method.upper() for method in methods), path)
                       for path, methods in owner.openapi()['paths'].items()]

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = perf_counter()
        state = scope.setdefault('state', {})
        headers = scope.get('headers', [])
        limits = self.settings
        headers_exceed_limits = (len(headers) > limits.request_max_header_count
            or sum(len(k) + len(v) for k, v in headers) > limits.request_max_header_bytes
            or any(len(k) > 128 or len(v) > limits.request_max_header_value_bytes for k, v in headers))
        path_exceeds_limit = len(scope['path']) > 2048 or len(scope['path'].encode()) > 2048
        # Inbound safe IDs may be echoed; logs always use independent generated IDs.
        generated, correlation = uuid4().hex, uuid4().hex
        state.update(request_id=generated, correlation_id=correlation, authenticated=False)
        for name, key in (() if headers_exceed_limits else
                ((b'x-request-id', 'request_id'), (b'x-correlation-id', 'correlation_id'))):
            values = [v.decode('latin1') for k, v in headers if k.lower() == name]
            if len(values) == 1 and ID_GRAMMAR.fullmatch(values[0]):
                state[key] = values[0]
        route = 'UNMATCHED'
        for pattern, methods, template in (() if path_exceeds_limit else self.routes):
            if pattern.fullmatch(scope['path']) and scope['method'] in methods:
                route = template
                break
        telemetry = self.owner.state.telemetry
        measurement = QueryMeasurement()
        token = query_measurement.set(measurement)
        status: int | None = None

        async def response_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message['headers'] = [(k, v) for k, v in message.get('headers', [])
                    if k.lower() not in {b'x-request-id', b'x-correlation-id'}] + [
                    (b'x-request-id', state['request_id'].encode()),
                    (b'x-correlation-id', state['correlation_id'].encode())]
            await send(message)

        async def reject(code, message, response_status):
            payload = json.dumps({'error': {'code': code, 'message': message,
                'details': None, 'request_id': state['request_id']}}).encode()
            await response_send({'type': 'http.response.start', 'status': response_status,
                                 'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
            await send({'type': 'http.response.body', 'body': payload})

        try:
            if headers_exceed_limits:
                return await reject('REQUEST_HEADERS_TOO_LARGE', 'Request headers exceed server limits.', 431)
            if len(scope.get('query_string', b'')) > limits.request_max_query_bytes or path_exceeds_limit:
                return await reject('REQUEST_INPUT_TOO_LARGE', 'Request input exceeds server limits.', 414)
            lengths = [v for k, v in headers if k.lower() == b'content-length']
            if len(lengths) > 1 or lengths and (len(lengths[0]) > 10 or not lengths[0].isdigit()):
                return await reject('INVALID_CONTENT_LENGTH', 'Invalid Content-Length.', 400)
            expected = int(lengths[0]) if lengths else None
            if expected is not None and expected > limits.request_max_body_bytes:
                return await reject('REQUEST_BODY_TOO_LARGE', 'Request body exceeds server limits.', 413)
            cost = operation_cost(route, scope['method'])
            # Paper's authenticated budget is checked by its route dependency, before domain work.
            check_admission(self.owner.state.admission_backend, AdmissionContext(route,
                CostClass.CHEAP_READ if '/paper/' in route else cost))
            parts, size = [], 0
            deadline = perf_counter() + limits.request_body_timeout_seconds
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=max(.001, deadline - perf_counter()))
                except TimeoutError:
                    return await reject('REQUEST_BODY_TIMEOUT', 'Request body was not available within the server deadline.', 408)
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > limits.request_max_body_bytes:
                    return await reject('REQUEST_BODY_TOO_LARGE', 'Request body exceeds server limits.', 413)
                if chunk:
                    parts.append(chunk)
                if not message.get('more_body', False):
                    break
            if expected is not None and size != expected:
                return await reject('INVALID_CONTENT_LENGTH', 'Content-Length does not match the body.', 400)
            content_types = [v.decode('latin1').split(';')[0].strip().lower()
                             for k, v in headers if k.lower() == b'content-type']
            if size and (len(content_types) != 1 or content_types[0] != 'application/json'):
                return await reject('JSON_CONTENT_TYPE_REQUIRED', 'JSON Content-Type is required.', 415)
            body = b''.join(parts)
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}

            await self.app(scope, bounded_receive, response_send)
        except AppError as error:
            telemetry.emit('admission', outcome='denied', operation=operation_cost(route, scope['method']).value)
            await reject(error.code, error.message, error.status_code)
        finally:
            query_measurement.reset(token)
            telemetry.emit('http', request_id=generated, correlation_id=correlation, route=route,
                method=scope['method'], status_class=None if status is None else status // 100,
                duration_seconds=perf_counter() - started, authenticated=state['authenticated'],
                operation=operation_cost(route, scope['method']).value,
                query_count=measurement.count, query_seconds=measurement.seconds,
                outcome='unknown' if status is None else 'ok' if status < 400 else 'error')
