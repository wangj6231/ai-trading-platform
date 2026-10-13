"""Share only an active evaluation; each caller retains its own projection."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

import anyio

from app.core.errors import AppError


@dataclass(eq=False)
class _Flight:
    members: dict[object, tuple[dict[str, Any], asyncio.Future]] = field(default_factory=dict)
    task: asyncio.Task | None = None
    accepting: bool = True


class InFlightResponses:
    def __init__(self, *, capacity: int = 2) -> None:
        self._capacity = capacity
        self._leases: set[object] = set()
        self._flights: dict[Hashable, _Flight] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def reserve(self) -> object:
        if self._closed or len(self._leases) >= self._capacity:
            raise AppError(status_code=503, code='STRATEGY_EVALUATION_BUSY',
                message='Strategy evaluation capacity is busy. Retry later.')
        lease = object()
        self._leases.add(lease)
        return lease

    def release(self, lease: object) -> None:
        self._leases.discard(lease)

    async def response(self, key: Hashable, payload: dict[str, Any],
        execute: Callable[..., Awaitable[Any]]) -> bytes:
        member = object()
        future = asyncio.get_running_loop().create_future()
        flight = self._flights.get(key)
        if flight is None or not flight.accepting:
            flight = _Flight()
            self._flights[key] = flight
            flight.members[member] = (payload, future)
            task = asyncio.create_task(self._execute(key, flight, execute))
            flight.task = task
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            flight.members[member] = (payload, future)
        try:
            return await asyncio.shield(future)
        finally:
            flight.members.pop(member, None)
            if not future.done():
                future.cancel()
            if not flight.members and flight.task is not None:
                with anyio.CancelScope(shield=True):
                    if not flight.task.done():
                        flight.task.cancel()
                    await asyncio.gather(flight.task, return_exceptions=True)

    async def _execute(self, key: Hashable, flight: _Flight, execute) -> None:
        snapshot: list[tuple[dict[str, Any], asyncio.Future]] = []
        async def projections():
            flight.accepting = False
            snapshot.extend(flight.members.values())
            return [payload for payload, _ in snapshot]
        def published(message):
            index, body = message
            future = snapshot[index][1]
            if not future.done():
                future.set_result(body)
        try:
            initial = next(iter(flight.members.values()))[0]
            await execute({**initial, '_response_group': True}, projections, published)
            if any(not future.done() for _, future in flight.members.values()):
                raise RuntimeError('worker did not publish every response')
        except asyncio.CancelledError:
            for _, future in flight.members.values():
                future.cancel()
            raise
        except Exception as exc:
            for _, future in flight.members.values():
                if not future.done():
                    future.set_exception(exc)
        finally:
            if self._flights.get(key) is flight:
                self._flights.pop(key)

    async def aclose(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
