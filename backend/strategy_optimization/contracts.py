from __future__ import annotations

from typing import Any, TypedDict


class OptimizationResult(TypedDict):
    success: bool
    recommended: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    grid_summary: list[dict[str, Any]]
    best_result: dict[str, Any] | None
    diagnostics: list[dict[str, str]]
    optimizer_name: str
    optimizer_version: str
    error: str | None

