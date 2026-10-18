from datetime import date, datetime

from backend.services import executor_service
from executor.portfolio import Book
from executor.store import Store


def test_overview_reads_engine_database(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_service, "EXECUTOR_ROOT", tmp_path)
    store = Store(tmp_path / "backtests" / "demo" / "executor.sqlite")
    book = Book("rot_hk_dividend", 100_000, 500, {"513530.SH": 1000}).to_dict()
    store.save_book(datetime(2026, 1, 5), book)
    store.end_of_day(date(2026, 1, 5), "rot_hk_dividend", book, {}, 101_000)
    store.decision(datetime(2026, 1, 5, 14, 56), "rot_hk_dividend", {"z": {"513530.SH": 0.1}, "action": "none"})
    store.event(datetime(2026, 1, 5, 10), "order_rejected", "rot_hk_dividend", reason="资金不足")
    store.conn.execute("INSERT INTO unit_returns VALUES (?,?,?,?)", ("2026-01-05", "rot_hk_dividend", 2.5, 2.5))
    store.commit()
    runs = executor_service.list_runs()["items"]
    assert runs[0]["id"] == "backtest:demo"
    o = executor_service.overview("backtest:demo")
    s = o["strategies"][0]
    assert s["positions"] == {"513530.SH": 1000} and s["return_pct"] == 2.5
    assert s["latest_decision"]["action"] == "none"
    assert o["alerts"][0]["payload"]["reason"] == "资金不足"


def test_overview_rejects_path_like_run_ids():
    import pytest
    with pytest.raises(ValueError):
        executor_service.overview("backtest:../../etc")
