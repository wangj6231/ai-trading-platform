"""Repeated immutable UTC values retain validation and serialization semantics."""
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, timezone
import sys

import pytest
from app.core import time as clock_values


def test_native_utc_normalization_does_not_repeat_no_op_timezone_conversion():
    calls = []
    def measured(frame, event, arg):
        if event == 'c_call' and getattr(arg, '__name__', '') in {'utcoffset', 'astimezone'}:
            calls.append(arg.__name__)
    instant = datetime(2025, 1, 1, 1, 2, 3, 123456, tzinfo=UTC, fold=1)
    previous = sys.getprofile()
    try:
        sys.setprofile(measured)
        for _ in range(1000):
            normalized = clock_values.normalize_utc_datetime(instant)
            assert normalized == instant and normalized.fold == instant.fold
    finally:
        sys.setprofile(previous)
    assert not calls


def test_datetime_subclass_keeps_original_timezone_validation():
    class InvalidOffset(datetime):
        def utcoffset(self):
            raise ValueError('invalid test offset')
    value = InvalidOffset(2025, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match='invalid UTC offset'):
        clock_values.normalize_utc_datetime(value)


def test_repeated_serialization_formats_one_immutable_instant_once(monkeypatch):
    original = clock_values.normalize_utc_datetime
    calls = 0
    def counted(value):
        nonlocal calls
        calls += 1
        return original(value)
    monkeypatch.setattr(clock_values, 'normalize_utc_datetime', counted)
    scope = getattr(clock_values, 'evaluation_temporal_scope', nullcontext)
    instant = datetime(2025, 1, 1, 1, 2, 3, 123456, tzinfo=UTC)
    for _ in range(2):
        with scope():
            assert {clock_values.canonical_utc_iso(instant) for _ in range(1000)} == {'2025-01-01T01:02:03.123456Z'}
    assert calls <= 2


@pytest.mark.parametrize('value', [
    datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC, fold=1),
    datetime(2025, 1, 1, microsecond=7, tzinfo=timezone(timedelta(hours=8))),
    '2025-01-01T08:00:00.000007+08:00', '2025-01-01T00:00:00Z',
])
def test_temporal_scope_preserves_exact_offset_microsecond_and_fold(value):
    expected = clock_values.normalize_utc_datetime(value)
    encoded = clock_values.canonical_utc_iso(expected)
    scope = getattr(clock_values, 'evaluation_temporal_scope', nullcontext)
    with scope():
        actual = clock_values.normalize_utc_datetime(value)
        assert actual == expected and actual.fold == expected.fold
        assert clock_values.canonical_utc_iso(actual) == encoded


@pytest.mark.parametrize('value', [datetime(2025, 1, 1), '2025-01-01T00:00:00', 'invalid', None, 0])
def test_temporal_scope_never_accepts_untrusted_or_naive_values(value):
    scope = getattr(clock_values, 'evaluation_temporal_scope', nullcontext)
    with scope():
        clock_values.canonical_utc_iso(datetime(2025, 1, 1, tzinfo=UTC))
        with pytest.raises(ValueError):
            clock_values.normalize_utc_datetime(value)
