from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    STRATEGY_GENERATION = "strategy_generation"
    BACKTEST = "backtest"
    OPTIMIZATION = "optimization"
    DATA_DOWNLOAD = "data_download"
    POOL_ADD = "pool_add"
    POOL_REBUILD = "pool_rebuild"
    STRATEGY_RESEARCH = "strategy_research"


class RunType(StrEnum):
    BASELINE = "baseline"
    OPTIMIZATION = "optimization"
    MANUAL_GRID = "manual_grid"


class VariantType(StrEnum):
    BASELINE = "baseline"
    MANUAL_GRID = "manual_grid"
    RECOMMENDED = "recommended"
    ROBUST = "robust"
    PRODUCTION_SAFE = "production_safe"


class ArtifactType(StrEnum):
    MANIFEST = "manifest"
    INPUT = "input"
    CONFIG = "config"
    STRATEGY_CODE = "strategy_code"
    RESULT = "result"
    DAILY_RESULTS = "daily_results"
    TRADES = "trades"
    GRID_SUMMARY = "grid_summary"
    LOG = "log"
    POOL_SNAPSHOT = "pool_snapshot"
    GENERATION_REPORT = "generation_report"
