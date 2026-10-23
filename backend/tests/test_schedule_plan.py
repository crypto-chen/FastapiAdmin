from datetime import datetime

from app.core.schedule_plan import (
    DEFAULT_SYNC_CRON,
    METRIC_CALC_TIMES,
    SCHEDULE_TZ,
    build_cron_trigger,
    build_daily_trigger,
    cron_has_fire_at,
    latest_daytime_slot,
    normalize_sync_cron,
)


def _next_times(trigger, start: datetime, count: int) -> list[str]:
    times: list[str] = []
    previous = None
    cursor = start
    for _ in range(count):
        fire_time = trigger.get_next_fire_time(previous, cursor)
        assert fire_time is not None
        times.append(fire_time.strftime("%H:%M"))
        previous = fire_time
        cursor = fire_time
    return times


def test_sync_cron_keeps_early_run_and_adds_daytime() -> None:
    assert normalize_sync_cron("0 0 2 * * ?") == DEFAULT_SYNC_CRON
    assert normalize_sync_cron("0 0 5 * * ?") == "0 0 5 * * ?;0 20 12 * * ?;0 20 18 * * ?"
    assert normalize_sync_cron(DEFAULT_SYNC_CRON) == DEFAULT_SYNC_CRON


def test_weekly_cron_becomes_daily_three_times() -> None:
    normalized = normalize_sync_cron("0 0 2 ? * MON")
    assert normalized == "0 0 2 * * ?;0 20 12 * * ?;0 20 18 * * ?"


def test_multi_cron_fires_three_times_per_day() -> None:
    trigger = build_cron_trigger(DEFAULT_SYNC_CRON)
    start = datetime(2026, 10, 23, 0, 0, tzinfo=SCHEDULE_TZ)
    assert _next_times(trigger, start, 3) == ["02:00", "12:20", "18:20"]


def test_metric_trigger_fires_three_times_per_day() -> None:
    trigger = build_daily_trigger(METRIC_CALC_TIMES)
    start = datetime(2026, 10, 23, 0, 0, tzinfo=SCHEDULE_TZ)
    assert _next_times(trigger, start, 3) == ["02:30", "12:20", "18:20"]


def test_cron_has_fire_at_matches_daytime_slot() -> None:
    noon = datetime(2026, 10, 23, 12, 20, tzinfo=SCHEDULE_TZ)
    evening = datetime(2026, 10, 23, 18, 20, tzinfo=SCHEDULE_TZ)
    assert cron_has_fire_at(DEFAULT_SYNC_CRON, noon)
    assert cron_has_fire_at(DEFAULT_SYNC_CRON, evening)


def test_latest_daytime_slot() -> None:
    assert latest_daytime_slot(datetime(2026, 10, 23, 11, 0, tzinfo=SCHEDULE_TZ)) is None
    noon = latest_daytime_slot(datetime(2026, 10, 23, 15, 0, tzinfo=SCHEDULE_TZ))
    assert noon is not None and noon.strftime("%H:%M") == "12:20"
    evening = latest_daytime_slot(datetime(2026, 10, 23, 19, 0, tzinfo=SCHEDULE_TZ))
    assert evening is not None and evening.strftime("%H:%M") == "18:20"
