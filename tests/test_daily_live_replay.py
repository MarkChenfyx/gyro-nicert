from datetime import datetime

from scripts import daily_live_replay


def test_daily_live_replay_skips_when_state_is_not_for_today(monkeypatch):
    monkeypatch.setattr(daily_live_replay, "now_beijing", lambda: datetime(2026, 9, 11, 15, 20))
    monkeypatch.setattr(
        daily_live_replay.live_service,
        "local_source_status",
        lambda: {"available": True, "state_trade_date": "2026-09-10"},
    )
    monkeypatch.setattr(
        daily_live_replay.live_service,
        "list_sources",
        lambda: (_ for _ in ()).throw(AssertionError("stale state must skip before loading sources")),
    )
    assert daily_live_replay.main() == 0


def test_daily_live_replay_captures_and_tracks_local_sources(monkeypatch):
    calls = []
    monkeypatch.setattr(daily_live_replay, "now_beijing", lambda: datetime(2026, 9, 11, 15, 20))
    monkeypatch.setattr(
        daily_live_replay.live_service,
        "local_source_status",
        lambda: {"available": True, "state_trade_date": "2026-09-11"},
    )
    monkeypatch.setattr(
        daily_live_replay.live_service,
        "list_sources",
        lambda: [{"source_id": "live_1", "name": "实盘组合", "source_kind": "local_dir"}],
    )
    monkeypatch.setattr(
        daily_live_replay.live_service,
        "import_snapshot",
        lambda source_id, payload: calls.append(("snapshot", source_id, payload["trade_date"])),
    )
    monkeypatch.setattr(
        daily_live_replay.live_service,
        "track_day",
        lambda source_id, trade_date, update_data: (
            calls.append(("track", source_id, trade_date, update_data))
            or {"summary": {"total": 1, "match": 1, "mismatch": 0, "trade_count": 2}}
        ),
    )

    assert daily_live_replay.main() == 0
    assert calls == [
        ("snapshot", "live_1", "2026-09-11"),
        ("track", "live_1", "2026-09-11", True),
    ]
