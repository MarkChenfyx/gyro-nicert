from __future__ import annotations

from typing import Any

from strategy_generation.generators.legacy_agent_generator import LegacyAgentGenerator


def generate_strategy_from_text(source_text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    generator = LegacyAgentGenerator()
    return generator.generate(source_text, options=options)
