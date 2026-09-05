import datetime
import zoneinfo
from unittest import mock

from app import scheduler

SGT = zoneinfo.ZoneInfo("Asia/Singapore")


def test_busy_hours_use_30_minute_interval():
    for hour in (9, 12, 16):
        dt = datetime.datetime(2026, 1, 1, hour, 30, tzinfo=SGT)
        assert scheduler.next_interval_seconds(dt) == 30 * 60


def test_quiet_hours_use_3_hour_interval():
    for hour in (0, 3, 8, 17, 20, 23):
        dt = datetime.datetime(2026, 1, 1, hour, 0, tzinfo=SGT)
        assert scheduler.next_interval_seconds(dt) == 3 * 60 * 60


def test_busy_hours_boundary_is_inclusive_start_exclusive_end():
    assert scheduler.next_interval_seconds(datetime.datetime(2026, 1, 1, 9, 0, tzinfo=SGT)) == 30 * 60
    assert scheduler.next_interval_seconds(datetime.datetime(2026, 1, 1, 16, 59, tzinfo=SGT)) == 30 * 60
    assert scheduler.next_interval_seconds(datetime.datetime(2026, 1, 1, 17, 0, tzinfo=SGT)) == 3 * 60 * 60


def test_run_scheduled_check_calls_cmd_check_sso_with_override(monkeypatch):
    calls = []

    def fake_cmd_check_sso(db, live, simulate, clause_ref, override_schedule):
        calls.append((live, simulate, clause_ref, override_schedule))
        return mock.Mock(ok=True, message=None)

    monkeypatch.setattr(scheduler.cli, "cmd_check_sso", fake_cmd_check_sso)

    scheduler.run_scheduled_check()

    assert len(calls) == 1
    live, simulate, clause_ref, override_schedule = calls[0]
    assert live is True
    assert simulate is False
    assert override_schedule is True  # deliberately bypasses should_run_now()'s 3-7am gate


def test_run_scheduled_check_never_raises_even_if_cmd_check_sso_fails(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(scheduler.cli, "cmd_check_sso", boom)

    scheduler.run_scheduled_check()  # must not raise
