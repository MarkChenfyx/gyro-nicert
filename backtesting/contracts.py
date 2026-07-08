from __future__ import annotations

from typing import Any, TypedDict


class BacktestResult(TypedDict):
    success: bool
    metrics: dict[str, Any]
    daily_results: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    logs: list[str]
    diagnostics: list[dict[str, str]]
    engine_name: str
    engine_version: str
    error: str | None

