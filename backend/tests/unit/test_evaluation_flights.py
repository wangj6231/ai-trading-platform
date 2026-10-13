"""Ownership of active shared work, with no completed-result cache."""
import asyncio

import pytest

from app.core.errors import AppError
from app.services.evaluation_flights import InFlightResponses


@pytest.mark.parametrize('first_cancelled', [False, True])
def test_shared_work_survives_one_waiter_and_keeps_each_projection(first_cancelled):
    async def exercise():
        flights = InFlightResponses()
        started, finish = asyncio.Event(), asyncio.Event()
        calls = 0
        async def execute(payload, projections, published):
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            for index, member in enumerate(await projections()):
                published((index, member['response_kind'].encode()))
        first = asyncio.create_task(flights.response('same', {'response_kind': 'signal'}, execute))
        await started.wait()
        second = asyncio.create_task(flights.response('same', {'response_kind': 'analysis'}, execute))
        await asyncio.sleep(0)
        if first_cancelled:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            assert calls == 1 and len(flights._tasks) == 1
        finish.set()
        assert await second == b'analysis'
        if not first_cancelled:
            assert await first == b'signal'
        assert calls == 1 and not flights._flights and not flights._tasks
        assert await flights.response('same', {'response_kind': 'signal'}, execute) == b'signal'
        assert calls == 2  # Completed work is not retained or reused.
        await flights.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize('shutdown', [False, True])
def test_all_waiters_cancel_or_shutdown_reaps_owned_work(shutdown):
    async def exercise():
        flights = InFlightResponses()
        started, reaped = asyncio.Event(), asyncio.Event()
        async def execute(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.01)
                reaped.set()
        first = asyncio.create_task(flights.response('same', {}, execute))
        await started.wait()
        second = asyncio.create_task(flights.response('same', {}, execute))
        await asyncio.sleep(0)
        if shutdown:
            await flights.aclose()
        else:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            assert not reaped.is_set()
            second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
        assert reaped.is_set() and not flights._flights and not flights._tasks
    asyncio.run(exercise())


def test_different_evidence_runs_separately_and_errors_reach_all_waiters():
    async def exercise():
        flights = InFlightResponses()
        started, finish = asyncio.Event(), asyncio.Event()
        calls = 0
        async def execute(*args):
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            raise AppError(status_code=504, code='STRATEGY_EVALUATION_TIMEOUT', message='technical failure')
        tasks = [asyncio.create_task(flights.response(key, {}, execute)) for key in ['same', 'same', 'different']]
        await started.wait()
        await asyncio.sleep(0)
        assert calls == 2
        finish.set()
        errors = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(error, AppError) and error.code == 'STRATEGY_EVALUATION_TIMEOUT' for error in errors)
        assert not flights._flights and not flights._tasks
    asyncio.run(exercise())


def test_request_capacity_includes_waiters_and_closed_service_rejects():
    async def exercise():
        flights = InFlightResponses(capacity=2)
        first, second = flights.reserve(), flights.reserve()
        with pytest.raises(AppError, match='capacity'):
            flights.reserve()
        flights.release(first)
        third = flights.reserve()
        flights.release(second)
        flights.release(third)
        assert not flights._leases
        await flights.aclose()
        with pytest.raises(AppError):
            flights.reserve()
    asyncio.run(exercise())
