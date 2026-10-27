from datetime import datetime

from app.core.schedule_plan import (
    DEFAULT_SYNC_CRON,
    METRIC_CALC_TIMES,
    SCHEDULE_TZ,
    build_cron_trigger,
    build_daily_trigger,
    cron_has_fire_at,
    is_month_settlement_run,
    latest_schedule_slot,
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


def test_sync_cron_is_four_times_daily() -> None:
    assert DEFAULT_SYNC_CRON == "0 0 0 * * ?;0 0 7 * * ?;0 0 12 * * ?;0 0 18 * * ?"
    assert normalize_sync_cron("0 0 2 * * ?") == DEFAULT_SYNC_CRON
    assert normalize_sync_cron("0 0 5 * * ?") == DEFAULT_SYNC_CRON
    assert normalize_sync_cron(DEFAULT_SYNC_CRON) == DEFAULT_SYNC_CRON


def test_weekly_cron_becomes_daily_four_times() -> None:
    assert normalize_sync_cron("0 0 2 ? * MON") == DEFAULT_SYNC_CRON


def test_year_specific_never_cron_is_preserved() -> None:
    never = "0 0 0 * * ? 2000"
    assert normalize_sync_cron(never) == never


def test_multi_cron_fires_four_times_per_day() -> None:
    trigger = build_cron_trigger(DEFAULT_SYNC_CRON)
    start = datetime(2026, 10, 23, 0, 0, tzinfo=SCHEDULE_TZ)
    assert _next_times(trigger, start, 4) == ["00:00", "07:00", "12:00", "18:00"]


def test_metric_trigger_fires_four_times_per_day() -> None:
    trigger = build_daily_trigger(METRIC_CALC_TIMES)
    start = datetime(2026, 10, 23, 0, 0, tzinfo=SCHEDULE_TZ)
    assert _next_times(trigger, start, 4) == ["00:00", "07:00", "12:00", "18:00"]


def test_cron_has_fire_at_matches_each_slot() -> None:
    for hour, minute in METRIC_CALC_TIMES:
        when = datetime(2026, 10, 23, hour, minute, tzinfo=SCHEDULE_TZ)
        assert cron_has_fire_at(DEFAULT_SYNC_CRON, when)


def test_latest_schedule_slot() -> None:
    assert latest_schedule_slot(datetime(2026, 10, 23, 0, 10, tzinfo=SCHEDULE_TZ)).strftime("%H:%M") == "00:00"
    assert latest_schedule_slot(datetime(2026, 10, 23, 6, 59, tzinfo=SCHEDULE_TZ)).strftime("%H:%M") == "00:00"
    assert latest_schedule_slot(datetime(2026, 10, 23, 9, 0, tzinfo=SCHEDULE_TZ)).strftime("%H:%M") == "07:00"
    assert latest_schedule_slot(datetime(2026, 10, 23, 12, 30, tzinfo=SCHEDULE_TZ)).strftime("%H:%M") == "12:00"
    assert latest_schedule_slot(datetime(2026, 10, 23, 19, 0, tzinfo=SCHEDULE_TZ)).strftime("%H:%M") == "18:00"


def test_month_settlement_only_in_midnight_slot() -> None:
    assert is_month_settlement_run(datetime(2026, 11, 1, 0, 10, tzinfo=SCHEDULE_TZ))
    assert not is_month_settlement_run(datetime(2026, 11, 1, 7, 0, tzinfo=SCHEDULE_TZ))
    assert not is_month_settlement_run(datetime(2026, 11, 1, 12, 0, tzinfo=SCHEDULE_TZ))
    assert not is_month_settlement_run(datetime(2026, 11, 1, 18, 0, tzinfo=SCHEDULE_TZ))
