from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import base64
import json
import sqlite3
import zipfile

import pytest

from backend.backtesting.replay_worker import _state_injector
from backend.data_manager import database
from backend.services import live_service
from scripts.init_db import APP_SCHEMA


PACKAGE_SOURCE = (
    "from vnpy_ctastrategy import CtaTemplate\n"
    "class DemoStrategy(CtaTemplate):\n"
    "    parameters = ['fixed_size']\n"
    "    variables = ['pos']\n"
    "    fixed_size = 500\n"
)


def _package() -> str:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("strategies/demo.py", PACKAGE_SOURCE)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _settings(fixed_size: int = 500) -> dict:
    return {
        "demo_live": {
            "class_name": "DemoStrategy",
            "vt_symbol": "511380.SSE",
            "setting": {"fixed_size": fixed_size, "window": 10},
        }
    }


def _configure(tmp_path: Path, monkeypatch) -> None:
    app_db = tmp_path / "app.sqlite"
    with sqlite3.connect(app_db) as connection:
        connection.executescript(APP_SCHEMA)
    monkeypatch.setattr(database, "APP_DB_PATH", app_db)
    # 一并改写 STORAGE_ROOT，让产物路径真的走"相对存库"这条分支。
    monkeypatch.setattr(live_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(live_service, "LIVE_ROOT", tmp_path / "live")


def _import(tmp_path: Path, monkeypatch) -> str:
    _configure(tmp_path, monkeypatch)
    detail = live_service.import_source({
        "trade_date": "2026-09-02",
        "name": "实盘组合",
        "source_kind": "package",
        "package_base64": _package(),
        "settings": _settings(),
        "states": {"demo_live": {"pos": 500}},
    })
    return str(detail["source"]["source_id"])


def _stub_market_data(monkeypatch, failures: dict | None = None) -> None:
    monkeypatch.setattr(live_service, "_ensure_market_data", lambda *_a, **_k: dict(failures or {}))


def test_import_registers_bindings_and_leaves_pool_untouched(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    detail = live_service.get_source_detail(source_id)

    assert detail["source"]["instance_count"] == 1
    binding = detail["bindings"][0]
    assert binding["instance_name"] == "demo_live"
    # 实盘手数原样保留，不做 fixed_size 归一化。
    assert binding["fixed_size"] == 500
    assert len(detail["snapshots"]) == 1

    with sqlite3.connect(database.APP_DB_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pool_items").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM virtual_portfolios").fetchone()[0] == 0


def test_local_dir_source_reads_configured_directory(tmp_path, monkeypatch):
    """本机模式从 .env 指定的目录读取，不需要上传任何文件。"""
    _configure(tmp_path, monkeypatch)
    deployment = tmp_path / "vnpy_home"
    (deployment / "strategies").mkdir(parents=True)
    (deployment / "strategies" / "demo.py").write_text(PACKAGE_SOURCE, encoding="utf-8")
    config_dir = deployment / live_service.VNPY_CONFIG_DIRNAME
    config_dir.mkdir()
    (config_dir / live_service.SETTING_FILENAME).write_text(
        json.dumps(_settings()), encoding="utf-8")
    (config_dir / live_service.STATE_FILENAME).write_text(
        json.dumps({"demo_live": {"pos": 500}}), encoding="utf-8")
    monkeypatch.setenv(live_service.LIVE_SOURCE_DIR_ENV, str(deployment))

    status = live_service.local_source_status()
    assert status["available"] is True and status["instance_count"] == 1

    import os
    from datetime import timezone, timedelta
    stamp = datetime(2026, 9, 2, 16, tzinfo=timezone(timedelta(hours=8))).timestamp()
    os.utime(config_dir / live_service.STATE_FILENAME, (stamp, stamp))
    detail = live_service.import_source({"trade_date": "2026-09-02"})
    source = detail["source"]
    assert source["source_kind"] == "local_dir"
    # 库里不留绝对路径，换机器只需改 .env。
    assert source["package_path"] == ""
    assert detail["bindings"][0]["instance_name"] == "demo_live"


def test_local_source_supports_separate_strategy_and_vntrader_dirs(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    strategy_dir = tmp_path / "runtime" / "strategies"
    strategy_dir.mkdir(parents=True)
    (strategy_dir / "demo.py").write_text(PACKAGE_SOURCE, encoding="utf-8")
    vntrader_dir = tmp_path / "user_home" / ".vntrader"
    vntrader_dir.mkdir(parents=True)
    (vntrader_dir / live_service.SETTING_FILENAME).write_text(
        json.dumps(_settings()), encoding="utf-8")
    state_path = vntrader_dir / live_service.STATE_FILENAME
    state_path.write_text(json.dumps({"demo_live": {"pos": 500}}), encoding="utf-8")

    import os
    from datetime import timezone, timedelta
    # vn.py 在 15:05 写出的当日状态已经属于收盘后有效状态。
    stamp = datetime(2026, 9, 2, 15, 5, tzinfo=timezone(timedelta(hours=8))).timestamp()
    os.utime(state_path, (stamp, stamp))
    monkeypatch.setenv(live_service.LIVE_SOURCE_DIR_ENV, "")
    monkeypatch.setenv(live_service.LIVE_STRATEGY_DIR_ENV, str(strategy_dir))
    monkeypatch.setenv(live_service.LIVE_VNTRADER_DIR_ENV, str(vntrader_dir))

    status = live_service.local_source_status()
    assert status["available"] is True and status["strategy_dir_exists"] is True
    detail = live_service.import_source({"trade_date": "2026-09-02"})
    assert detail["bindings"][0]["instance_name"] == "demo_live"


def test_local_dir_source_requires_configuration(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv(live_service.LIVE_SOURCE_DIR_ENV, "")
    with pytest.raises(ValueError, match=live_service.LIVE_SOURCE_DIR_ENV):
        live_service.import_source({"trade_date": "2026-09-02"})


def test_artifact_paths_are_stored_relative_to_storage(tmp_path, monkeypatch):
    """库里不存绝对路径，换部署目录不需要迁移数据。"""
    source_id = _import(tmp_path, monkeypatch)
    detail = live_service.get_source_detail(source_id)
    stored = detail["snapshots"][0]["artifact_path"]
    assert not Path(stored).is_absolute(), stored
    assert stored.startswith("live/")


def test_delete_source_removes_only_its_own_records(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    live_service.delete_source(source_id)
    assert live_service.list_sources() == []
    with pytest.raises(FileNotFoundError):
        live_service.get_source_detail(source_id)


def test_track_requires_a_prior_snapshot(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    _stub_market_data(monkeypatch)
    # 最早的一份快照只能当起点，本身不能被跟踪。
    with pytest.raises(FileNotFoundError, match="最早的一份"):
        live_service.track_day(source_id, "2026-09-02")


def test_track_compares_replay_position_against_live(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": _settings(),
        "states": {"demo_live": {"pos": 0}},
    })
    _stub_market_data(monkeypatch)
    monkeypatch.setattr(live_service, "_run_replay", lambda *_a, **_k: {
        "success": True, "end_pos": 500.0, "trades": [], "end_variables": {"pos": 500.0},
    })

    record = live_service.track_day(source_id, "2026-09-03")
    row = record["rows"][0]
    assert row["status"] == "MISMATCH"
    assert row["actual_pos"] == 0
    assert row["replay_pos"] == 500.0
    # 差异与实盘同量纲，不做份数换算。
    assert row["difference"] == -500.0
    assert record["summary"]["prior_date"] == "2026-09-02"


def test_identical_state_snapshots_are_allowed(tmp_path, monkeypatch):
    """两天读到同一份状态文件时，比对目标就是起点自己，必须拒绝而不是给出假差异。"""
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": _settings(),
        "states": {"demo_live": {"pos": 500}},   # 与起点完全相同
    })
    _stub_market_data(monkeypatch)
    monkeypatch.setattr(live_service, "_run_replay", lambda *_a, **_k: {"success": True, "end_pos": 500})
    assert live_service.track_day(source_id, "2026-09-03")["rows"][0]["status"] == "MATCH"


def test_missing_market_data_reports_data_gap_not_mismatch(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": _settings(),
        "states": {"demo_live": {"pos": 0}},
    })
    _stub_market_data(monkeypatch, {"511380.SSE": "一分钟行情不完整"})

    def _fail(*_a, **_k):
        raise AssertionError("行情不完整时不应触发回放")

    monkeypatch.setattr(live_service, "_run_replay", _fail)
    row = live_service.track_day(source_id, "2026-09-03")["rows"][0]
    assert row["status"] == "DATA_GAP"
    assert row["replay_pos"] is None


def test_replay_without_bars_is_a_data_gap_not_a_failure(tmp_path, monkeypatch):
    """回放区间没有行情属于数据缺口，不该报成策略回放故障。"""
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": _settings(),
        "states": {"demo_live": {"pos": 0}},
    })
    _stub_market_data(monkeypatch)
    monkeypatch.setattr(live_service, "_run_replay", lambda *_a, **_k: {
        "success": False, "reason": "no_bars", "error": "没有一分钟行情",
    })
    row = live_service.track_day(source_id, "2026-09-03")["rows"][0]
    assert row["status"] == "DATA_GAP"


def test_market_data_window_starts_from_replay_start(tmp_path, monkeypatch):
    """预热窗口以回放起始日为基准；起点与目标相隔越久，需要的行情越早。"""
    monkeypatch.setattr(live_service, "now_beijing", lambda: datetime(2026, 10, 21, 16))
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-10-20",
        "settings": _settings(),
        "states": {"demo_live": {"pos": 0}},
    })
    seen: dict = {}

    def _capture(bindings, replay_start, trade_date, update):
        seen["replay_start"] = replay_start
        seen["trade_date"] = trade_date
        return {}

    monkeypatch.setattr(live_service, "_ensure_market_data", _capture)
    monkeypatch.setattr(live_service, "_run_replay", lambda *_a, **_k: {
        "success": True, "end_pos": 0.0, "trades": [], "end_variables": {},
    })
    live_service.track_day(source_id, "2026-10-20")
    # 起点快照是 2026-09-02，回放从次日开始，而不是从目标日开始。
    assert seen["replay_start"] == "2026-09-03"
    assert seen["trade_date"] == "2026-10-20"


def test_instance_added_in_live_is_reported_not_ignored(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    settings = {**_settings(), "added_live": {
        "class_name": "DemoStrategy", "vt_symbol": "510300.SSE", "setting": {"fixed_size": 100},
    }}
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": settings,
        "states": {"demo_live": {"pos": 500}, "added_live": {"pos": 100}},
    })
    _stub_market_data(monkeypatch)
    monkeypatch.setattr(live_service, "_run_replay", lambda *_a, **_k: {
        "success": True, "end_pos": 500.0, "trades": [], "end_variables": {},
    })

    rows = {row["instance_name"]: row for row in live_service.track_day(source_id, "2026-09-03")["rows"]}
    assert rows["demo_live"]["status"] == "MATCH"
    assert rows["added_live"]["status"] == "NEW_INSTANCE"


def test_changed_live_config_is_flagged(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": _settings(fixed_size=1000),
        "states": {"demo_live": {"pos": 1000}},
    })
    _stub_market_data(monkeypatch)
    row = live_service.track_day(source_id, "2026-09-03")["rows"][0]
    assert row["status"] == "CONFIG_CHANGED"


def test_state_injector_skips_parameters_and_engine_flags():
    class Strategy:
        parameters = ["fixed_size"]
        fixed_size = 500
        pos = 0
        inited = False
        intra_trade_high = 0.0

    strategy = Strategy()
    applied: list[str] = []
    skipped: list[str] = []
    _state_injector(
        {"pos": 300, "intra_trade_high": 9.02, "fixed_size": 1, "inited": True, "unknown": 1},
        applied, skipped,
    )(strategy)

    assert strategy.pos == 300 and strategy.intra_trade_high == 9.02
    # 参数由实盘配置决定，存档状态不得改写它们；引擎标志同理。
    assert strategy.fixed_size == 500 and strategy.inited is False
    assert set(applied) == {"pos", "intra_trade_high"}
    assert set(skipped) == {"fixed_size", "inited", "unknown"}


def test_state_injection_happens_after_warmup_overwrites_variables():
    """预热会重算策略变量，注入必须发生在预热之后、开始交易之前。"""
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData
    from vnpy_ctastrategy import CtaTemplate
    from vnpy_ctastrategy.base import BacktestingMode

    from backend.backtesting.cta_engine import BacktestingEngine

    class WarmupProbe(CtaTemplate):
        parameters: list = []
        variables = ["pos", "marker"]
        marker = 0

        def on_init(self) -> None:
            self.marker = 1  # 模拟预热过程改写变量
            self.marker_after_init = self.marker

        def on_start(self) -> None:
            self.marker_at_trading = self.marker

        def on_bar(self, bar) -> None:
            pass

    start = datetime(2026, 9, 3, 0, 0, 0)
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="511380.SSE", interval=Interval.MINUTE, start=start,
        end=datetime(2026, 9, 3, 23, 59, 59), rate=0.0, slippage=0.0,
        size=1, pricetick=0.001, capital=100000, mode=BacktestingMode.BAR,
    )
    engine.add_strategy(WarmupProbe, {})
    engine.history_data = [BarData(
        gateway_name="TEST", symbol="511380", exchange=Exchange.SSE,
        datetime=datetime(2026, 9, 3, 9, 30), interval=Interval.MINUTE,
        open_price=105.0, high_price=105.3, low_price=104.9, close_price=105.2, volume=1000,
    )]
    engine.run_backtesting(on_ready=lambda strategy: setattr(strategy, "marker", 99))

    assert engine.strategy.marker_after_init == 1, "预热确实会改写变量"
    assert engine.strategy.marker_at_trading == 99, "注入的实盘状态被预热覆盖了"


def test_run_backtesting_without_hook_is_unchanged():
    """不传 on_ready 时行为与原来完全一致，现有回测链路不受影响。"""
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData
    from vnpy_ctastrategy import CtaTemplate
    from vnpy_ctastrategy.base import BacktestingMode

    from backend.backtesting.cta_engine import BacktestingEngine

    class Plain(CtaTemplate):
        parameters: list = []
        variables = ["pos"]

        def on_init(self) -> None:
            self.seen = 0

        def on_bar(self, bar) -> None:
            self.seen += 1

    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="511380.SSE", interval=Interval.MINUTE,
        start=datetime(2026, 9, 3, 0, 0, 0), end=datetime(2026, 9, 3, 23, 59, 59),
        rate=0.0, slippage=0.0, size=1, pricetick=0.001, capital=100000, mode=BacktestingMode.BAR,
    )
    engine.add_strategy(Plain, {})
    engine.history_data = [BarData(
        gateway_name="TEST", symbol="511380", exchange=Exchange.SSE,
        datetime=datetime(2026, 9, 3, 9, 30 + offset), interval=Interval.MINUTE,
        open_price=105.0, high_price=105.3, low_price=104.9, close_price=105.2, volume=10,
    ) for offset in range(3)]
    engine.run_backtesting()

    assert engine.strategy.seen == 3
    assert engine.strategy.trading is True


def test_capture_before_close_leaves_no_snapshot(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    monkeypatch.setattr(live_service, "now_beijing", lambda: datetime(2026, 9, 3, 10))
    with pytest.raises(ValueError, match="尚未收盘"):
        live_service.import_snapshot(source_id, {"trade_date": "2026-09-03", "settings": _settings(), "states": {}})
    assert len(live_service.get_source_detail(source_id)["snapshots"]) == 1


@pytest.mark.parametrize("state", [{}, {"pos": None}, {"pos": "bad"}, {"pos": float("nan")}])
def test_invalid_position_never_matches(tmp_path, monkeypatch, state):
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {"trade_date": "2026-09-03", "settings": _settings(), "states": {"demo_live": state}})
    _stub_market_data(monkeypatch)
    monkeypatch.setattr(live_service, "_run_replay", lambda *a: pytest.fail("invalid state must not replay"))
    assert live_service.track_day(source_id, "2026-09-03")["rows"][0]["status"] == "NO_STATE"


def test_changed_code_replays_with_warning(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    root = live_service.package_root_for(live_service.live_repository.get_source(source_id))
    (root / "strategies" / "demo.py").write_text(PACKAGE_SOURCE + "\n# changed", encoding="utf-8")
    live_service.import_snapshot(source_id, {"trade_date": "2026-09-03", "settings": _settings(), "states": {"demo_live": {"pos": 500}}})
    _stub_market_data(monkeypatch)
    calls = []
    def replay(binding, source, *args):
        calls.append(source)
        return {"success": True, "end_pos": 300, "trades": [{"datetime": "2026-09-03T10:00:00"}]}
    monkeypatch.setattr(live_service, "_run_replay", replay)
    record = live_service.track_day(source_id, "2026-09-03")
    row = record["rows"][0]
    assert len(calls) == 1
    assert row["status"] == "CONFIG_CHANGED"
    assert row["version_changed"] is True
    assert row["replay_pos"] == 300
    assert row["difference"] == 200
    assert len(row["replay_trades"]) == 1
    assert "终点快照" in row["message"]
    assert record["summary"]["unresolved"] == 1


def test_other_strategy_code_change_does_not_block_replay(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    root = live_service.package_root_for(live_service.live_repository.get_source(source_id))
    (root / "strategies" / "other.py").write_text("class OtherStrategy: pass\n", encoding="utf-8")
    live_service.import_snapshot(source_id, {
        "trade_date": "2026-09-03",
        "settings": _settings(),
        "states": {"demo_live": {"pos": 500}},
    })
    _stub_market_data(monkeypatch)
    monkeypatch.setattr(live_service, "_run_replay", lambda *_a, **_k: {
        "success": True, "end_pos": 500.0, "trades": [], "end_variables": {},
    })

    assert live_service.track_day(source_id, "2026-09-03")["rows"][0]["status"] == "MATCH"


def test_strategy_code_check_includes_referenced_model(tmp_path):
    code_root = tmp_path / "code" / "strategies"
    code_root.mkdir(parents=True)
    (code_root / "demo.py").write_text(
        PACKAGE_SOURCE + '\nMODEL = "strategies/demo.model"\n', encoding="utf-8"
    )
    binding = {"module_path": "strategies/demo.py"}
    prior = {"code_hashes": {"strategies/demo.py": "same", "strategies/demo.model": "old"}}
    current = {"code_hashes": {"strategies/demo.py": "same", "strategies/demo.model": "changed"}}

    assert live_service._binding_code_hashes(binding, prior, tmp_path) != \
        live_service._binding_code_hashes(binding, current, tmp_path)


def test_replay_stages_flat_snapshot_models_at_strategy_relative_path(tmp_path, monkeypatch):
    package = tmp_path / "code"
    package.mkdir()
    (package / "probe.py").write_text('MODEL = "strategies/probe.model"', encoding="utf-8")
    (package / "probe.model").write_bytes(b"model snapshot")
    observed = {}

    def fake_run(command, **kwargs):
        request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
        resource_root = Path(request["resource_root"])
        observed["cwd"] = Path(kwargs["cwd"])
        observed["model"] = (resource_root / "strategies" / "probe.model").read_bytes()
        Path(command[-1]).write_text(json.dumps({"success": True, "end_pos": 0}), encoding="utf-8")
        return type("Completed", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(live_service.subprocess, "run", fake_run)
    result = live_service._run_replay(
        {"module_path": "probe.py", "class_name": "Probe", "vt_symbol": "511380.SSE", "parameters": {}},
        {"source_kind": "package", "package_path": str(package)},
        "2026-09-03", "2026-09-03", {"pos": 0},
    )
    assert result["success"] is True
    assert observed["model"] == b"model snapshot"
    assert observed["cwd"].name == "resources"


def test_minute_gap_and_missing_target_day_are_detected():
    from datetime import date, timedelta
    from types import SimpleNamespace
    from backend.backtesting.replay_worker import replay_data_issue
    day = date(2026, 9, 3)
    bars = [SimpleNamespace(datetime=datetime(2026, 9, 3, hour, minute) + timedelta(minutes=i))
            for hour, minute in [(9, 30), (13, 0)] for i in range(120)]
    assert replay_data_issue(bars, day, day, "SSE") == ""
    assert replay_data_issue(bars[:-1], day, day, "SSE")
    assert replay_data_issue(bars, day, date(2026, 9, 4), "SSE")


def test_worker_restores_state_after_on_start(tmp_path, monkeypatch):
    from backend.backtesting import replay_worker, local_data_provider
    from vnpy_ctastrategy import CtaTemplate
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData

    class Probe(CtaTemplate):
        marker = 0
        variables = ["marker"]
        def on_init(self):
            with open("strategies/probe.model", "rb") as model:
                assert model.read() == b"snapshot model"
        def on_start(self):
            self.marker = 1
            self.pos = 0
        def on_bar(self, bar):
            pass

    (tmp_path / "strategy.py").write_text("# isolated probe", encoding="utf-8")
    resource_root = tmp_path / "resources"
    (resource_root / "strategies").mkdir(parents=True)
    (resource_root / "strategies" / "probe.model").write_bytes(b"snapshot model")
    bar = BarData(gateway_name="TEST", symbol="511380", exchange=Exchange.SSE,
                  datetime=datetime(2026, 9, 3, 9, 30), interval=Interval.MINUTE,
                  open_price=100, high_price=100, low_price=100, close_price=100)
    monkeypatch.setattr(local_data_provider, "load_bar_data", lambda *a: [bar])
    monkeypatch.setattr(replay_worker, "replay_data_issue", lambda *a: "")
    monkeypatch.setattr(replay_worker, "_load_class", lambda *a: Probe)
    result = replay_worker.run({"package_root": str(tmp_path), "resource_root": str(resource_root), "module_path": "strategy.py",
                                "class_name": "Probe", "vt_symbol": "511380.SSE",
                                "end_date": "2026-09-03", "prior_state": {"pos": 500, "marker": 99}})
    assert result["end_pos"] == 500
    assert result["end_variables"]["marker"] == 99
    assert result["state_unrestored"] == []


def test_saved_trace_is_read_without_replay(tmp_path, monkeypatch):
    source_id = _import(tmp_path, monkeypatch)
    live_service.import_snapshot(source_id, {"trade_date": "2026-09-03", "settings": _settings(), "states": {"demo_live": {"pos": 500}}})
    _stub_market_data(monkeypatch)
    signal = {"signal_id": "signal_1", "variables": {"threshold": 99}}
    monkeypatch.setattr(live_service, "_run_replay", lambda *a: {
        "success": True, "end_pos": 500, "trace_version": 1,
        "trades": [{"tradeid": "1", "datetime": "2026-09-03T10:00:00", "signal_id": "signal_1"},
                   {"tradeid": "2", "datetime": "2026-09-02T10:00:00"}],
        "orders": [{"order_id": "order_1", "signal_id": "signal_1"}], "signals": [signal],
    })
    live_service.track_day(source_id, "2026-09-03")
    monkeypatch.setattr(live_service, "_run_replay", lambda *a: pytest.fail("Reading must not replay"))
    saved = live_service.get_daily_record(source_id, "2026-09-03")
    assert saved["summary"]["day_trade_count"] == 1
    assert saved["summary"]["trade_count"] == 2
    assert saved["rows"][0]["replay_signals"] == [signal]
    assert saved["rows"][0]["replay_orders"][0]["signal_id"] == "signal_1"
