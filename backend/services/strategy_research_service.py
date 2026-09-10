from __future__ import annotations

from backend.core.paths import path_fields

from ast import ClassDef, parse
from pathlib import Path
from typing import Any
from uuid import uuid4
import hashlib
import json
import re

from backend.common.time_utils import now_beijing, now_iso
from backend.core.paths import CACHE_ROOT, POOL_STRATEGIES_ROOT, RESEARCH_ROOT
from backend.domain.enums import TaskType
from backend.services import pool_service, task_service
from backend.strategy_generation.providers import build_provider
from backend.strategy_optimization import optimize_parameters, parameter_policy
from backend.strategy_optimization.optimizers.common import values_from_range
from backend.strategy_optimization.search_space import build_parameter_inventory


ALLOWED_OBJECTIVES = {"excess_return", "sharpe"}
AI_OVERVIEW_PROMPT_VERSION = "research_overview_v1"
AI_OVERVIEW_CACHE_ROOT = CACHE_ROOT / "strategy_research_ai_overviews"
AI_OVERVIEW_FIXED_SUGGESTION = "建议继续检查参数稳定性，并补充分阶段表现和滚动优化验证。"
AI_OVERVIEW_SYSTEM_PROMPT = """你是量化研究平台的“AI 研究提示”助手。

你只根据给出的策略概览数据生成一句简短中文，不检查代码、不修改策略、不自行计算指标，也不判断策略已经稳健或可以实盘。

要求：
- 先用最多 60 个汉字概括当前结果，只选择 1 至 2 个最值得注意的事实。
- 收益口径是单位仓位累计收益，固定数量、非复利；禁止使用初始资金、资金利用率或账户复利解释。
- 交易次数为 0 时，优先说明当前没有可分析的交易样本。
- 收益较低、跑输基准或回撤较大时可以如实描述，但不要直接否定策略。
- 不得声称已经完成参数稳定性或滚动优化研究。
- 不分析市场原因，不补造输入中不存在的数据。
- 不要给出多条建议，后端会统一添加固定研究建议。

只返回 JSON，不要 Markdown：
{"summary": "一句简短的当前结果概括"}
"""


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(path_fields(payload, storing=True), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_pool_path(detail: dict[str, Any]) -> Path:
    pool_path = Path(str(detail.get("pool_path") or "")).resolve()
    try:
        pool_path.relative_to(POOL_STRATEGIES_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("策略池快照路径不安全，拒绝执行研究") from exc
    if not pool_path.is_dir():
        raise FileNotFoundError(f"策略池快照目录不存在：{pool_path}")
    return pool_path


def _safe_research_dir(pool_item_id: str) -> Path:
    root = RESEARCH_ROOT.resolve()
    target = (root / pool_item_id).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("策略研究目录不安全") from exc
    target.mkdir(parents=True, exist_ok=True)
    return target


def _parameters_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    config = dict(detail.get("config") or {})
    manifest = dict(detail.get("manifest") or {})
    result = dict(detail.get("result") or {})
    for candidate in (
        config.get("parameters"),
        manifest.get("parameters"),
        result.get("recommended", {}).get("parameters") if isinstance(result.get("recommended"), dict) else None,
        result.get("params"),
        result.get("parameters"),
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def _class_name(strategy_code: str, detail: dict[str, Any], inventory: dict[str, Any]) -> str:
    manifest = dict(detail.get("manifest") or {})
    config = dict(detail.get("config") or {})
    explicit = str(inventory.get("class_name") or manifest.get("class_name") or config.get("class_name") or "").strip()
    if explicit:
        return explicit
    try:
        tree = parse(strategy_code)
    except SyntaxError:
        return ""
    return next((node.name for node in tree.body if isinstance(node, ClassDef) and not node.name.startswith("_")), "")


def _parameter_inventory(detail: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    strategy_code = str(detail.get("strategy_code") or "")
    if not strategy_code.strip():
        raise FileNotFoundError("策略池快照缺少 strategy.py")
    pool_parameters = _parameters_from_detail(detail)
    inventory = build_parameter_inventory(strategy_code=strategy_code, generation_report={})
    base_parameters = {**dict(inventory.get("base_parameters") or {}), **pool_parameters, "fixed_size": 1}
    parameters: list[dict[str, Any]] = []
    for raw_item in list(inventory.get("parameters") or []):
        item = dict(raw_item)
        name = str(item.get("name") or "").strip()
        current = pool_parameters.get(name, item.get("current"))
        if not name or name == "fixed_size" or isinstance(current, bool) or not isinstance(current, (int, float)):
            continue
        item["current"] = current
        default_range = parameter_policy.default_range_for_parameter(name, current)
        if default_range:
            item.update(default_range)
        item["type"] = "int" if isinstance(current, int) and not isinstance(current, bool) else "float"
        parameters.append(item)
    return {**inventory, "base_parameters": base_parameters}, parameters


def _latest_heatmap(pool_item_id: str) -> dict[str, Any] | None:
    root = RESEARCH_ROOT.resolve()
    research_dir = (root / pool_item_id).resolve()
    try:
        research_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("策略研究目录不安全") from exc
    if not research_dir.is_dir():
        return None
    candidates = sorted(research_dir.glob("*/result.json"), key=lambda path: path.parent.name, reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("type") == "parameter_heatmap":
            return payload
    return None


def get_pool_research_context(pool_item_id: str) -> dict[str, Any]:
    from backend.services.walk_forward_research_service import latest_walk_forward_result

    detail = pool_service.get_pool_item_detail(pool_item_id)
    _safe_pool_path(detail)
    inventory, parameters = _parameter_inventory(detail)
    result = dict(detail.get("result") or {})
    daily_results = dict(detail.get("daily_results") or {})
    return {
        "pool_item": dict(detail.get("pool_item") or {}),
        "config": dict(detail.get("config") or {}),
        "metrics": dict(result.get("metrics") or result),
        "parameters": parameters,
        "base_parameters": dict(inventory.get("base_parameters") or {}),
        "curve": list(daily_results.get("data") or []),
        "notes": str(detail.get("notes") or ""),
        "latest_heatmap": _latest_heatmap(pool_item_id),
        "latest_walk_forward": latest_walk_forward_result(pool_item_id),
    }


def _overview_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _overview_row_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _overview_number(row.get(key))
        if number is not None:
            return number
    return None


def _overview_curve_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    previous_close: float | None = None
    strategy_return = 0.0
    benchmark_return = 0.0
    strategy_peak = 0.0
    max_drawdown = 0.0
    for row in rows:
        close = _overview_row_number(row, "close_price", "close", "price")
        pre_close = _overview_row_number(row, "pre_close", "prev_close", "previous_close")
        denominator = previous_close if previous_close is not None and previous_close > 0 else None
        if denominator is None and close is not None and close > 0 and pre_close is not None and pre_close > 0:
            ratio = pre_close / close
            if 0.5 < ratio < 1.5:
                denominator = pre_close
        if denominator is None and close is not None and close > 0:
            denominator = close
        if close is not None and close > 0:
            previous_close = close
        if denominator is None or denominator <= 0:
            continue
        strategy_return += (_overview_row_number(row, "net_pnl") or 0.0) / denominator * 100.0
        strategy_peak = max(strategy_peak, strategy_return)
        max_drawdown = min(max_drawdown, strategy_return - strategy_peak)
        if close is not None and close > 0:
            benchmark_return += (close / denominator - 1.0) * 100.0
    return {
        "cumulative_return_pct": round(strategy_return, 4),
        "benchmark_return_pct": round(benchmark_return, 4),
        "excess_return_pct_points": round(strategy_return - benchmark_return, 4),
        "max_drawdown_pct_points": round(max_drawdown, 4),
    }


def _ai_overview_cache_path(pool_item_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(pool_item_id or "").strip())
    if not safe_id:
        raise ValueError("pool_item_id 不能为空")
    AI_OVERVIEW_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return AI_OVERVIEW_CACHE_ROOT / f"{safe_id}.json"


def _read_ai_overview_cache(path: Path, fingerprint: str) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("input_fingerprint") != fingerprint:
        return None
    return {**payload, "cached": True}


def _parse_ai_overview(content: str) -> str:
    text = str(content or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI 研究提示返回格式错误")
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI 研究提示返回格式错误")
    summary = re.sub(r"\s+", "", str(payload.get("summary") or "").strip())
    if not summary:
        raise ValueError("AI 研究提示缺少摘要")
    summary = summary[:90].rstrip("。；;，,")
    return f"{summary}；{AI_OVERVIEW_FIXED_SUGGESTION}"


def create_pool_ai_overview(
    pool_item_id: str,
    *,
    force_refresh: bool = False,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.services.walk_forward_research_service import latest_walk_forward_result

    detail = pool_service.get_pool_item_detail(pool_item_id)
    _safe_pool_path(detail)
    item = dict(detail.get("pool_item") or {})
    config = dict(detail.get("config") or {})
    result = dict(detail.get("result") or {})
    metrics = dict(result.get("metrics") or result)
    daily_rows = list(dict(detail.get("daily_results") or {}).get("data") or [])
    trade_rows = list(dict(detail.get("trades") or {}).get("data") or [])
    curve_metrics = _overview_curve_metrics(daily_rows)
    trade_count = len(trade_rows) if trade_rows else int(_overview_number(metrics.get("total_trade_count")) or 0)
    context = {
        "strategy_name": item.get("strategy_name") or item.get("display_name"),
        "vt_symbol": item.get("vt_symbol"),
        "interval": config.get("interval"),
        "start_date": config.get("start_date") or metrics.get("start_date"),
        "end_date": config.get("end_date") or metrics.get("end_date"),
        "trade_count": trade_count,
        **curve_metrics,
        "sharpe": _overview_number(metrics.get("sharpe") or metrics.get("sharpe_ratio")),
        "parameter_stability_completed": _latest_heatmap(pool_item_id) is not None,
        "walk_forward_completed": latest_walk_forward_result(pool_item_id) is not None,
        "return_basis": "单位仓位累计收益，固定数量，非复利",
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {"prompt_version": AI_OVERVIEW_PROMPT_VERSION, "context": context},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cache_path = _ai_overview_cache_path(pool_item_id)
    if not force_refresh:
        cached = _read_ai_overview_cache(cache_path, fingerprint)
        if cached is not None:
            return cached

    provider = build_provider({**dict(options or {}), "temperature": 0.05})
    content = provider.complete(
        [
            {"role": "system", "content": AI_OVERVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "请生成该策略的单句研究提示：\n" + json.dumps(context, ensure_ascii=False, indent=2),
            },
        ]
    )
    payload = {
        "pool_item_id": pool_item_id,
        "prompt_version": AI_OVERVIEW_PROMPT_VERSION,
        "generated_at": now_iso(),
        "input_fingerprint": fingerprint,
        "model": provider.config.model,
        "cached": False,
        "summary": _parse_ai_overview(content),
    }
    _write_json_atomic(cache_path, payload)
    return payload


def _validated_range(name: str, raw_spec: Any, parameter: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    if not isinstance(raw_spec, dict):
        raise ValueError(f"参数 {name} 缺少有效范围")
    spec = {
        "low": raw_spec.get("low"),
        "high": raw_spec.get("high"),
        "step": raw_spec.get("step"),
        "type": parameter.get("type") or "float",
    }
    values = values_from_range(spec, parameter.get("current"))
    if len(values) < 2:
        raise ValueError(f"参数 {name} 至少需要两个有效取值")
    return spec, values


def _stability_summary(rows: list[dict[str, Any]], objective: str) -> dict[str, Any]:
    values = [float(row.get(objective)) for row in rows if row.get("success") and row.get(objective) is not None]
    if not values:
        return {"level": "unknown", "positive_ratio": 0.0, "summary": "没有可用于判断的成功组合。"}
    positive_ratio = sum(value > 0 for value in values) / len(values)
    if positive_ratio >= 0.7:
        level, label = "stable", "较稳定"
    elif positive_ratio >= 0.4:
        level, label = "general", "一般"
    else:
        level, label = "sensitive", "较敏感"
    metric_label = "超额收益" if objective == "excess_return" else "Sharpe"
    return {
        "level": level,
        "label": label,
        "positive_ratio": positive_ratio,
        "successful_count": len(values),
        "summary": f"{len(values)} 个有效组合中，{positive_ratio:.0%} 的{metric_label}为正，当前网格表现{label}。",
    }


def run_pool_parameter_heatmap(
    pool_item_id: str,
    *,
    x_parameter: str,
    y_parameter: str,
    parameter_ranges: dict[str, Any],
    objective: str = "excess_return",
    max_trials: int = 100,
) -> dict[str, Any]:
    if x_parameter == y_parameter:
        raise ValueError("横轴和纵轴必须选择不同参数")
    objective = str(objective or "excess_return").strip().lower()
    if objective not in ALLOWED_OBJECTIVES:
        raise ValueError("当前仅支持按超额收益或 Sharpe 研究")

    detail = pool_service.get_pool_item_detail(pool_item_id)
    _safe_pool_path(detail)
    inventory, parameters = _parameter_inventory(detail)
    parameter_by_name = {str(item["name"]): item for item in parameters}
    missing = [name for name in (x_parameter, y_parameter) if name not in parameter_by_name]
    if missing:
        raise ValueError(f"不可研究的参数：{', '.join(missing)}")
    x_spec, x_values = _validated_range(x_parameter, parameter_ranges.get(x_parameter), parameter_by_name[x_parameter])
    y_spec, y_values = _validated_range(y_parameter, parameter_ranges.get(y_parameter), parameter_by_name[y_parameter])
    total = len(x_values) * len(y_values)
    if total > min(100, max_trials):
        raise ValueError(f"当前网格共 {total} 组，第一版最多允许 {min(100, max_trials)} 组")

    item = dict(detail.get("pool_item") or {})
    config = dict(detail.get("config") or {})
    strategy_code = str(detail.get("strategy_code") or "")
    class_name = _class_name(strategy_code, detail, inventory)
    vt_symbol = str(item.get("vt_symbol") or config.get("vt_symbol") or "").strip()
    if not class_name or not vt_symbol:
        raise ValueError("策略池快照缺少可执行类名或标的信息")

    task = task_service.create_task(
        TaskType.STRATEGY_RESEARCH.value,
        message=f"参数热力图排队中 · {total} 组",
        related_strategy_id=str(item.get("strategy_id") or "") or None,
        related_pool_item_id=pool_item_id,
    )
    task_service.mark_running(task["task_id"], message=f"参数热力图进行中 0/{total} 组")
    try:
        def progress_callback(current: int, count: int, message: str) -> None:
            task_service.mark_progress(task["task_id"], current / max(1, count), message=message.replace("参数优化", "参数研究"))

        optimization = optimize_parameters(
            strategy_code=strategy_code,
            class_name=class_name,
            vt_symbol=vt_symbol,
            base_parameters={**dict(inventory.get("base_parameters") or {}), "fixed_size": 1},
            parameter_space={x_parameter: x_spec, y_parameter: y_spec},
            backtest_config={
                **config,
                "mode": "real",
                "execution_mode": "real_backtest",
                "is_real_backtest": True,
                "max_trials": total,
            },
            objective=objective,
            options={
                "method": "manual_grid",
                "selected_parameters": [x_parameter, y_parameter],
                "max_trials": total,
                "progress_callback": progress_callback,
            },
        )
        if not optimization.get("success"):
            raise RuntimeError(str(optimization.get("error") or "参数热力图失败"))

        created_at = now_beijing().isoformat()
        experiment_id = f"research_{now_beijing().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        rows = list(optimization.get("grid_summary") or [])
        payload = {
            "type": "parameter_heatmap",
            "experiment_id": experiment_id,
            "pool_item_id": pool_item_id,
            "created_at": created_at,
            "x_parameter": x_parameter,
            "y_parameter": y_parameter,
            "x_values": x_values,
            "y_values": y_values,
            "parameter_ranges": {x_parameter: x_spec, y_parameter: y_spec},
            "objective": objective,
            "grid_summary": rows,
            "recommended": optimization.get("recommended") or {},
            "stability": _stability_summary(rows, objective),
        }
        experiment_dir = _safe_research_dir(pool_item_id) / experiment_id
        _write_json_atomic(experiment_dir / "result.json", payload)
        completed = task_service.mark_completed(task["task_id"], message=f"参数热力图完成 · {total} 组")
        return {**payload, "task": completed}
    except Exception as exc:
        task_service.mark_failed(task["task_id"], error=str(exc), message="参数热力图失败")
        raise
