from __future__ import annotations

from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = PROJECT_ROOT / "natural_language"


def _resolve_source_file(filename: str) -> Path:
    clean_name = Path(str(filename or "")).name
    if not clean_name or clean_name != filename or not clean_name.endswith(".txt"):
        raise ValueError("invalid natural language source filename")
    path = SOURCE_DIR / clean_name
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"natural language source not found: {clean_name}")
    return path


def list_source_files() -> dict:
    files = []
    if SOURCE_DIR.exists():
        for path in sorted(SOURCE_DIR.glob("*.txt"), key=lambda item: item.name.lower()):
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
    return {
        "source_dir": str(SOURCE_DIR),
        "count": len(files),
        "files": files,
    }


def read_source_file(filename: str) -> dict:
    path = _resolve_source_file(filename)
    stat = path.stat()
    return {
        "name": path.name,
        "text": path.read_text(encoding="utf-8"),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }
