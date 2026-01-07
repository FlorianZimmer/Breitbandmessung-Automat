import argparse
import random
from datetime import datetime, timedelta, time as dtime, date as real_date

import breitbandmessung_automate_stateful as bbm


def test_parse_hhmm_valid():
    assert bbm.parse_hhmm("07:05") == dtime(hour=7, minute=5)


def test_parse_hhmm_invalid_raises():
    try:
        bbm.parse_hhmm("0705")
    except argparse.ArgumentTypeError:
        return
    raise AssertionError("expected argparse.ArgumentTypeError")


def test_required_gap_after_completed_rule():
    assert bbm.required_gap_after_completed(5) == timedelta(hours=3)
    assert bbm.required_gap_after_completed(1) == timedelta(minutes=5)
    assert bbm.required_gap_after_completed(6) == timedelta(minutes=5)


def test_min_gap_after_completed_adds_buffer():
    assert bbm.min_gap_after_completed(1, min_gap_buffer_seconds=120) == timedelta(minutes=5, seconds=120)


def test_min_remaining_gap_total_sums_all_future_gaps():
    # For a 10/day goal, after completing #5 we need a 3h gap once, all others 5m, all +2m buffer.
    total = bbm.min_remaining_gap_total(next_completed_in_day=5, day_goal=10, min_gap_buffer_seconds=120)
    expected = (
        (timedelta(hours=3) + timedelta(seconds=120))  # after completion #5
        + (timedelta(minutes=5) + timedelta(seconds=120)) * 4  # after completions #6..#9
    )
    assert total == expected


def test_choose_next_start_time_none_when_infeasible():
    last_start = datetime(2026, 1, 7, 10, 0, 0)
    last_end = datetime(2026, 1, 7, 10, 5, 0)
    day_end = datetime(2026, 1, 7, 10, 10, 0)
    rng = random.Random(0)
    assert (
        bbm.choose_next_start_time(
            last_start=last_start,
            last_end=last_end,
            completed_in_day=5,
            day_goal=10,
            day_end=day_end,
            min_gap_buffer_seconds=120,
            post_measurement_settle_seconds=30,
            rng=rng,
        )
        is None
    )


def test_choose_next_start_time_within_bounds_and_deterministic():
    last_start = datetime(2026, 1, 7, 8, 0, 0)
    last_end = datetime(2026, 1, 7, 8, 1, 0)
    day_end = datetime(2026, 1, 7, 23, 0, 0)
    rng = random.Random(123)

    next_start = bbm.choose_next_start_time(
        last_start=last_start,
        last_end=last_end,
        completed_in_day=1,
        day_goal=10,
        day_end=day_end,
        min_gap_buffer_seconds=120,
        post_measurement_settle_seconds=30,
        rng=rng,
    )
    assert next_start is not None

    earliest = max(
        last_start + bbm.min_gap_after_completed(1, min_gap_buffer_seconds=120),
        last_end + timedelta(seconds=30),
    )
    min_future = bbm.min_remaining_gap_total(next_completed_in_day=2, day_goal=10, min_gap_buffer_seconds=120)
    latest = day_end - min_future
    assert earliest <= next_start <= latest


def test_iso_dt_parse_roundtrip():
    dt = datetime(2026, 1, 7, 12, 34, 56)
    s = bbm.iso_dt(dt)
    assert s == "2026-01-07T12:34:56"
    assert bbm.parse_iso_dt(s) == dt
    assert bbm.iso_dt(None) is None
    assert bbm.parse_iso_dt(None) is None


def test_day_dt_combines_date_time():
    d = real_date(2026, 1, 7)
    t = dtime(7, 0)
    assert bbm.day_dt(d, t) == datetime(2026, 1, 7, 7, 0, 0)


def test_sleep_until_does_not_sleep_when_target_reached(monkeypatch):
    monkeypatch.setattr(bbm, "now", lambda: datetime(2026, 1, 7, 12, 0, 0))
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("slept")))
    bbm.sleep_until(datetime(2026, 1, 7, 11, 59, 59))


def test_sleep_until_sleeps_in_chunks(monkeypatch):
    calls = []
    times = [
        datetime(2026, 1, 7, 12, 0, 0),
        datetime(2026, 1, 7, 12, 1, 0),
        datetime(2026, 1, 7, 12, 2, 0),
    ]
    it = iter(times)
    monkeypatch.setattr(bbm, "now", lambda: next(it))
    monkeypatch.setattr(bbm.time, "sleep", lambda s: calls.append(s))
    bbm.sleep_until(datetime(2026, 1, 7, 12, 2, 0))
    assert calls == [60.0, 60.0]
