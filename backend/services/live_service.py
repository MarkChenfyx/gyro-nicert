"""实盘跟踪。

每天记录一组实盘 CTA 策略发生了什么，并用一次独立的单日回放作为参照物：
以前一交易日收盘的真实状态为起点重放当天，得到"本来应该持有多少"，
再与当天实盘的真实持仓比较。持仓差异是其中一项输出，当日成交明细同样保留，
用来判断差异是信号算错了还是成交环节出了问题。

本模块自成一体：不写策略池，不建虚拟组合，不与研究链路共享产物。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
import ast
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from backend.backtesting.local_data_provider import split_vt_symbol
from backend.backtesting.replay_worker import WARMUP_DAYS
from backend.common.time_utils import now_beijing, now_iso, timestamp_id
from backend.core.environment import env
from backend.core.paths import LIVE_ROOT, PROJECT_ROOT, STORAGE_ROOT, stored_path, resolved_path
from backend.data_manager import coverage_service, download_service
from backend.repositories import live_repository


SOURCE_KIND_LOCAL = "local_dir"
SOURCE_KIND_PACKAGE = "package"

# vn.py 实盘部署目录按机器配置在 .env，代码与数据库里都不出现绝对路径。
LIVE_SOURCE_DIR_ENV = "GYRO_LIVE_SOURCE_DIR"
LIVE_STRATEGY_DIR_ENV = "GYRO_LIVE_STRATEGY_DIR"
LIVE_VNTRADER_DIR_ENV = "GYRO_LIVE_VNTRADER_DIR"
VNPY_CONFIG_DIRNAME = ".vntrader"
SETTING_FILENAME = "cta_strategy_setting.json"
STATE_FILENAME = "cta_strategy_data.json"

BEIJING_TZ = timezone(timedelta(hours=8))

MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_INSTANCES = 100
REPLAY_TIMEOUT_SECONDS = 600
MARKET_CLOSE = time(15, 10)
STATE_FILE_CLOSE = time(15, 0)

STATUS_MATCH = "MATCH"
STATUS_MISMATCH = "MISMATCH"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_CONFIG_CHANGED = "CONFIG_CHANGED"
STATUS_NO_STATE = "NO_STATE"
STATUS_NEW_INSTANCE = "NEW_INSTANCE"
STATUS_REPLAY_ERROR = "REPLAY_ERROR"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _validated_date(value: Any) -> str:
    text = _text(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"交易日期无效：{text}") from exc


def _check_capture_date(trade_date: str, *, local: bool = False) -> None:
    now = now_beijing()
    if trade_date > now.date().isoformat():
        raise ValueError("不能记录未来日期的实盘状态")
    if trade_date == now.date().isoformat() and now.time() < MARKET_CLOSE:
        raise ValueError("当日尚未收盘，请在北京时间 15:10 之后记录快照")
    if local:
        state_path = local_vntrader_dir() / STATE_FILENAME
        modified = datetime.fromtimestamp(state_path.stat().st_mtime, BEIJING_TZ)
        if modified.date().isoformat() != trade_date or modified.time() < STATE_FILE_CLOSE:
            raise ValueError("状态文件修改时间不对应所选交易日收盘后；请确认文件已更新和服务器时钟正确")


def _valid_position(state: Any) -> bool:
    if not isinstance(state, dict) or isinstance(state.get("pos"), bool):
        return False
    try:
        number = float(state["pos"])
        return number == number and abs(number) != float("inf")
    except (KeyError, TypeError, ValueError):
        return False


def _capture_code(source_id: str, destination: Path) -> dict[str, str]:
    source = live_repository.get_source(source_id)
    root = package_root_for(source)
    candidates = list((root / "strategies").rglob("*")) if (root / "strategies").is_dir() else []
    candidates += list(root.glob("*"))
    hashes = {}
    for path in sorted(set(candidates)):
        if not path.is_file() or path.suffix.lower() not in {".py", ".model", ".pkl", ".pickle", ".joblib", ".npy"}:
            continue
        path.resolve().relative_to(root.resolve())
        relative = path.relative_to(root)
        content = path.read_bytes()
        target = destination / "code" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
    return hashes


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _slug(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if str(key) not in fields:
                fields.append(str(key))
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            if fields:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in fields} for row in rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _stored_path(path: Path) -> str:
    """产物路径按 storage/ 相对存库，换机器或换部署目录不需要迁移数据。

    产物落在 storage/ 之外时（例如测试用的临时目录）退回绝对路径，读取端两种都认。
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(STORAGE_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _artifact_path(stored: Any) -> Path:
    text = _text(stored)
    if not text:
        raise FileNotFoundError("产物路径为空")
    candidate = Path(text)
    return candidate if candidate.is_absolute() else STORAGE_ROOT / candidate


# ---------------------------------------------------------------- 本机实盘目录


def _configured_dir(name: str) -> Path | None:
    configured = _text(env(name, ""))
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_dir():
        raise ValueError(f"{name} 指向的目录不存在：{path}")
    return path.resolve()


def local_source_dir() -> Path:
    """返回旧版单根目录配置，供兼容已有部署使用。"""
    configured = _text(env(LIVE_SOURCE_DIR_ENV, ""))
    if not configured:
        raise ValueError(
            f"未配置 {LIVE_STRATEGY_DIR_ENV} 和 {LIVE_VNTRADER_DIR_ENV}；"
            f"也未提供兼容配置 {LIVE_SOURCE_DIR_ENV}"
        )
    path = Path(configured).expanduser()
    if not path.is_dir():
        raise ValueError(f"{LIVE_SOURCE_DIR_ENV} 指向的目录不存在：{path}")
    return path.resolve()


def local_strategy_dir() -> Path:
    """返回策略源码目录；未单独配置时兼容旧版根目录/strategies。"""
    configured = _configured_dir(LIVE_STRATEGY_DIR_ENV)
    return configured if configured is not None else local_source_dir() / "strategies"


def local_vntrader_dir() -> Path:
    """返回包含 CTA 配置和状态文件的 .vntrader 目录。"""
    configured = _configured_dir(LIVE_VNTRADER_DIR_ENV)
    return configured if configured is not None else local_source_dir() / VNPY_CONFIG_DIRNAME


def read_local_live_files() -> tuple[dict[str, Any], dict[str, Any]]:
    """读取实盘当前的策略配置与策略状态。"""
    config_dir = local_vntrader_dir()
    setting_path = config_dir / SETTING_FILENAME
    state_path = config_dir / STATE_FILENAME
    for path in (setting_path, state_path):
        if not path.is_file():
            raise FileNotFoundError(f"未找到实盘配置文件：{path.name}（应位于 {config_dir}）")
    return (
        json.loads(setting_path.read_text(encoding="utf-8")),
        json.loads(state_path.read_text(encoding="utf-8")),
    )


def package_root_for(source: dict[str, Any]) -> Path:
    """本机模式每次从环境变量重新解析，因此换机器不需要改库。"""
    if _text(source.get("source_kind")) == SOURCE_KIND_LOCAL:
        return local_strategy_dir()
    path = Path(resolved_path(_text(source.get("package_path"))))
    if not path.is_dir():
        raise FileNotFoundError(f"策略包目录不存在：{path}")
    return path


def local_source_status() -> dict[str, Any]:
    """给前端用：本机实盘目录是否可用、当前有多少启用策略、状态文件多新。"""
    try:
        strategy_dir = local_strategy_dir()
        config_dir = local_vntrader_dir()
    except ValueError as exc:
        return {"available": False, "message": str(exc)}
    state_path = config_dir / STATE_FILENAME
    try:
        settings, states = read_local_live_files()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {"available": False, "message": str(exc)}
    # 同一份状态文件重复导入没有意义，先告诉前端它是否已经被记录过。
    state_hash = _hash_json(states)
    recorded = live_repository.find_snapshot_by_state_hash(state_hash)
    return {
        "available": True,
        "strategy_dir_exists": strategy_dir.is_dir(),
        "instance_count": len(settings),
        "state_count": len(states),
        # 交易日以北京时间为准；按本机时区显示会让人判断错日期。
        "state_modified_at": datetime.fromtimestamp(
            state_path.stat().st_mtime, BEIJING_TZ
        ).isoformat(timespec="seconds"),
        "state_hash": state_hash[:12],
        # 状态文件写于收盘后，其北京日期就是它代表的交易日，用作页面默认值。
        "state_trade_date": datetime.fromtimestamp(state_path.stat().st_mtime, BEIJING_TZ).date().isoformat(),
        "recorded_as": _text((recorded or {}).get("trade_date")),
        "message": "",
    }


# ---------------------------------------------------------------- 策略包


def _decode_package(value: str) -> bytes:
    encoded = _text(value)
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("策略包不是有效的 Base64 ZIP") from exc
    if not raw or len(raw) > MAX_PACKAGE_BYTES:
        raise ValueError("策略包为空或超过 256 MB")
    return raw


def _extract_package(raw: bytes, destination: Path) -> Path:
    archive_path = destination / "package.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(raw)
    extract_root = destination / "package"
    extract_root.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            total = 0
            for item in archive.infolist():
                member = Path(item.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(f"策略包包含不安全路径：{item.filename}")
                total += int(item.file_size)
                if total > MAX_PACKAGE_BYTES:
                    raise ValueError("策略包解压后超过 256 MB")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("策略包不能包含符号链接")
            archive.extractall(extract_root)
    except zipfile.BadZipFile as exc:
        raise ValueError("策略包不是有效 ZIP 文件") from exc
    archive_path.unlink(missing_ok=True)

    candidates = [extract_root]
    candidates.extend(path.parent for path in extract_root.rglob("strategies") if path.is_dir())
    for candidate in sorted(set(candidates), key=lambda item: len(item.parts)):
        strategies_dir = candidate / "strategies"
        if strategies_dir.is_dir() and any(strategies_dir.glob("*.py")):
            return candidate
    if any(extract_root.glob("*.py")):
        return extract_root
    raise ValueError("策略包内未找到 strategies/*.py 或根目录 Python 策略文件")


def _class_inventory(package_root: Path) -> dict[str, str]:
    search_root = package_root / "strategies" if (package_root / "strategies").is_dir() else package_root
    inventory: dict[str, str] = {}
    duplicates: set[str] = set()
    for path in sorted(search_root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in inventory:
                    duplicates.add(node.name)
                inventory[node.name] = path.relative_to(package_root).as_posix()
    if duplicates:
        raise ValueError(f"策略类名重复：{', '.join(sorted(duplicates))}")
    return inventory


# 部分实盘策略在 on_init 里按相对路径加载模型文件（如 pickle 的 .model），
# 打包时漏掉这些文件会让回放在运行期才失败，因此导入时先行检查。
SIDECAR_PATTERN = re.compile(r"""["']([^"']*\.(?:model|pkl|pickle|joblib|npy))["']""")


def _missing_sidecar_files(package_root: Path) -> list[str]:
    search_root = package_root / "strategies" if (package_root / "strategies").is_dir() else package_root
    missing: list[str] = []
    for path in sorted(search_root.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for reference in dict.fromkeys(SIDECAR_PATTERN.findall(text)):
            candidate = Path(reference.replace("\\", "/"))
            if candidate.is_absolute() or ".." in candidate.parts:
                missing.append(f"{path.name} 引用了包外路径 {reference}")
            elif not (package_root / candidate).is_file() and not (search_root / candidate.name).is_file():
                missing.append(f"{path.name} 需要 {reference}")
    return missing


def _config_hash(config: dict[str, Any]) -> str:
    return _hash_json({
        "class_name": _text(config.get("class_name")),
        "vt_symbol": _text(config.get("vt_symbol")),
        "setting": dict(config.get("setting") or {}),
    })


def _bindings_from_settings(source_id: str, settings: dict[str, Any], inventory: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance_name, raw_config in settings.items():
        config = dict(raw_config or {})
        parameters = dict(config.get("setting") or {})
        class_name = _text(config.get("class_name"))
        vt_symbol = _text(config.get("vt_symbol"))
        if not class_name or class_name not in inventory:
            raise ValueError(f"{instance_name} 找不到策略类：{class_name or '-'}")
        if "." not in vt_symbol:
            raise ValueError(f"{instance_name} 的交易标的无效：{vt_symbol or '-'}")
        fixed_size = _number(parameters.get("fixed_size"), 0)
        if fixed_size <= 0:
            raise ValueError(f"{instance_name} 的 fixed_size 必须大于 0")
        rows.append({
            "binding_id": f"binding_{source_id}_{_slug(str(instance_name))}",
            "source_id": source_id,
            "instance_name": str(instance_name),
            "class_name": class_name,
            "module_path": inventory[class_name],
            "vt_symbol": vt_symbol,
            "fixed_size": fixed_size,
            "parameters": parameters,
            "config_hash": _config_hash(config),
        })
    if not rows:
        raise ValueError("实盘配置中没有启用的策略")
    if len(rows) > MAX_INSTANCES:
        raise ValueError(f"单个实盘源最多支持 {MAX_INSTANCES} 个策略实例")
    return rows


# ---------------------------------------------------------------- 快照


def _snapshot_dir(source_id: str, trade_date: str) -> Path:
    return LIVE_ROOT / source_id / "snapshots" / trade_date


def _save_snapshot(source_id: str, trade_date: str, settings: dict[str, Any], states: dict[str, Any]) -> dict[str, Any]:
    setting_hash = _hash_json(settings)
    state_hash = _hash_json(states)
    existing = live_repository.get_snapshot_for_date(source_id, trade_date)
    if existing:
        if existing["setting_hash"] == setting_hash and existing["state_hash"] == state_hash:
            return existing
        raise ValueError(f"{trade_date} 已存在内容不同的实盘快照，请先确认是哪一份为准")
    artifact_path = _snapshot_dir(source_id, trade_date)
    hashes = _capture_code(source_id, artifact_path)
    metadata = {"captured_at": now_iso(), "trade_date": trade_date, "code_hashes": hashes}
    source = live_repository.get_source(source_id)
    if source.get("source_kind") == SOURCE_KIND_LOCAL:
        state_file = local_vntrader_dir() / STATE_FILENAME
        metadata["state_modified_at"] = datetime.fromtimestamp(state_file.stat().st_mtime, BEIJING_TZ).isoformat()
    _write_json(artifact_path / "capture.json", metadata)
    _write_json(artifact_path / "cta_strategy_setting.json", settings)
    _write_json(artifact_path / "cta_strategy_data.json", states)
    return live_repository.create_snapshot({
        "snapshot_id": f"live_snapshot_{timestamp_id()}_{uuid4().hex[:6]}",
        "source_id": source_id, "trade_date": trade_date,
        "setting_hash": setting_hash, "state_hash": state_hash,
        "artifact_path": _stored_path(artifact_path),
    })


def _load_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _artifact_path(snapshot.get("artifact_path"))
    return (
        json.loads((path / "cta_strategy_setting.json").read_text(encoding="utf-8")),
        json.loads((path / "cta_strategy_data.json").read_text(encoding="utf-8")),
    )


# ---------------------------------------------------------------- 导入


def import_source(payload: dict[str, Any]) -> dict[str, Any]:
    """建立实盘源。默认读本机 .env 配置的目录；也支持上传策略包 ZIP。"""
    trade_date = _validated_date(payload.get("trade_date"))
    kind = _text(payload.get("source_kind")) or SOURCE_KIND_LOCAL
    if kind not in {SOURCE_KIND_LOCAL, SOURCE_KIND_PACKAGE}:
        raise ValueError(f"未知的实盘源类型：{kind}")

    _check_capture_date(trade_date, local=kind == SOURCE_KIND_LOCAL)
    source_id = f"live_{timestamp_id()}_{uuid4().hex[:6]}"
    source_root = LIVE_ROOT / source_id
    source_root.mkdir(parents=True, exist_ok=False)
    try:
        if kind == SOURCE_KIND_LOCAL:
            settings, states = read_local_live_files()
            package_root = local_strategy_dir()
            package_path, package_hash = "", ""
        else:
            settings = dict(payload.get("settings") or {})
            states = dict(payload.get("states") or {})
            raw_package = _decode_package(str(payload.get("package_base64") or ""))
            package_root = _extract_package(raw_package, source_root)
            package_path = stored_path(package_root)
            package_hash = hashlib.sha256(raw_package).hexdigest()

        inventory = _class_inventory(package_root)
        missing = _missing_sidecar_files(package_root)
        if missing:
            preview = "；".join(missing[:5])
            more = f"（共 {len(missing)} 处）" if len(missing) > 5 else ""
            raise ValueError(f"策略目录缺少策略依赖的模型文件{more}：{preview}")
        bindings = _bindings_from_settings(source_id, settings, inventory)
        live_repository.create_source({
            "source_id": source_id,
            "name": _text(payload.get("name")) or "实盘组合",
            "source_kind": kind,
            "package_path": package_path,
            "package_hash": package_hash,
            "first_date": trade_date,
            "instance_count": len(bindings),
        })
        live_repository.create_bindings(bindings)
        _save_snapshot(source_id, trade_date, settings, states)
        return get_source_detail(source_id)
    except Exception:
        live_repository.delete_source(source_id)
        shutil.rmtree(source_root, ignore_errors=True)
        raise


def import_snapshot(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """记录某个交易日的实盘状态。本机模式下不传内容就直接读当前配置目录。"""
    source = live_repository.get_source(source_id)
    if source is None:
        raise FileNotFoundError(f"实盘源不存在：{source_id}")
    trade_date = _validated_date(payload.get("trade_date"))
    _check_capture_date(trade_date, local=_text(source.get("source_kind")) == SOURCE_KIND_LOCAL)
    if _text(source.get("source_kind")) == SOURCE_KIND_LOCAL and not payload.get("settings"):
        settings, states = read_local_live_files()
    else:
        settings = dict(payload.get("settings") or {})
        states = dict(payload.get("states") or {})
    return _save_snapshot(source_id, _validated_date(payload.get("trade_date")), settings, states)


# ---------------------------------------------------------------- 行情


def _ensure_market_data(
    bindings: list[dict[str, Any]], replay_start: str, trade_date: str, update: bool
) -> dict[str, str]:
    """预热区间必须与实盘 on_init 加载的区间一致，否则指标算不出相同的值。

    预热是从回放起始日往前推的，起点快照与目标日相隔越久，需要的行情就越早，
    因此窗口必须以 replay_start 为基准，不能用目标日。
    """
    warmup_start = (date.fromisoformat(replay_start) - timedelta(days=WARMUP_DAYS)).isoformat()
    failures: dict[str, str] = {}
    for vt_symbol in sorted({str(item["vt_symbol"]) for item in bindings}):
        symbol, exchange = split_vt_symbol(vt_symbol)
        coverage = coverage_service.get_data_coverage(
            symbol, exchange, "1m", start_date=warmup_start, end_date=trade_date
        )
        if coverage.get("status") == "covered":
            continue
        if not update:
            failures[vt_symbol] = f"缺少 {warmup_start} 至 {trade_date} 的一分钟行情"
            continue
        for missing in coverage.get("missing_ranges") or [{"start_date": warmup_start, "end_date": trade_date}]:
            result = download_service.download_bars(
                symbol, exchange, "1m",
                str(missing.get("start_date") or warmup_start), str(missing.get("end_date") or trade_date),
            )
            if not result.get("success"):
                failures[vt_symbol] = _text(result.get("error")) or "行情下载失败"
                break
        if vt_symbol in failures:
            continue
        recheck = coverage_service.get_data_coverage(
            symbol, exchange, "1m", start_date=warmup_start, end_date=trade_date
        )
        if recheck.get("status") != "covered":
            failures[vt_symbol] = f"{warmup_start} 至 {trade_date} 的一分钟行情仍不完整"
    # The general coverage index only checks boundaries. Verify the actual replay days too.
    from backend.backtesting.local_data_provider import load_bar_data
    from backend.backtesting.replay_worker import replay_data_issue
    start = datetime.combine(date.fromisoformat(replay_start), time.min)
    end = datetime.combine(date.fromisoformat(trade_date), time.max)
    for vt_symbol in sorted({str(item["vt_symbol"]) for item in bindings}):
        if vt_symbol in failures:
            continue
        symbol, exchange = split_vt_symbol(vt_symbol)
        bars = load_bar_data(vt_symbol, "1m", start, end)
        issue = replay_data_issue(bars, start.date(), end.date(), exchange)
        if issue and update:
            download = download_service.download_bars(symbol, exchange, "1m", replay_start, trade_date)
            if not download.get("success"):
                failures[vt_symbol] = _text(download.get("error")) or "行情下载失败"
                continue
            issue = replay_data_issue(load_bar_data(vt_symbol, "1m", start, end), start.date(), end.date(), exchange)
        if issue:
            failures[vt_symbol] = issue
    return failures


# ---------------------------------------------------------------- 回放


def _run_replay(
    binding: dict[str, Any],
    source: dict[str, Any],
    start_date: str,
    end_date: str,
    prior_state: dict[str, Any],
) -> dict[str, Any]:
    package_root = package_root_for(source)
    request = {
        "package_root": str(package_root), "module_path": binding["module_path"],
        "class_name": binding["class_name"], "vt_symbol": binding["vt_symbol"],
        "parameters": binding["parameters"], "prior_state": prior_state,
        "start_date": start_date, "end_date": end_date,
    }
    with tempfile.TemporaryDirectory(prefix="gyro_replay_") as temporary:
        input_path = Path(temporary) / "input.json"
        output_path = Path(temporary) / "output.json"
        input_path.write_text(json.dumps(request, ensure_ascii=False, default=str), encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(PROJECT_ROOT), environment.get("PYTHONPATH", "")])
        )
        completed = subprocess.run(
            [sys.executable, "-m", "backend.backtesting.replay_worker", str(input_path), str(output_path)],
            cwd=str(package_root), env=environment,
            capture_output=True, text=True, timeout=REPLAY_TIMEOUT_SECONDS,
        )
        if not output_path.exists():
            return {"success": False, "error": (completed.stderr or completed.stdout or "回放进程无输出")[-2000:]}
        return json.loads(output_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 每日跟踪


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status") or "UNKNOWN")
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "total": len(rows),
        "match": statuses.get(STATUS_MATCH, 0),
        "mismatch": statuses.get(STATUS_MISMATCH, 0),
        "unresolved": len(rows) - statuses.get(STATUS_MATCH, 0) - statuses.get(STATUS_MISMATCH, 0),
        "trade_count": int(sum(len(row.get("replay_trades") or []) for row in rows)),
        "statuses": statuses,
    }


def track_day(source_id: str, trade_date: str, *, update_data: bool = True) -> dict[str, Any]:
    source = live_repository.get_source(source_id)
    if source is None:
        raise FileNotFoundError(f"实盘源不存在：{source_id}")
    trade_date = _validated_date(trade_date)

    _check_capture_date(trade_date)

    snapshot = live_repository.get_snapshot_for_date(source_id, trade_date)
    if snapshot is None:
        raise FileNotFoundError(f"请先导入 {trade_date} 的实盘快照")
    prior = live_repository.previous_snapshot(source_id, trade_date)
    if prior is None:
        raise FileNotFoundError(
            f"{trade_date} 是最早的一份实盘快照，只能作为回放起点，本身无法被跟踪。"
            "跟踪一个交易日需要该日与更早的两份快照。"
        )
    settings, states = _load_snapshot(snapshot)
    prior_settings, prior_states = _load_snapshot(prior)
    captures = []
    for item in (prior, snapshot):
        metadata = _artifact_path(item["artifact_path"]) / "capture.json"
        captures.append(json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {})
    code_verified = bool(captures[0].get("code_hashes")) and captures[0].get("code_hashes") == captures[1].get("code_hashes")
    replay_source = {**source, "source_kind": SOURCE_KIND_PACKAGE, "package_path": str(_artifact_path(snapshot["artifact_path"]) / "code")}
    # 起点快照记录的是它那一天收盘后的状态，所以回放从它的次日开始，一直放到目标日。
    replay_start = (date.fromisoformat(str(prior["trade_date"])) + timedelta(days=1)).isoformat()
    bindings = live_repository.list_bindings(source_id)
    data_failures = _ensure_market_data(bindings, replay_start, trade_date, update_data)

    rows: list[dict[str, Any]] = []
    for binding in bindings:
        instance = str(binding["instance_name"])
        actual_state = states.get(instance)
        base = {
            "binding_id": binding["binding_id"], "instance_name": instance,
            "vt_symbol": binding["vt_symbol"], "fixed_size": binding["fixed_size"],
            "actual_pos": _number(dict(actual_state or {}).get("pos"), 0) if actual_state is not None else None,
            "replay_pos": None, "difference": None, "replay_trades": [],
        }
        config = settings.get(instance)
        if config is None or _config_hash(dict(config or {})) != binding["config_hash"]:
            rows.append({**base, "status": STATUS_CONFIG_CHANGED,
                         "message": "实盘参数或标的已变化，需要重新导入实盘源以重建绑定。"})
            continue
        if not _valid_position(actual_state):
            rows.append({**base, "status": STATUS_NO_STATE, "message": "当日快照缺少合法的策略持仓 pos。"})
            continue
        if not _valid_position(prior_states.get(instance)):
            rows.append({**base, "status": STATUS_NO_STATE,
                         "message": f"起点快照 {prior['trade_date']} 缺少该策略的状态，无法确定回放起点。"})
            continue
        if not code_verified or _config_hash(dict(prior_settings.get(instance) or {})) != binding["config_hash"]:
            rows.append({**base, "status": STATUS_CONFIG_CHANGED, "message": "起点与终点代码、模型或参数不一致，或旧快照未保存代码；请重新建立可靠起点。"})
            continue
        if binding["vt_symbol"] in data_failures:
            rows.append({**base, "status": STATUS_DATA_GAP, "message": data_failures[binding["vt_symbol"]]})
            continue

        try:
            result = _run_replay(
                binding, replay_source, replay_start, trade_date, dict(prior_states[instance] or {})
            )
        except subprocess.TimeoutExpired:
            rows.append({**base, "status": STATUS_REPLAY_ERROR,
                         "message": f"回放超过 {REPLAY_TIMEOUT_SECONDS} 秒被终止。"})
            continue
        if not result.get("success"):
            missing_bars = _text(result.get("reason")) == "no_bars"
            rows.append({
                **base,
                "status": STATUS_DATA_GAP if missing_bars else STATUS_REPLAY_ERROR,
                "message": _text(result.get("error")) or "回放失败",
            })
            continue

        if not _valid_position({"pos": result.get("end_pos")}) or result.get("state_unrestored"):
            rows.append({**base, "status": STATUS_NO_STATE, "message": "回放缺少合法持仓或关键状态未能恢复。"})
            continue
        replay_pos = float(result["end_pos"])
        difference = _number(base["actual_pos"], 0) - replay_pos
        rows.append({
            **base,
            "replay_pos": replay_pos,
            "difference": difference,
            "replay_trades": list(result.get("trades") or []),
            "replay_orders": list(result.get("orders") or []),
            "replay_signals": list(result.get("signals") or []),
            "trace_version": result.get("trace_version"),
            "replay_variables": dict(result.get("end_variables") or {}),
            "status": STATUS_MATCH if abs(difference) < 1e-9 else STATUS_MISMATCH,
            "message": "",
        })

    for instance in settings:
        if not any(row["instance_name"] == instance for row in rows):
            rows.append({
                "binding_id": "", "instance_name": str(instance),
                "vt_symbol": _text(dict(settings[instance] or {}).get("vt_symbol")),
                "fixed_size": None, "actual_pos": _number(dict(states.get(instance) or {}).get("pos"), 0),
                "replay_pos": None, "difference": None, "replay_trades": [],
                "status": STATUS_NEW_INSTANCE,
                "message": "实盘新增了该策略，尚未绑定，需要重新导入实盘源。",
            })

    rows.sort(key=lambda row: (row["status"] == STATUS_MATCH, str(row["instance_name"])))
    return _persist_record(source_id, trade_date, rows, str(prior["trade_date"]), replay_start)


def _persist_record(
    source_id: str,
    trade_date: str,
    rows: list[dict[str, Any]],
    prior_date: str,
    replay_start: str,
) -> dict[str, Any]:
    record_id = f"live_day_{timestamp_id()}_{uuid4().hex[:6]}"
    artifact_path = LIVE_ROOT / source_id / "daily" / trade_date
    summary = {
        **_summarize(rows),
        "day_trade_count": sum(1 for row in rows for trade in row.get("replay_trades", [])
                               if str(trade.get("datetime", ""))[:10] == trade_date),
        "prior_date": prior_date,
        "replay_start": replay_start,
        "replay_end": trade_date,
        "completed_at": now_iso(),
    }
    _write_json(artifact_path / "summary.json", summary)
    _write_json(artifact_path / "rows.json", rows)
    _write_csv(artifact_path / "positions.csv", [
        {key: row.get(key) for key in
         ("instance_name", "vt_symbol", "fixed_size", "actual_pos", "replay_pos", "difference", "status", "message")}
        for row in rows
    ])
    _write_csv(artifact_path / "replay_trades.csv", [
        {"instance_name": row["instance_name"], **trade}
        for row in rows for trade in (row.get("replay_trades") or [])
    ])
    _write_csv(artifact_path / "replay_orders.csv", [
        {"instance_name": row["instance_name"], **order}
        for row in rows for order in row.get("replay_orders", [])
    ])
    live_repository.save_daily_record({
        "record_id": record_id, "source_id": source_id, "trade_date": trade_date,
        "summary": summary, "artifact_path": _stored_path(artifact_path), "error": None,
    })
    return get_daily_record(source_id, trade_date)


# ---------------------------------------------------------------- 查询


def get_daily_record(source_id: str, trade_date: str) -> dict[str, Any]:
    record = live_repository.get_daily_record(source_id, _validated_date(trade_date))
    if record is None:
        raise FileNotFoundError(f"没有 {trade_date} 的跟踪记录")
    rows_path = _artifact_path(record.get("artifact_path")) / "rows.json"
    return {**record, "rows": json.loads(rows_path.read_text(encoding="utf-8")) if rows_path.exists() else []}


def get_source_detail(source_id: str) -> dict[str, Any]:
    source = live_repository.get_source(source_id)
    if source is None:
        raise FileNotFoundError(f"实盘源不存在：{source_id}")
    records = live_repository.list_daily_records(source_id)
    latest = get_daily_record(source_id, str(records[0]["trade_date"])) if records else {}
    return {
        "source": source,
        "local_status": local_source_status() if _text(source.get("source_kind")) == SOURCE_KIND_LOCAL else {},
        "bindings": [
            {key: value for key, value in item.items() if key != "parameters"}
            for item in live_repository.list_bindings(source_id)
        ],
        "snapshots": live_repository.list_snapshots(source_id),
        "records": records,
        "latest": latest,
    }


def list_sources() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in live_repository.list_sources():
        records = live_repository.list_daily_records(str(source["source_id"]), limit=1)
        result.append({
            **source,
            "latest_trade_date": str(records[0]["trade_date"]) if records else "",
            "latest_summary": dict(records[0].get("summary") or {}) if records else {},
        })
    return result


def delete_source(source_id: str) -> dict[str, Any]:
    """弃用一个实盘源：删除它的绑定、快照与跟踪记录，以及自身的产物目录。

    只清除本模块写入的内容，不触碰实盘目录里的任何用户文件。
    """
    source = live_repository.get_source(source_id)
    if source is None:
        raise FileNotFoundError(f"实盘源不存在：{source_id}")
    live_repository.delete_source(source_id)
    shutil.rmtree(LIVE_ROOT / source_id, ignore_errors=True)
    return {"deleted": source_id}


def list_daily_records(source_id: str, limit: int = 60) -> list[dict[str, Any]]:
    return live_repository.list_daily_records(source_id, limit=limit)
