from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.core.hashing import compute_sha256
from backend.core.paths import GENERATED_STRATEGIES_ROOT
from backend.domain.enums import ArtifactType
from backend.repositories import artifact_repository, strategy_repository


def _strategy_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"strategy_{stamp}_{uuid4().hex[:6]}"


def register_generated_strategy(strategy_name: str, source_text: str, code: str) -> dict[str, Any]:
    strategy_id = _strategy_id()
    strategy_dir = GENERATED_STRATEGIES_ROOT / strategy_id
    strategy_dir.mkdir(parents=True, exist_ok=False)
    code_path = strategy_dir / "strategy.py"
    code_path.write_text(str(code or ""), encoding="utf-8")
    code_hash = compute_sha256(code_path)

    strategy = strategy_repository.create_strategy(
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        source_type="generated",
        source_text=source_text,
        code_path=str(code_path),
        code_hash=code_hash,
    )
    artifact_repository.create_artifact(
        owner_type="strategy",
        owner_id=strategy_id,
        artifact_type=ArtifactType.STRATEGY_CODE.value,
        path=str(code_path),
        sha256=code_hash,
    )
    return strategy

