from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

STORAGE_ROOT = PROJECT_ROOT / "storage"
DB_ROOT = STORAGE_ROOT / "db"
RUNTIME_ROOT = STORAGE_ROOT / "runtime"
RUNS_ROOT = RUNTIME_ROOT / "runs"
CACHE_ROOT = STORAGE_ROOT / "cache"
POOL_ROOT = STORAGE_ROOT / "pool"
POOL_STRATEGIES_ROOT = POOL_ROOT / "strategies"

STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
GENERATED_STRATEGIES_ROOT = STRATEGIES_ROOT / "generated"
VALIDATED_STRATEGIES_ROOT = STRATEGIES_ROOT / "validated"
TEMPLATES_ROOT = STRATEGIES_ROOT / "templates"


REQUIRED_DIRECTORIES = (
    STORAGE_ROOT,
    DB_ROOT,
    RUNTIME_ROOT,
    RUNS_ROOT,
    CACHE_ROOT,
    POOL_ROOT,
    POOL_STRATEGIES_ROOT,
    STRATEGIES_ROOT,
    GENERATED_STRATEGIES_ROOT,
    VALIDATED_STRATEGIES_ROOT,
    TEMPLATES_ROOT,
)


def ensure_directories() -> None:
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()

