from __future__ import annotations

from typing import Any

from backend.strategy_generation.generators.api_strategy_generator import ApiStrategyGenerator


def generate_strategy_from_text(source_text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = dict(options or {})
    return ApiStrategyGenerator().generate(source_text, options=options)

