from __future__ import annotations

from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

STORAGE_ROOT = PROJECT_ROOT / "storage"
DB_ROOT = STORAGE_ROOT / "db"
RUNTIME_ROOT = STORAGE_ROOT / "runtime"
RUNS_ROOT = RUNTIME_ROOT / "runs"
RESEARCH_ROOT = RUNTIME_ROOT / "research"
OPTIMIZATION_CURVE_SNAPSHOTS_ROOT = RUNTIME_ROOT / "optimization_curve_snapshots"
CACHE_ROOT = STORAGE_ROOT / "cache"
POOL_ROOT = STORAGE_ROOT / "pool"
POOL_STRATEGIES_ROOT = POOL_ROOT / "strategies"
PORTFOLIOS_ROOT = STORAGE_ROOT / "portfolios"
LIVE_ROOT = STORAGE_ROOT / "live"


def stored_path(value: Any) -> Any:
    """Persist project artifacts relative to the installation; leave external paths explicit."""
    if value is None or str(value) == "":
        return value
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            return str(value)
    return str(value).replace("\\", "/")


def resolved_path(value: Any) -> Any:
    if value is None or str(value) == "":
        return value
    text = str(value).replace("\\", "/")
    if text.startswith("storage/"):
        path = (PROJECT_ROOT / text).resolve()
        path.relative_to(STORAGE_ROOT.resolve())
        return str(path)
    return str(value)


def path_fields(payload: Any, *, storing: bool = False) -> Any:
    """Convert only named artifact path fields, never strategy source or user prose."""
    if isinstance(payload, list):
        return [path_fields(item, storing=storing) for item in payload]
    if not isinstance(payload, dict):
        return payload
    convert = stored_path if storing else resolved_path
    return {
        key: convert(value) if (key == "path" or key.endswith("_path") or key == "resource_root")
        and isinstance(value, (str, Path)) else path_fields(value, storing=storing)
        for key, value in payload.items()
    }

NATURAL_LANGUAGE_ROOT = STORAGE_ROOT / "natural_language"
STRATEGIES_ROOT = STORAGE_ROOT / "strategies"
GENERATED_STRATEGIES_ROOT = STRATEGIES_ROOT / "generated"
VALIDATED_STRATEGIES_ROOT = STRATEGIES_ROOT / "validated"
TEMPLATES_ROOT = STRATEGIES_ROOT / "templates"


REQUIRED_DIRECTORIES = (
    STORAGE_ROOT,
    DB_ROOT,
    RUNTIME_ROOT,
    RUNS_ROOT,
    RESEARCH_ROOT,
    OPTIMIZATION_CURVE_SNAPSHOTS_ROOT,
    CACHE_ROOT,
    POOL_ROOT,
    POOL_STRATEGIES_ROOT,
    PORTFOLIOS_ROOT,
    LIVE_ROOT,
    NATURAL_LANGUAGE_ROOT,
    STRATEGIES_ROOT,
    GENERATED_STRATEGIES_ROOT,
    VALIDATED_STRATEGIES_ROOT,
    TEMPLATES_ROOT,
)


def ensure_directories() -> None:
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()
