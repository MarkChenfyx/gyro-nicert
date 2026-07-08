from __future__ import annotations

import json
import pytest

from strategy_generation.generators.api_strategy_generator import ApiStrategyGenerator
from strategy_generation import providers


VALID_CODE = """from __future__ import annotations
from vnpy_ctastrategy import CtaTemplate


class ApiMaStrategy(CtaTemplate):
    author = "test"
    fixed_size = 1
    parameters = ["fixed_size"]
    variables = []

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

    def on_init(self):
        pass

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_tick(self, tick):
        pass

    def on_bar(self, bar):
        self.put_event()
"""


class FakeProvider:
    def __init__(self, content: str | Exception):
        self.content = content

    def complete(self, messages):
        assert messages[0]["role"] == "system"
        assert "{USER_REQUEST}" not in messages[0]["content"]
        assert "{PROJECT_RULES}" not in messages[0]["content"]
        assert "{EXAMPLES}" not in messages[0]["content"]
        if isinstance(self.content, Exception):
            raise self.content
        return self.content


def patch_provider(monkeypatch, content: str | Exception) -> None:
    monkeypatch.setattr(providers, "build_provider", lambda options=None: FakeProvider(content))
    import strategy_generation.generators.api_strategy_generator as api_module

    monkeypatch.setattr(api_module, "build_provider", lambda options=None: FakeProvider(content))


def test_api_strategy_generator_success(monkeypatch) -> None:
    code_json = json.dumps(VALID_CODE)
    patch_provider(
        monkeypatch,
        f"""{{
  "success": true,
  "strategy_name": "API MA Strategy",
  "class_name": "ApiMaStrategy",
  "strategy_code": {code_json},
  "parameters": {{"fixed_size": {{"default": 1, "description": "fixed order size"}}}},
  "description": "test strategy",
  "strategy_type": "trend_following",
  "diagnostics": [{{"stage": "model", "level": "info", "message": "ok"}}],
  "error": null
}}""",
    )

    result = ApiStrategyGenerator().generate("moving average strategy")

    assert result["success"] is True
    assert result["strategy_name"] == "API MA Strategy"
    assert result["class_name"] == "ApiMaStrategy"
    assert "class ApiMaStrategy" in result["strategy_code"]
    assert result["params"]["fixed_size"] == 1
    assert result["spec"]["strategy_type"] == "trend_following"
    assert result["generator_name"] == "api_strategy_generator"


def test_api_strategy_generator_reports_non_json_response(monkeypatch) -> None:
    patch_provider(monkeypatch, "not json")

    result = ApiStrategyGenerator().generate("moving average strategy")

    assert result["success"] is False
    assert "Expecting value" in result["error"]
    assert result["strategy_code"] is None


def test_api_strategy_generator_reports_syntax_error(monkeypatch) -> None:
    patch_provider(
        monkeypatch,
        """{
  "success": true,
  "strategy_name": "Bad",
  "class_name": "BadStrategy",
  "strategy_code": "class BadStrategy(:\\n    pass",
  "params": {},
  "spec": {},
  "diagnostics": [],
  "error": null
}""",
    )

    result = ApiStrategyGenerator().generate("bad strategy")

    assert result["success"] is False
    assert "syntax error" in result["error"]


def test_api_strategy_generator_reports_provider_error(monkeypatch) -> None:
    patch_provider(monkeypatch, TimeoutError("provider timeout"))

    result = ApiStrategyGenerator().generate("moving average strategy")

    assert result["success"] is False
    assert result["error"] == "provider timeout"


def test_provider_config_supports_named_providers(monkeypatch) -> None:
    monkeypatch.setattr(providers, "load_local_env", lambda: None)
    monkeypatch.setenv("GYRO_LLM_API_KEY", "test-key")
    monkeypatch.setenv("GYRO_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("GYRO_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GYRO_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = providers.LlmConfig.from_options()

    assert config.provider == "deepseek"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.model == "deepseek-chat"


def test_provider_config_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        providers.LlmConfig.from_options({"provider": "unknown"})
