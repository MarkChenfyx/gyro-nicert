from __future__ import annotations

from pathlib import Path
import hashlib


def compute_sha256(path: str | Path) -> str:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Cannot compute sha256, file does not exist: {candidate}")
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()

