from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StrategyGenerateRequest(BaseModel):
    source_text: str
    options: dict[str, Any] | None = None


class ResearchCreateRequest(BaseModel):
    source_text: str
    symbol: str = "510300"
    exchange: str = "SSE"
    interval: str = "1m"
    start_date: str | None = None
    end_date: str | None = None
    capital: float = 100000.0
    rate: float = 0.000045
    slippage: float = 0.001
    size: float = 1.0
    pricetick: float = 0.001
    mode: str = "real"
    options: dict[str, Any] | None = None


class PoolAddRequest(BaseModel):
    run_id: str
    variant_name: str = "baseline"
    tags: list[str] | None = None
    note: str | None = None
    vt_symbol: str | None = None


class PoolCompareRequest(BaseModel):
    pool_item_ids: list[str] = Field(default_factory=list)


class PoolListQuery(BaseModel):
    keyword: str | None = None
    vt_symbol: str | None = None
    min_sharpe: float | None = None
    tag: str | None = None
    sort_by: str = "created_at"
    order: str = "desc"
    limit: int = Field(default=100, ge=1, le=1000)


class DataDownloadRequest(BaseModel):
    symbol: str
    exchange: str
    interval: str = "1m"
    start_date: str
    end_date: str


class OptimizationSearchSpaceRequest(BaseModel):
    run_id: str
    variant_name: str = "baseline"


class OptimizationRunRequest(BaseModel):
    run_id: str
    variant_name: str = "baseline"
    method: str = "manual_grid"
    selected_parameters: list[str] = Field(default_factory=list)
    parameter_ranges: dict[str, Any] = Field(default_factory=dict)
    objective: str = "sharpe"
    max_trials: int = Field(default=200, ge=1, le=5000)
