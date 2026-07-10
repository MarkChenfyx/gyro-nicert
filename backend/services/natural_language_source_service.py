from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = PROJECT_ROOT / "natural_language"


def _clean_source_filename(filename: str, *, append_txt: bool = False) -> str:
    raw_name = str(filename or "").strip()
    clean_name = Path(raw_name).name
    if not clean_name or clean_name != raw_name:
        raise ValueError("invalid natural language source filename")
    if append_txt and not clean_name.endswith(".txt"):
        clean_name = f"{clean_name}.txt"
    if not clean_name.endswith(".txt") or clean_name == ".txt":
        raise ValueError("invalid natural language source filename")
    return clean_name


def clean_source_filename(filename: str, *, append_txt: bool = False) -> str:
    return _clean_source_filename(filename, append_txt=append_txt)


def source_family_from_filename(filename: str) -> str:
    clean_name = _clean_source_filename(filename, append_txt=True)
    family = Path(clean_name).stem.strip()
    family = re.sub(r"\s+", "_", family)
    family = re.sub(r'[<>:"/\\\\|?*]', "_", family)
    family = family.strip(" ._")
    if not family:
        raise ValueError("invalid natural language source filename")
    return family


def _resolve_source_file(filename: str) -> Path:
    clean_name = _clean_source_filename(filename)
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


def create_source_file(filename: str, text: str) -> dict:
    clean_name = _clean_source_filename(filename, append_txt=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCE_DIR / clean_name
    if path.exists():
        raise ValueError(f"natural language source already exists: {clean_name}")
    path.write_text(str(text or ""), encoding="utf-8")
    stat = path.stat()
    return {
        "name": path.name,
        "text": str(text or ""),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def update_source_file(filename: str, text: str) -> dict:
    path = _resolve_source_file(filename)
    path.write_text(str(text or ""), encoding="utf-8")
    stat = path.stat()
    return {
        "name": path.name,
        "text": str(text or ""),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }
