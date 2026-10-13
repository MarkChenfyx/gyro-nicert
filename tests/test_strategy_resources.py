import base64
import importlib
import json
from pathlib import Path

import pytest

from backend.backtesting.strategy_resources import stage_resources, validate_resources


def attachment(value=b"frozen-model"):
    return base64.b64encode(value).decode("ascii")


def test_resources_portable_and_legacy_path(tmp_path):
    files = json.loads(json.dumps({"m.model": attachment()}))
    code = "open('strategies/m.model', 'rb')"
    hashes = validate_resources(files, code)
    stage_resources(tmp_path, files, code)
    assert (tmp_path / "strategies/m.model").read_bytes() == b"frozen-model"
    assert (tmp_path / "m.model").read_bytes() == b"frozen-model"
    assert len(hashes["m.model"]) == 64


@pytest.mark.parametrize("name", ["../a.model", "/a.model", "C:/a.model", "a\\b.model", "a.py"])
def test_invalid_paths(name):
    with pytest.raises(ValueError):
        validate_resources({name: attachment()}, "pass")


def test_missing_and_invalid_resources():
    with pytest.raises(ValueError, match="缺少模型"):
        validate_resources({}, "open('strategies/m.model', 'rb')")
    with pytest.raises(ValueError):
        validate_resources({"m.model": "%%%"}, "pass")
    assert validate_resources({}, "class Plain: pass") == {}


def test_backtest_stages_and_cleans_resources(monkeypatch):
    runner = importlib.import_module("backend.backtesting.run")
    roots = []
    def fake(code, cls, symbol, parameters, config):
        root = Path(config["resource_root"])
        roots.append(root)
        with runner._resource_dir(root):
            assert Path("strategies/m.model").read_bytes() == b"frozen-model"
        return {"success": True}
    monkeypatch.setattr(runner, "_real_backtest", fake)
    result = runner.run_backtest("open('strategies/m.model','rb')", "Test", "513120.SSE", {},
                                {"model_files": {"m.model": attachment()}})
    assert result["success"]
    assert not roots[0].exists()


def test_fixed_model_inventory_blocks_feature_parameters(tmp_path, monkeypatch):
    from backend.services import optimization_service as service
    (tmp_path / "strategy.py").write_text('''class Kbins_Test:
    long_label = 0
    holding_window = 12
    mfi_window = 47
    parameters = ["long_label", "holding_window", "mfi_window"]
''', encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"model_files": {"m.model": attachment()}}))
    monkeypatch.setattr(service.run_repository, "get_run", lambda _: {"runtime_path": str(tmp_path), "strategy_id": "test"})
    monkeypatch.setattr(service.strategy_repository, "get_strategy", lambda _: {})
    space = service.get_search_space("test")
    assert {x["name"] for x in space["parameters"]} == {"long_label", "holding_window"}
    with pytest.raises(ValueError):
        service._resolve_base_parameters(space, {"mfi_window": 20})
    with pytest.raises(ValueError):
        service._validate_selected_parameters(space, ["mfi_window"], {"mfi_window": {}})
