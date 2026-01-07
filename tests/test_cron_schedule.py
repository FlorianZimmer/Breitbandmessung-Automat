from datetime import datetime

import breitbandmessung_automate_stateful as bbm


def test_parse_cron_schedule_min_hour_only():
    sch = bbm.parse_cron_schedule("0 7,10,20 * * *")
    assert 0 in sch.minutes
    assert sch.hours == (7, 10, 20)


def test_cron_next_on_or_after_rounds_up_to_next_minute():
    sch = bbm.parse_cron_schedule("0 * * * *")  # top of hour
    dt = datetime(2026, 1, 7, 10, 0, 1)
    assert sch.next_on_or_after(dt) == datetime(2026, 1, 7, 11, 0, 0)


def test_choose_next_start_time_uses_cron_schedule():
    sch = bbm.parse_cron_schedule("0 * * * *")
    last_start = datetime(2026, 1, 7, 10, 0, 0)
    last_end = datetime(2026, 1, 7, 10, 1, 0)
    day_end = datetime(2026, 1, 7, 23, 0, 0)

    next_start = bbm.choose_next_start_time(
        last_start=last_start,
        last_end=last_end,
        completed_in_day=1,
        day_goal=10,
        day_end=day_end,
        min_gap_buffer_seconds=120,
        post_measurement_settle_seconds=30,
        rng=bbm.random.Random(0),
        schedule=sch,
    )
    assert next_start is not None
    assert next_start.minute == 0
    assert next_start >= last_start + bbm.min_gap_after_completed(1, min_gap_buffer_seconds=120)
