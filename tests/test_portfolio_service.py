from __future__ import annotations

from pathlib import Path
import csv

import pytest

from backend.services import portfolio_service


def _pool_item(root: Path, pool_item_id: str, rows: list[dict[str, object]]) -> dict[str, object]:
    pool_path = root / pool_item_id
    pool_path.mkdir(parents=True)
    daily_path = pool_path / "daily_results.csv"
    with daily_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "close_price", "pre_close", "net_pnl", "commission", "turnover", "trade_count"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return {
        "pool_item_id": pool_item_id,
        "pool_path": str(pool_path),
        "strategy_name": pool_item_id,
        "strategy_version": "v1",
        "vt_symbol": "511380.SSE",
    }


def test_portfolio_uses_weighted_unit_returns_and_cash_fills_missing_dates(tmp_path, monkeypatch):
    items = {
        "pool_a": _pool_item(tmp_path, "pool_a", [
            {"date": "2026-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 10, "commission": 1, "turnover": 100, "trade_count": 1},
            {"date": "2026-01-02", "close_price": 100, "pre_close": 100, "net_pnl": 10, "commission": 1, "turnover": 100, "trade_count": 1},
            {"date": "2026-01-03", "close_price": 100, "pre_close": 100, "net_pnl": -20, "commission": 1, "turnover": 100, "trade_count": 2},
        ]),
        "pool_b": _pool_item(tmp_path, "pool_b", [
            {"date": "2026-01-02", "close_price": 200, "pre_close": 200, "net_pnl": 0, "commission": 0, "turnover": 0, "trade_count": 0},
            {"date": "2026-01-03", "close_price": 200, "pre_close": 200, "net_pnl": 20, "commission": 2, "turnover": 200, "trade_count": 1},
            {"date": "2026-01-04", "close_price": 200, "pre_close": 200, "net_pnl": 20, "commission": 2, "turnover": 200, "trade_count": 1},
        ]),
    }
    monkeypatch.setattr(portfolio_service.pool_repository, "get_pool_item", lambda pool_item_id: items.get(pool_item_id))

    result = portfolio_service.calculate_portfolio_definition({
        "name": "测试组合",
        "virtual_capital": 100_000,
        "components": [
            {"pool_item_id": "pool_a", "weight": 1},
            {"pool_item_id": "pool_b", "weight": 3},
        ],
    })

    assert result["definition"]["alignment_mode"] == "cash_fill"
    assert result["definition"]["start_date"] == "2026-01-01"
    assert result["definition"]["end_date"] == "2026-01-04"
    assert [row["daily_return"] for row in result["daily_results"]] == pytest.approx([2.5, 2.5, 2.5, 7.5])
    assert [row["cash_weight"] for row in result["daily_results"]] == pytest.approx([0.75, 0.0, 0.0, 0.25])
    assert result["metrics"]["total_return"] == pytest.approx(15.0)
    assert result["metrics"]["virtual_pnl"] == pytest.approx(15_000.0)
    assert result["metrics"]["trade_count"] == 6
    assert result["metrics"]["cash_days"] == 2
    assert result["metrics"]["average_cash_weight"] == pytest.approx(0.25)
    summaries = {item["pool_item_id"]: item for item in result["components"]}
    assert summaries["pool_a"]["effective_weight"] == pytest.approx(0.25)
    assert summaries["pool_a"]["weighted_contribution"] == pytest.approx(0.0)
    assert summaries["pool_a"]["cash_days"] == 1
    assert summaries["pool_b"]["weighted_contribution"] == pytest.approx(15.0)
    assert summaries["pool_b"]["cash_days"] == 1


def test_portfolio_drawdown_is_based_on_simple_cumulative_returns(tmp_path, monkeypatch):
    item = _pool_item(tmp_path, "pool_a", [
        {"date": "2026-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 10},
        {"date": "2026-01-02", "close_price": 100, "pre_close": 100, "net_pnl": -20},
        {"date": "2026-01-03", "close_price": 100, "pre_close": 100, "net_pnl": 5},
    ])
    monkeypatch.setattr(portfolio_service.pool_repository, "get_pool_item", lambda _pool_item_id: item)

    result = portfolio_service.calculate_portfolio_definition({
        "name": "回撤测试",
        "virtual_capital": 100_000,
        "components": [{"pool_item_id": "pool_a", "weight": 1}],
    })

    assert result["metrics"]["total_return"] == pytest.approx(-5.0)
    assert result["metrics"]["max_drawdown"] == pytest.approx(-20.0)
    assert [row["cumulative_return"] for row in result["daily_results"]] == pytest.approx([10.0, -10.0, -5.0])


def test_portfolio_rejects_dates_outside_available_data_interval(tmp_path, monkeypatch):
    item = _pool_item(tmp_path, "pool_a", [
        {"date": "2026-01-02", "close_price": 100, "pre_close": 100, "net_pnl": 1},
        {"date": "2026-01-03", "close_price": 100, "pre_close": 100, "net_pnl": 1},
    ])
    monkeypatch.setattr(portfolio_service.pool_repository, "get_pool_item", lambda _pool_item_id: item)

    with pytest.raises(ValueError, match="已有数据总区间"):
        portfolio_service.calculate_portfolio_definition({
            "name": "越界测试",
            "virtual_capital": 100_000,
            "start_date": "2026-01-01",
            "components": [{"pool_item_id": "pool_a", "weight": 1}],
        })


def test_portfolio_cash_fills_internal_component_gaps_without_renormalizing_weights(tmp_path, monkeypatch):
    items = {
        "pool_a": _pool_item(tmp_path, "pool_a", [
            {"date": "2026-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 10},
            {"date": "2026-01-03", "close_price": 100, "pre_close": 100, "net_pnl": 10},
        ]),
        "pool_b": _pool_item(tmp_path, "pool_b", [
            {"date": "2026-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 20},
            {"date": "2026-01-02", "close_price": 100, "pre_close": 100, "net_pnl": 20},
            {"date": "2026-01-03", "close_price": 100, "pre_close": 100, "net_pnl": 20},
        ]),
    }
    monkeypatch.setattr(portfolio_service.pool_repository, "get_pool_item", lambda pool_item_id: items.get(pool_item_id))

    result = portfolio_service.calculate_portfolio_definition({
        "name": "断档现金测试",
        "virtual_capital": 100_000,
        "components": [
            {"pool_item_id": "pool_a", "weight": 1},
            {"pool_item_id": "pool_b", "weight": 1},
        ],
    })

    assert [row["daily_return"] for row in result["daily_results"]] == pytest.approx([15.0, 10.0, 15.0])
    assert [row["cash_weight"] for row in result["daily_results"]] == pytest.approx([0.0, 0.5, 0.0])
    assert result["metrics"]["total_return"] == pytest.approx(40.0)
    assert result["components"][0]["cash_days"] == 1


def test_portfolio_allows_components_with_no_common_interval(tmp_path, monkeypatch):
    items = {
        "pool_a": _pool_item(tmp_path, "pool_a", [
            {"date": "2025-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 10},
        ]),
        "pool_b": _pool_item(tmp_path, "pool_b", [
            {"date": "2026-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 20},
        ]),
    }
    monkeypatch.setattr(portfolio_service.pool_repository, "get_pool_item", lambda pool_item_id: items.get(pool_item_id))

    result = portfolio_service.calculate_portfolio_definition({
        "name": "无交集现金测试",
        "virtual_capital": 100_000,
        "components": [
            {"pool_item_id": "pool_a", "weight": 1},
            {"pool_item_id": "pool_b", "weight": 1},
        ],
    })

    assert result["definition"]["has_common_interval"] is False
    assert result["definition"]["common_start_date"] == ""
    assert result["definition"]["common_end_date"] == ""
    assert [row["daily_return"] for row in result["daily_results"]] == pytest.approx([5.0, 10.0])
    assert [row["cash_weight"] for row in result["daily_results"]] == pytest.approx([0.5, 0.5])
