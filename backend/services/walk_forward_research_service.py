from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from math import ceil, isfinite, sqrt
from statistics import fmean, median, pstdev
from typing import Any
from uuid import uuid4
import json

from backend import backtesting
from backend.common.time_utils import now_beijing
from backend.core.paths import RESEARCH_ROOT
from backend.domain.enums import TaskType
from backend.services import pool_service, strategy_research_service, task_service
from backend.strategy_optimization import optimize_parameters
from backend.strategy_optimization.optimizers.common import enrich_metrics_with_curve_returns


ALLOWED_OBJECTIVES = {"sharpe"}


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _parse_date(value: Any, label: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"策略快照缺少{label}")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{label}格式无效：{text}") from exc


def _build_windows(start: date, end: date, training_months: int, test_months: int) -> list[dict[str, str]]:
    windows: list[dict[str, str]] = []
    train_start = start
    while True:
        test_start = _add_months(train_start, training_months)
        train_end = test_start - timedelta(days=1)
        test_end = _add_months(test_start, test_months) - timedelta(days=1)
        if test_end > end:
            break
        windows.append(
            {
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
            }
        )
        train_start = _add_months(train_start, test_months)
    return windows


def _latest_result(pool_item_id: str) -> dict[str, Any] | None:
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
        if payload.get("type") == "walk_forward":
            return payload
    return None


def latest_walk_forward_result(pool_item_id: str) -> dict[str, Any] | None:
    return _latest_result(pool_item_id)


def _stitched_metrics(rows: list[dict[str, Any]], capital: float, annual_days: int) -> dict[str, Any]:
    enriched = enrich_metrics_with_curve_returns({}, rows)
    balance = float(capital)
    returns: list[float] = []
    total_net_pnl = 0.0
    for row in rows:
        try:
            net_pnl = float(row.get("net_pnl") or 0.0)
        except (TypeError, ValueError):
            net_pnl = 0.0
        denominator = balance if balance > 0 else float(capital)
        returns.append(net_pnl / denominator if denominator > 0 else 0.0)
        balance += net_pnl
        total_net_pnl += net_pnl
    deviation = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = fmean(returns) / deviation * sqrt(max(1, annual_days)) if deviation > 0 else 0.0
    return {
        **enriched,
        "total_net_pnl": total_net_pnl,
        "total_return": ((balance / capital) - 1.0) * 100.0 if capital > 0 else 0.0,
        "sharpe": sharpe,
        "test_days": len(rows),
    }


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _average_ranks(values: list[float]) -> list[float]:
    """Return one-based ascending ranks with average ranks for ties."""
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average_rank = ((cursor + 1) + end) / 2.0
        for position in range(cursor, end):
            ranks[ordered[position][0]] = average_rank
        cursor = end
    return ranks


def _spearman_rank_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    left_mean = fmean(left_ranks)
    right_mean = fmean(right_ranks)
    covariance = sum((x - left_mean) * (y - right_mean) for x, y in zip(left_ranks, right_ranks, strict=True))
    left_variance = sum((x - left_mean) ** 2 for x in left_ranks)
    right_variance = sum((y - right_mean) ** 2 for y in right_ranks)
    denominator = sqrt(left_variance * right_variance)
    return covariance / denominator if denominator > 0 else None


def _parameter_marker(parameters: dict[str, Any]) -> str:
    return json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _parameter_rank_analysis(
    training_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    *,
    objective: str,
    maximum_groups: int = 5,
) -> dict[str, Any]:
    test_by_parameters = {
        _parameter_marker(dict(row.get("parameters") or {})): row
        for row in test_rows
        if row.get("success")
    }
    paired: list[dict[str, Any]] = []
    for training_row in training_rows:
        if not training_row.get("success"):
            continue
        parameters = dict(training_row.get("parameters") or {})
        test_row = test_by_parameters.get(_parameter_marker(parameters))
        if not test_row:
            continue
        training_score = _finite_float(training_row.get("score"))
        test_score = _finite_float(test_row.get("score"))
        if training_score is None or test_score is None:
            continue
        paired.append(
            {
                "label": str(training_row.get("label") or ""),
                "parameters": parameters,
                "training_score": training_score,
                "test_score": test_score,
                "training_sharpe": _finite_float(training_row.get("sharpe")),
                "test_sharpe": _finite_float(test_row.get("sharpe")),
                "training_excess_return": _finite_float(training_row.get("excess_return")),
                "test_excess_return": _finite_float(test_row.get("excess_return")),
            }
        )

    if not paired:
        return {
            "objective": objective,
            "combination_count": 0,
            "rank_ic": None,
            "monotonicity": None,
            "top_20_lift": None,
            "groups": [],
            "rows": [],
        }

    training_scores = [float(row["training_score"]) for row in paired]
    test_scores = [float(row["test_score"]) for row in paired]
    training_best_ranks = _average_ranks([-score for score in training_scores])
    test_best_ranks = _average_ranks([-score for score in test_scores])
    for index, row in enumerate(paired):
        row["training_rank"] = training_best_ranks[index]
        row["test_rank"] = test_best_ranks[index]

    rank_ic = _spearman_rank_correlation(training_scores, test_scores)
    group_count = min(maximum_groups, len(paired))
    grouped_rows: list[list[dict[str, Any]]] = [[] for _ in range(group_count)]
    ascending_training_ranks = _average_ranks(training_scores)
    for row, ascending_rank in zip(paired, ascending_training_ranks, strict=True):
        group_index = min(group_count - 1, int((ascending_rank - 1.0) * group_count / len(paired)))
        grouped_rows[group_index].append(row)

    groups: list[dict[str, Any]] = []
    for index, rows in enumerate(grouped_rows, start=1):
        if not rows:
            continue
        group_test_scores = [float(row["test_score"]) for row in rows]
        groups.append(
            {
                "label": f"Q{index}",
                "order": index,
                "count": len(rows),
                "training_score_mean": fmean(float(row["training_score"]) for row in rows),
                "test_score_mean": fmean(group_test_scores),
                "test_score_median": median(group_test_scores),
                "positive_ratio": sum(score > 0 for score in group_test_scores) / len(group_test_scores),
            }
        )
    monotonicity = _spearman_rank_correlation(
        [float(group["order"]) for group in groups],
        [float(group["test_score_mean"]) for group in groups],
    )

    top_count = max(1, ceil(len(paired) * 0.2))
    training_top = sorted(paired, key=lambda row: (-float(row["training_score"]), str(row["label"])))[:top_count]
    top_test_mean = fmean(float(row["test_score"]) for row in training_top)
    all_test_mean = fmean(test_scores)
    training_best = min(paired, key=lambda row: (float(row["training_rank"]), str(row["label"])))
    best_test_score = max(test_scores)
    best_test_rank = float(training_best["test_rank"])
    test_percentile = 100.0 if len(paired) == 1 else (len(paired) - best_test_rank) / (len(paired) - 1) * 100.0

    paired.sort(key=lambda row: (float(row["training_rank"]), str(row["label"])))
    return {
        "objective": objective,
        "combination_count": len(paired),
        "rank_ic": rank_ic,
        "monotonicity": monotonicity,
        "top_20_count": top_count,
        "top_20_test_mean": top_test_mean,
        "all_test_mean": all_test_mean,
        "top_20_lift": top_test_mean - all_test_mean,
        "training_best_test_score": float(training_best["test_score"]),
        "training_best_test_percentile": test_percentile,
        "test_best_score": best_test_score,
        "selection_regret": best_test_score - float(training_best["test_score"]),
        "groups": groups,
        "rows": paired,
    }


def _predictability_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    analyses = [dict(window.get("rank_analysis") or {}) for window in windows if window.get("rank_analysis")]
    rank_ics = [value for analysis in analyses if (value := _finite_float(analysis.get("rank_ic"))) is not None]
    monotonicities = [
        value for analysis in analyses if (value := _finite_float(analysis.get("monotonicity"))) is not None
    ]
    top_lifts = [value for analysis in analyses if (value := _finite_float(analysis.get("top_20_lift"))) is not None]
    ic_deviation = pstdev(rank_ics) if len(rank_ics) > 1 else 0.0

    groups_by_label: dict[str, list[dict[str, Any]]] = {}
    for analysis in analyses:
        for group in list(analysis.get("groups") or []):
            groups_by_label.setdefault(str(group.get("label") or ""), []).append(dict(group))
    aggregate_groups: list[dict[str, Any]] = []
    for label, rows in sorted(groups_by_label.items(), key=lambda item: int(item[0][1:]) if item[0][1:].isdigit() else 999):
        test_means = [value for row in rows if (value := _finite_float(row.get("test_score_mean"))) is not None]
        training_means = [value for row in rows if (value := _finite_float(row.get("training_score_mean"))) is not None]
        if not test_means:
            continue
        aggregate_groups.append(
            {
                "label": label,
                "order": int(label[1:]) if label[1:].isdigit() else len(aggregate_groups) + 1,
                "window_count": len(test_means),
                "training_score_mean": fmean(training_means) if training_means else None,
                "test_score_mean": fmean(test_means),
                "test_score_median": median(test_means),
                "positive_window_ratio": sum(value > 0 for value in test_means) / len(test_means),
            }
        )
    group_monotonicity = _spearman_rank_correlation(
        [float(group["order"]) for group in aggregate_groups],
        [float(group["test_score_mean"]) for group in aggregate_groups],
    )
    return {
        "window_count": len(analyses),
        "valid_rank_ic_windows": len(rank_ics),
        "mean_rank_ic": fmean(rank_ics) if rank_ics else None,
        "median_rank_ic": median(rank_ics) if rank_ics else None,
        "rank_ic_std": ic_deviation if rank_ics else None,
        "icir": fmean(rank_ics) / ic_deviation if rank_ics and ic_deviation > 0 else None,
        "positive_rank_ic_ratio": sum(value > 0 for value in rank_ics) / len(rank_ics) if rank_ics else None,
        "mean_top_20_lift": fmean(top_lifts) if top_lifts else None,
        "mean_monotonicity": fmean(monotonicities) if monotonicities else None,
        "positive_monotonicity_ratio": (
            sum(value > 0 for value in monotonicities) / len(monotonicities) if monotonicities else None
        ),
        "group_monotonicity": group_monotonicity,
        "groups": aggregate_groups,
    }


def run_pool_walk_forward(
    pool_item_id: str,
    *,
    training_start_date: str | None = None,
    training_months: int = 24,
    test_months: int = 6,
    selected_parameters: list[str],
    parameter_ranges: dict[str, Any],
    objective: str = "sharpe",
    max_trials: int = 100,
) -> dict[str, Any]:
    objective = str(objective or "sharpe").strip().lower()
    if objective not in ALLOWED_OBJECTIVES:
        raise ValueError("滚动优化第一版仅支持 Sharpe 评分")
    training_months = int(training_months)
    test_months = int(test_months)
    if training_months < 6 or training_months > 120:
        raise ValueError("训练窗口需要控制在 6～120 个月")
    if test_months != 6:
        raise ValueError("滚动优化第一版的样本外窗口固定为 6 个月")

    detail = pool_service.get_pool_item_detail(pool_item_id)
    strategy_research_service._safe_pool_path(detail)
    inventory, parameters = strategy_research_service._parameter_inventory(detail)
    parameter_by_name = {str(item["name"]): item for item in parameters}
    selected = list(dict.fromkeys(str(name).strip() for name in selected_parameters if str(name).strip()))
    if not selected or len(selected) > 3:
        raise ValueError("请选择 1～3 个滚动优化参数")
    missing = [name for name in selected if name not in parameter_by_name]
    if missing:
        raise ValueError(f"不可研究的参数：{', '.join(missing)}")

    parameter_space: dict[str, Any] = {}
    combination_count = 1
    for name in selected:
        spec, values = strategy_research_service._validated_range(name, parameter_ranges.get(name), parameter_by_name[name])
        parameter_space[name] = spec
        combination_count *= len(values)
    if combination_count < 2 or combination_count > min(100, int(max_trials)):
        raise ValueError(f"滚动优化每期参数组合需要控制在 2～{min(100, int(max_trials))} 组")

    item = dict(detail.get("pool_item") or {})
    config = dict(detail.get("config") or {})
    strategy_code = str(detail.get("strategy_code") or "")
    class_name = strategy_research_service._class_name(strategy_code, detail, inventory)
    vt_symbol = str(item.get("vt_symbol") or config.get("vt_symbol") or "").strip()
    if not class_name or not vt_symbol:
        raise ValueError("策略池快照缺少可执行类名或标的信息")

    configured_start = _parse_date(config.get("start_date"), "回测开始日期")
    research_end = _parse_date(config.get("end_date"), "回测结束日期")
    research_start = _parse_date(training_start_date, "训练开始日期") if training_start_date else configured_start
    if research_start < configured_start:
        raise ValueError(f"训练开始日期不能早于策略回测开始日期 {configured_start.isoformat()}")
    if research_start > research_end:
        raise ValueError("训练开始日期不能晚于策略回测结束日期")
    windows = _build_windows(research_start, research_end, training_months, test_months)
    if not windows:
        required_months = training_months + test_months
        raise ValueError(f"当前回测区间不足以形成完整窗口，至少需要 {required_months} 个月数据")

    task = task_service.create_task(
        TaskType.STRATEGY_RESEARCH.value,
        message=f"滚动优化排队中 · {len(windows)} 个窗口",
        related_strategy_id=str(item.get("strategy_id") or "") or None,
        related_pool_item_id=pool_item_id,
    )
    task_service.mark_running(task["task_id"], message=f"滚动优化进行中 0/{len(windows)} 个窗口")
    total_steps = len(windows) * (combination_count + 2)
    completed_steps = 0
    window_results: list[dict[str, Any]] = []
    stitched_curve: list[dict[str, Any]] = []
    fixed_curve: list[dict[str, Any]] = []
    fixed_parameters = {**dict(inventory.get("base_parameters") or {}), "fixed_size": 1}

    try:
        for window_index, window in enumerate(windows, start=1):
            train_config = {
                **config,
                "start_date": window["train_start"],
                "end_date": window["train_end"],
                "mode": "real",
                "execution_mode": "real_backtest",
                "is_real_backtest": True,
                "max_trials": combination_count,
            }

            def progress_callback(current: int, count: int, message: str, *, base: int = completed_steps) -> None:
                progress = (base + current) / max(1, total_steps)
                task_service.mark_progress(
                    task["task_id"],
                    progress,
                    message=f"滚动优化窗口 {window_index}/{len(windows)} · 训练 {current}/{count} 组",
                )

            optimization = optimize_parameters(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                base_parameters={**dict(inventory.get("base_parameters") or {}), "fixed_size": 1},
                parameter_space=parameter_space,
                backtest_config=train_config,
                objective=objective,
                options={
                    "method": "manual_grid",
                    "selected_parameters": selected,
                    "max_trials": combination_count,
                    "progress_callback": progress_callback,
                },
            )
            if not optimization.get("success"):
                raise RuntimeError(str(optimization.get("error") or f"第 {window_index} 个训练窗口优化失败"))
            completed_steps += combination_count

            recommended = dict(optimization.get("recommended") or {})
            chosen_parameters = dict(recommended.get("parameters") or {})
            if not chosen_parameters:
                raise RuntimeError(f"第 {window_index} 个训练窗口没有返回推荐参数")

            test_config = {
                **config,
                "start_date": window["test_start"],
                "end_date": window["test_end"],
                "mode": "real",
                "execution_mode": "real_backtest",
                "is_real_backtest": True,
                "max_trials": combination_count,
            }

            test_result = backtesting.run_backtest(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                parameters=chosen_parameters,
                config=test_config,
            )
            if not test_result.get("success"):
                raise RuntimeError(str(test_result.get("error") or f"第 {window_index} 个样本外窗口回测失败"))
            completed_steps += 1

            fixed_result = backtesting.run_backtest(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                parameters=fixed_parameters,
                config=test_config,
            )
            if not fixed_result.get("success"):
                raise RuntimeError(str(fixed_result.get("error") or f"第 {window_index} 个固定参数对照回测失败"))
            completed_steps += 1
            task_service.mark_progress(
                task["task_id"],
                completed_steps / max(1, total_steps),
                message=f"滚动优化已完成 {window_index}/{len(windows)} 个窗口",
            )

            test_curve = list(test_result.get("daily_results") or [])
            fixed_test_curve = list(fixed_result.get("daily_results") or [])
            selected_values = {name: chosen_parameters.get(name) for name in selected}
            for row in test_curve:
                stitched_curve.append({**dict(row), "walk_forward_window": window_index})
            for row in fixed_test_curve:
                fixed_curve.append({**dict(row), "walk_forward_window": window_index})
            window_results.append(
                {
                    "index": window_index,
                    **window,
                    "selected_parameters": selected_values,
                    "train_score": recommended.get("score"),
                    "train_metrics": dict(recommended.get("metrics") or {}),
                    "training_grid_summary": list(optimization.get("grid_summary") or []),
                    "test_metrics": enrich_metrics_with_curve_returns(dict(test_result.get("metrics") or {}), test_curve),
                    "fixed_test_metrics": enrich_metrics_with_curve_returns(dict(fixed_result.get("metrics") or {}), fixed_test_curve),
                    "test_days": len(test_curve),
                }
            )

        stitched_curve.sort(key=lambda row: str(row.get("date") or ""))
        fixed_curve.sort(key=lambda row: str(row.get("date") or ""))
        capital = float(config.get("capital") or 100000.0)
        annual_days = int(config.get("annual_days") or 240)
        experiment_id = f"walk_forward_{now_beijing().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        payload = {
            "type": "walk_forward",
            "experiment_id": experiment_id,
            "pool_item_id": pool_item_id,
            "created_at": now_beijing().isoformat(),
            "objective": objective,
            "training_start_date": research_start.isoformat(),
            "training_months": training_months,
            "test_months": test_months,
            "selected_parameters": selected,
            "parameter_ranges": parameter_space,
            "combination_count": combination_count,
            "window_count": len(window_results),
            "windows": window_results,
            "curve": stitched_curve,
            "fixed_parameters": fixed_parameters,
            "fixed_curve": fixed_curve,
            "metrics": _stitched_metrics(stitched_curve, capital, annual_days),
            "fixed_metrics": _stitched_metrics(fixed_curve, capital, annual_days),
            "notes": [
                "每个样本外窗口使用训练期选出的参数独立冷启动。",
                "样本外窗口之间不传递策略内部状态或持仓。",
                "固定参数对照使用策略池快照参数，并采用完全相同的样本外窗口和独立冷启动规则。",
                "训练期完整参数网格随结果保存；样本外完整横截面与 Rank IC 可在结果页按需计算。",
            ],
        }
        experiment_dir = strategy_research_service._safe_research_dir(pool_item_id) / experiment_id
        strategy_research_service._write_json_atomic(experiment_dir / "result.json", payload)
        completed = task_service.mark_completed(task["task_id"], message=f"滚动优化完成 · {len(window_results)} 个窗口")
        return {**payload, "task": completed}
    except Exception as exc:
        task_service.mark_failed(task["task_id"], error=str(exc), message="滚动优化失败")
        raise


def run_walk_forward_rank_analysis(pool_item_id: str, experiment_id: str) -> dict[str, Any]:
    research_root = RESEARCH_ROOT.resolve()
    result_path = (research_root / pool_item_id / experiment_id / "result.json").resolve()
    try:
        result_path.relative_to(research_root)
    except ValueError as exc:
        raise ValueError("滚动优化研究结果路径不安全") from exc
    if not result_path.is_file():
        raise FileNotFoundError(f"滚动优化研究结果不存在：{experiment_id}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("滚动优化研究结果无法读取") from exc
    if payload.get("type") != "walk_forward" or str(payload.get("pool_item_id") or "") != pool_item_id:
        raise ValueError("指定结果不是当前策略的滚动优化实验")

    windows = [dict(window) for window in list(payload.get("windows") or [])]
    if payload.get("parameter_predictability") and windows and all(window.get("rank_analysis") for window in windows):
        return {**payload, "cached": True}
    if not windows:
        raise ValueError("滚动优化结果没有可分析的完整窗口")

    detail = pool_service.get_pool_item_detail(pool_item_id)
    strategy_research_service._safe_pool_path(detail)
    inventory, parameters = strategy_research_service._parameter_inventory(detail)
    parameter_by_name = {str(item["name"]): item for item in parameters}
    selected = list(dict.fromkeys(str(name).strip() for name in list(payload.get("selected_parameters") or []) if str(name).strip()))
    if not selected or len(selected) > 3:
        raise ValueError("滚动优化结果缺少有效的优化参数")
    missing = [name for name in selected if name not in parameter_by_name]
    if missing:
        raise ValueError(f"不可研究的参数：{', '.join(missing)}")

    stored_space = dict(payload.get("parameter_ranges") or {})
    parameter_space: dict[str, Any] = {}
    combination_count = 1
    for name in selected:
        spec, values = strategy_research_service._validated_range(name, stored_space.get(name), parameter_by_name[name])
        parameter_space[name] = spec
        combination_count *= len(values)
    if combination_count < 2 or combination_count > 100:
        raise ValueError("全量样本外分析的参数组合需要控制在 2～100 组")

    item = dict(detail.get("pool_item") or {})
    config = dict(detail.get("config") or {})
    strategy_code = str(detail.get("strategy_code") or "")
    class_name = strategy_research_service._class_name(strategy_code, detail, inventory)
    vt_symbol = str(item.get("vt_symbol") or config.get("vt_symbol") or "").strip()
    if not class_name or not vt_symbol:
        raise ValueError("策略池快照缺少可执行类名或标的信息")

    missing_training_count = sum(not list(window.get("training_grid_summary") or []) for window in windows)
    total_steps = combination_count * (len(windows) + missing_training_count)
    task = task_service.create_task(
        TaskType.STRATEGY_RESEARCH.value,
        message=f"全量样本外分析排队中 · {len(windows)} 个窗口",
        related_strategy_id=str(item.get("strategy_id") or "") or None,
        related_pool_item_id=pool_item_id,
    )
    task_service.mark_running(task["task_id"], message=f"全量样本外分析进行中 0/{len(windows)} 个窗口")
    completed_steps = 0
    base_parameters = {**dict(inventory.get("base_parameters") or {}), "fixed_size": 1}
    objective = "sharpe"

    try:
        for window_index, window in enumerate(windows, start=1):
            training_rows = list(window.get("training_grid_summary") or [])
            if not training_rows:
                train_config = {
                    **config,
                    "start_date": window["train_start"],
                    "end_date": window["train_end"],
                    "mode": "real",
                    "execution_mode": "real_backtest",
                    "is_real_backtest": True,
                    "max_trials": combination_count,
                }

                def training_progress(current: int, count: int, message: str, *, base: int = completed_steps) -> None:
                    task_service.mark_progress(
                        task["task_id"],
                        (base + current) / max(1, total_steps),
                        message=f"全量样本外 {window_index}/{len(windows)} · 补算训练横截面 {current}/{count} 组",
                    )

                training_evaluation = optimize_parameters(
                    strategy_code=strategy_code,
                    class_name=class_name,
                    vt_symbol=vt_symbol,
                    base_parameters=base_parameters,
                    parameter_space=parameter_space,
                    backtest_config=train_config,
                    objective=objective,
                    options={
                        "method": "manual_grid",
                        "selected_parameters": selected,
                        "max_trials": combination_count,
                        "progress_callback": training_progress,
                    },
                )
                if not training_evaluation.get("success"):
                    raise RuntimeError(str(training_evaluation.get("error") or f"第 {window_index} 个训练横截面失败"))
                training_rows = list(training_evaluation.get("grid_summary") or [])
                window["training_grid_summary"] = training_rows
                completed_steps += combination_count

            test_config = {
                **config,
                "start_date": window["test_start"],
                "end_date": window["test_end"],
                "mode": "real",
                "execution_mode": "real_backtest",
                "is_real_backtest": True,
                "max_trials": combination_count,
            }

            def test_progress(current: int, count: int, message: str, *, base: int = completed_steps) -> None:
                task_service.mark_progress(
                    task["task_id"],
                    (base + current) / max(1, total_steps),
                    message=f"全量样本外 {window_index}/{len(windows)} · 测试横截面 {current}/{count} 组",
                )

            test_evaluation = optimize_parameters(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                base_parameters=base_parameters,
                parameter_space=parameter_space,
                backtest_config=test_config,
                objective=objective,
                options={
                    "method": "manual_grid",
                    "selected_parameters": selected,
                    "max_trials": combination_count,
                    "progress_callback": test_progress,
                },
            )
            if not test_evaluation.get("success"):
                raise RuntimeError(str(test_evaluation.get("error") or f"第 {window_index} 个样本外参数横截面失败"))
            completed_steps += combination_count
            window["rank_analysis"] = _parameter_rank_analysis(
                training_rows,
                list(test_evaluation.get("grid_summary") or []),
                objective=objective,
            )
            task_service.mark_progress(
                task["task_id"],
                completed_steps / max(1, total_steps),
                message=f"全量样本外已完成 {window_index}/{len(windows)} 个窗口",
            )

        payload["windows"] = windows
        payload["parameter_predictability"] = _predictability_summary(windows)
        payload["rank_analysis_created_at"] = now_beijing().isoformat()
        notes = [str(note) for note in list(payload.get("notes") or [])]
        analysis_note = "参数 Rank IC 与分组单调性使用训练期和对应样本外期的完整参数横截面计算。"
        if analysis_note not in notes:
            notes.append(analysis_note)
        payload["notes"] = notes
        strategy_research_service._write_json_atomic(result_path, payload)
        completed = task_service.mark_completed(task["task_id"], message=f"全量样本外分析完成 · {len(windows)} 个窗口")
        return {**payload, "task": completed, "cached": False}
    except Exception as exc:
        task_service.mark_failed(task["task_id"], error=str(exc), message="全量样本外分析失败")
        raise
