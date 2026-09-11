from datetime import datetime

from backend.common.time_utils import BEIJING_TZ
from backend.services import live_scheduler


def _configure(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scheduler, "STATUS_PATH", tmp_path / "scheduler.json")
    monkeypatch.setenv(live_scheduler.AUTO_ENABLED_ENV, "true")
    monkeypatch.setenv(live_scheduler.AUTO_TIME_ENV, "15:20")


def test_scheduler_runs_once_after_weekday_close(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    now = datetime(2026, 9, 11, 15, 20, tzinfo=BEIJING_TZ)
    assert live_scheduler.should_run(now) is True
    live_scheduler._write_status({"last_attempt_date": "2026-09-11", "last_status": "completed"})
    assert live_scheduler.should_run(now) is False
    live_scheduler._write_status({"last_attempt_date": "2026-09-11", "last_status": "running"})
    assert live_scheduler.should_run(now) is True


def test_scheduler_skips_stale_state_for_holiday_or_late_update(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        live_scheduler.live_service,
        "local_source_status",
        lambda: {"available": True, "state_trade_date": "2026-09-10"},
    )
    result = live_scheduler.run_today(datetime(2026, 9, 11, 15, 20, tzinfo=BEIJING_TZ))
    assert result["last_status"] == "skipped"
    assert live_scheduler._read_status()["last_attempt_date"] == "2026-09-11"


def test_scheduler_captures_and_tracks_local_sources(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        live_scheduler.live_service,
        "local_source_status",
        lambda: {"available": True, "state_trade_date": "2026-09-11"},
    )
    monkeypatch.setattr(
        live_scheduler.live_service,
        "list_sources",
        lambda: [{"source_id": "live_1", "name": "实盘组合", "source_kind": "local_dir"}],
    )
    monkeypatch.setattr(
        live_scheduler.live_service,
        "import_snapshot",
        lambda source_id, payload: calls.append(("snapshot", source_id, payload["trade_date"])),
    )
    monkeypatch.setattr(live_scheduler.live_repository, "previous_snapshot", lambda *_args: {"snapshot_id": "prior"})
    monkeypatch.setattr(
        live_scheduler.live_service,
        "track_day",
        lambda source_id, trade_date, update_data: (
            calls.append(("track", source_id, trade_date, update_data))
            or {"summary": {"total": 1, "match": 1, "mismatch": 0, "trade_count": 2}}
        ),
    )

    result = live_scheduler.run_today(datetime(2026, 9, 11, 15, 20, tzinfo=BEIJING_TZ))
    assert result["last_status"] == "completed"
    assert calls == [
        ("snapshot", "live_1", "2026-09-11"),
        ("track", "live_1", "2026-09-11", True),
    ]
