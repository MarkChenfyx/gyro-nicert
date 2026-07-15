import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Checkbox, Drawer, Input, InputNumber, Modal, Progress, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  addToPool,
  archiveTerminalTasks,
  comparePool,
  createNaturalLanguageSource,
  createResearchBaseline,
  createResearchBaselineFromCode,
  downloadData,
  generateStrategy,
  getDataCoverage,
  getNaturalLanguageSource,
  getOptimizationMethods,
  getOptimizationSearchSpace,
  suggestOptimizationSearchSpace,
  getPoolItem,
  getVariantCurve,
  getRun,
  listRuns,
  listNaturalLanguageSources,
  listPool,
  listTasks,
  removeFromPool,
  rerunPool,
  runOptimization,
  updateNaturalLanguageSource
} from "../api";
import {
  PageKey,
  PAGE_STORAGE_KEY,
  OPTIMIZE_DRAFT_STORAGE_KEY,
  BENCHMARK_CURVE_COLOR,
  TaskStatusValue,
  TaskView,
  WorkbenchTask,
  TASK_TYPE_LABELS,
  TASK_STATUS_LABELS,
  taskTypeLabel,
  taskDisplayLabel,
  taskSummary,
  taskStatusLabel,
  taskProgress,
  taskTargetPage,
  elapsedLabel,
  taskDateGroup,
  isPageKey,
  loadInitialPage,
  loadOptimizeDraft,
  zh,
  SOURCE_FILES,
  SourceFile,
  LocalStrategyFile,
  WorkflowUiState,
  formatDate,
  strategyFamily,
  strategyVersion,
  strategyLabel,
  formatNumber,
  formatPercent,
  formatReturnPct,
  cleanOptimizationNumber,
  optimizationPrecision,
  formatParameterValue,
  summarizeParameters,
  statusClass,
  extractMissingRanges,
  missingRangeLabel,
  parseLaunchVtSymbol,
  NormalizedCurvePoint,
  NormalizedCurveSeries,
  buildDrawdownSeries,
  finiteNumber,
  drawdownMetricValue,
  rowDate,
  normalizeDateKey,
  clampDateRange,
  shiftDate,
  curveDateBoundsForRows,
  shortcutDateRange,
  valueFromKeys,
  closeValue,
  referenceClose,
  cumulativeStrategySeries,
  cumulativeBuyHoldSeries,
  buildStrategyCurve,
  buildNormalizedCurveSeries,
  variantDisplayLabel,
  curveSeriesColor,
  curveColorForKey,
  buildCumulativeChartOption,
  curveSummary,
  CurveChart,
  buildComparisonSeries,
  MultiVariantCurveChart,
  Sidebar,
  LaunchFlowPage,
  CurveControlItem,
  CurveControls,
  StrategyGenerationPage
} from "../app/App";


function variantCurveDateBounds(curves: Record<string, any[]>) {
  const dates = Object.values(curves)
    .flatMap((rows) => rows.map((row) => normalizeDateKey(rowDate(row))))
    .filter(Boolean)
    .sort();
  const dataMax = dates[dates.length - 1] || "";
  return { min: dates[0] || "", max: dataMax };
}


export default function ParameterOptimizationPage({
  lastResearch,
  refreshPool,
  onOpenPool,
  refreshTasks
}: {
  lastResearch: any;
  refreshPool: () => Promise<void>;
  onOpenPool: () => void;
  refreshTasks: () => Promise<void>;
}) {
  const persistedDraft = useMemo(() => loadOptimizeDraft(), []);
  const [runs, setRuns] = useState<any[]>([]);
  const [methods, setMethods] = useState<any[]>([]);
  const [selectedFamily, setSelectedFamily] = useState(String(persistedDraft.selectedFamily || ""));
  const [runId, setRunId] = useState(String(persistedDraft.runId || lastResearch?.baseline?.run?.run_id || ""));
  const [method, setMethod] = useState(String(persistedDraft.method || "manual_grid"));
  const [objective, setObjective] = useState(String(persistedDraft.objective || "sharpe"));
  const [poolVariant, setPoolVariant] = useState(String(persistedDraft.poolVariant || "manual_grid"));
  const [searchSpace, setSearchSpace] = useState<any>(null);
  const [selectedParams, setSelectedParams] = useState<string[]>(Array.isArray(persistedDraft.selectedParams) ? persistedDraft.selectedParams.map(String) : []);
  const [ranges, setRanges] = useState<Record<string, any>>(persistedDraft.ranges && typeof persistedDraft.ranges === "object" ? persistedDraft.ranges : {});
  const [runDetail, setRunDetail] = useState<any>(null);
  const [variantCurves, setVariantCurves] = useState<Record<string, any[]>>({});
  const [visibleCurveKeys, setVisibleCurveKeys] = useState<string[]>(Array.isArray(persistedDraft.visibleCurveKeys) ? persistedDraft.visibleCurveKeys.map(String) : []);
  const [curveStartDate, setCurveStartDate] = useState(String(persistedDraft.curveStartDate || ""));
  const [curveEndDate, setCurveEndDate] = useState(String(persistedDraft.curveEndDate || ""));
  const [optimizationResult, setOptimizationResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionProgress, setSuggestionProgress] = useState(0);
  const [spaceSuggestion, setSpaceSuggestion] = useState<any>(null);
  const [poolStrategyName, setPoolStrategyName] = useState("");
  const [addingToPool, setAddingToPool] = useState(false);
  const runContextRequestRef = useRef(0);

  useEffect(() => {
    if (!suggestionLoading) return;
    const timer = window.setInterval(() => {
      setSuggestionProgress((current) => Math.min(92, current + Math.max(1, Math.ceil((92 - current) * 0.12))));
    }, 180);
    return () => window.clearInterval(timer);
  }, [suggestionLoading]);

  async function refreshRuns(defaultRunId?: string) {
    const payload = await listRuns();
    const nextRuns = payload.runs || [];
    setRuns(nextRuns);
    const preferred = defaultRunId || runId || lastResearch?.baseline?.run?.run_id || nextRuns[0]?.run_id || "";
    const preferredRun = nextRuns.find((item: any) => item.run_id === preferred) || nextRuns[0];
    const preferredFamily = strategyFamily(preferredRun);
    if (preferredFamily) setSelectedFamily(preferredFamily);
    if (preferred && preferred !== runId) setRunId(preferred);
  }

  async function loadRunContext(nextRunId: string, useCachedSuggestion = true, reuseDraftParams = true) {
    if (!nextRunId) return;
    const requestId = ++runContextRequestRef.current;
    const [detail, space] = await Promise.all([
      getRun(nextRunId),
      getOptimizationSearchSpace(nextRunId, "baseline")
    ]);
    const availableVariants = Array.from(
      new Set([
        "baseline",
        ...((detail.variants || []).map((item: any) => String(item.variant_name || "")).filter(Boolean))
      ])
    );
    const curvePayloads = await Promise.all(
      availableVariants.map((name: string) =>
        getVariantCurve(nextRunId, name)
          .then((payload) => [name, payload.data || []] as const)
          .catch(() => [name, []] as const)
      )
    );
    const nextCurves = Object.fromEntries(curvePayloads);
    if (requestId !== runContextRequestRef.current) return;
    const nextCurveDateBounds = variantCurveDateBounds(nextCurves);
    const defaultPoolVariant = availableVariants.find((name: string) => name !== "baseline") || "baseline";
    const storedDraft = loadOptimizeDraft();
    const shouldReuseDraft = String(storedDraft.runId || "") === nextRunId;
    const shouldReuseDraftParams = shouldReuseDraft && reuseDraftParams;
    const cachedSuggestion = useCachedSuggestion && space.cached_suggestion ? space.cached_suggestion : null;
    const editableRows = cachedSuggestion
      ? [
          ...(cachedSuggestion.parameters || []),
          ...(cachedSuggestion.excluded_parameters || []).filter((item: any) => item.low !== undefined && item.high !== undefined)
        ]
      : (space.parameters || []);
    const effectiveSpace = { ...space, parameters: editableRows };
    const parameterNames = editableRows.map((item: any) => String(item.name));
    const virtualNames = (cachedSuggestion?.virtual_parameters || []).map((item: any) => String(item.name));
    const selectableNames = [...parameterNames, ...virtualNames];
    setRunDetail(detail);
    setSearchSpace(effectiveSpace);
    setSpaceSuggestion(cachedSuggestion);
    setVariantCurves(nextCurves);
    const storedStartDate = String(storedDraft.curveStartDate || "");
    const storedEndDate = String(storedDraft.curveEndDate || "");
    const reusableStartDate = shouldReuseDraft
      && storedStartDate >= nextCurveDateBounds.min
      && storedStartDate <= nextCurveDateBounds.max;
    const reusableEndDate = shouldReuseDraft
      && storedEndDate >= nextCurveDateBounds.min
      && storedEndDate <= nextCurveDateBounds.max;
    setCurveStartDate(reusableStartDate ? storedStartDate : nextCurveDateBounds.min);
    setCurveEndDate(reusableEndDate ? storedEndDate : nextCurveDateBounds.max);
    setVisibleCurveKeys(() => {
      if (shouldReuseDraft && Array.isArray(storedDraft.visibleCurveKeys)) {
        const allowed = new Set([...availableVariants, "buy_hold"]);
        const kept = storedDraft.visibleCurveKeys.map(String).filter((key: string) => allowed.has(key));
        if (kept.length) return Array.from(new Set([...kept, ...availableVariants, "buy_hold"]));
      }
      return Array.from(new Set([...availableVariants, "buy_hold"]));
    });
    setPoolVariant((current) => {
      const preferred = shouldReuseDraft ? String(storedDraft.poolVariant || current || defaultPoolVariant) : current;
      return availableVariants.includes(preferred) ? preferred : defaultPoolVariant;
    });
    const nextRanges: Record<string, any> = {};
    for (const item of editableRows) {
      nextRanges[item.name] = { low: item.low, high: item.high, step: item.step, type: item.type };
    }
    if (shouldReuseDraftParams && storedDraft.ranges && typeof storedDraft.ranges === "object") {
      for (const name of parameterNames) {
        if (storedDraft.ranges[name] && typeof storedDraft.ranges[name] === "object") {
          nextRanges[name] = { ...nextRanges[name], ...storedDraft.ranges[name] };
        }
      }
    }
    setRanges(nextRanges);
    setSelectedParams(
      shouldReuseDraftParams && Array.isArray(storedDraft.selectedParams)
        ? storedDraft.selectedParams.map(String).filter((name: string) => selectableNames.includes(name))
        : cachedSuggestion
          ? [
              ...(cachedSuggestion.parameters || []).filter((item: any) => item.optimize !== false).map((item: any) => String(item.name)),
              ...(cachedSuggestion.virtual_parameters || []).filter((item: any) => item.optimize !== false).map((item: any) => String(item.name))
            ]
          : []
    );
  }

  useEffect(() => {
    getOptimizationMethods().then((payload) => setMethods(payload.methods || [])).catch((error) => message.error(String(error)));
    refreshRuns(lastResearch?.baseline?.run?.run_id).catch((error) => message.error(String(error)));
  }, [lastResearch?.baseline?.run?.run_id]);

  const families = useMemo(
    () => Array.from(new Set(runs.map((item) => strategyFamily(item)).filter(Boolean))),
    [runs]
  );
  const familyRuns = useMemo(
    () => runs.filter((item) => !selectedFamily || strategyFamily(item) === selectedFamily),
    [runs, selectedFamily]
  );

  useEffect(() => {
    if (!families.length) {
      if (selectedFamily) setSelectedFamily("");
      return;
    }
    if (!selectedFamily || !families.includes(selectedFamily)) {
      setSelectedFamily(families[0]);
    }
  }, [families, selectedFamily]);

  useEffect(() => {
    if (!familyRuns.length) {
      if (runId) setRunId("");
      return;
    }
    if (!familyRuns.some((item) => item.run_id === runId)) {
      setRunId(familyRuns[0]?.run_id || "");
    }
  }, [familyRuns, runId]);

  useEffect(() => {
    if (!runId) return;
    setOptimizationResult((current: any) => (String(current?.run?.run_id || "") === runId ? current : null));
    loadRunContext(runId).catch((error) => message.error(String(error)));
  }, [runId]);

  const currentRun = runs.find((item) => item.run_id === runId);
  useEffect(() => {
    setPoolStrategyName(String(currentRun?.strategy_name || runDetail?.strategy?.strategy_name || ""));
  }, [currentRun?.strategy_name, runDetail?.strategy?.strategy_name]);
  const optimizationRunId = String(optimizationResult?.run?.run_id || "");
  const optimizationObjective = String(optimizationResult?.objective || optimizationResult?.optimization?.objective || "");
  const optimizationMatchesRun = Boolean(optimizationResult) && optimizationRunId === runId;
  const optimizationMatchesObjective = !optimizationObjective || optimizationObjective === objective;
  const variants = useMemo(
    () => Array.from(new Set((runDetail?.variants || []).map((item: any) => String(item.variant_name || "")).filter(Boolean))),
    [runDetail]
  );
  const curveVariantNames = useMemo(() => Object.keys(variantCurves), [variantCurves]);
  const curveDateBounds = useMemo(() => variantCurveDateBounds(variantCurves), [variantCurves]);
  const filteredVariantCurves = useMemo(
    () => Object.fromEntries(Object.entries(variantCurves).map(([name, rows]) => [name, clampDateRange(rows, curveStartDate, curveEndDate)])),
    [curveEndDate, curveStartDate, variantCurves]
  );
  const primaryVariant = useMemo(
    () => curveVariantNames.find((name) => name !== "baseline") || curveVariantNames[0] || "baseline",
    [curveVariantNames]
  );
  const curveRows = useMemo(
    () => filteredVariantCurves[primaryVariant] || filteredVariantCurves.baseline || [],
    [filteredVariantCurves, primaryVariant]
  );
  const activeMethod = methods.find((item) => item.method === method);
  const variantMetrics = useMemo(() => curveSummary(curveRows), [curveRows]);
  const baselineMetrics = useMemo(
    () => runDetail?.baseline_result?.metrics || runDetail?.baseline_result || {},
    [runDetail]
  );
  const totalGridCount = useMemo(() => {
    if (!selectedParams.length) return 0;
    return selectedParams.reduce((product, name) => {
      const spec = ranges[name] || {};
      const virtual = (spaceSuggestion?.virtual_parameters || []).find((item: any) => item.name === name);
      if (virtual) return product * Math.max(1, (virtual.choices || []).length);
      const low = Number(spec.low);
      const high = Number(spec.high);
      const step = Number(spec.step);
      if (!Number.isFinite(low) || !Number.isFinite(high) || !Number.isFinite(step) || step <= 0 || high < low) return 0;
      return product * Math.max(1, Math.floor((high - low) / step + 1.0000001));
    }, 1);
  }, [ranges, selectedParams, spaceSuggestion]);

  const poolVariantMetrics = useMemo(() => {
    if (poolVariant === "baseline") return baselineMetrics;
    if (optimizationMatchesRun && optimizationResult?.selected_variant === poolVariant) {
      return optimizationResult?.optimization?.metrics || {};
    }
    return runDetail?.variant_results?.[poolVariant]?.metrics || runDetail?.variant_results?.[poolVariant] || {};
  }, [baselineMetrics, optimizationMatchesRun, optimizationResult, poolVariant, runDetail]);

  const poolVariantTradeCount = useMemo(() => {
    if (poolVariant === "baseline") return runDetail?.baseline_trades_count;
    if (optimizationMatchesRun && optimizationResult?.selected_variant === poolVariant) {
      return optimizationResult?.optimization?.trade_count;
    }
    return runDetail?.variant_trade_counts?.[poolVariant];
  }, [optimizationMatchesRun, optimizationResult, poolVariant, runDetail]);

  function updateRange(name: string, key: string, value: number | null) {
    setRanges((current) => ({ ...current, [name]: { ...(current[name] || {}), [key]: cleanOptimizationNumber(value) } }));
  }

  async function generateSpaceSuggestion() {
    if (!runId) return;
    setSuggestionProgress(6);
    setSuggestionLoading(true);
    try {
      const payload = await suggestOptimizationSearchSpace(runId, "baseline", true);
      const editableRows = [
        ...(payload.parameters || []),
        ...(payload.excluded_parameters || []).filter((item: any) => item.low !== undefined && item.high !== undefined)
      ];
      setSpaceSuggestion(payload);
      setSearchSpace((current: any) => ({ ...current, parameters: editableRows }));
      setRanges(Object.fromEntries(editableRows.map((item: any) => [item.name, {
        low: item.low,
        high: item.high,
        step: item.step,
        type: item.type,
        scale: item.scale || "linear"
      }])));
      setSelectedParams([
        ...(payload.parameters || []).filter((item: any) => item.optimize !== false).map((item: any) => String(item.name)),
        ...(payload.virtual_parameters || []).filter((item: any) => item.optimize !== false).map((item: any) => String(item.name))
      ]);
      if (payload.fallback_used) {
        message.warning(payload.diagnostics?.[0]?.message || "AI 建议不可用，已恢复静态范围");
      } else {
        message.success("AI 优化建议已生成，请确认后再运行");
      }
      setSuggestionProgress(100);
    } catch (error) {
      setSuggestionProgress(100);
      message.error(String(error));
    } finally {
      setSuggestionLoading(false);
      window.setTimeout(() => setSuggestionProgress(0), 700);
    }
  }

  async function restoreStaticSpace() {
    if (!runId) return;
    await loadRunContext(runId, false, false);
    message.success("已恢复平台默认范围");
  }

  async function submitOptimization() {
    if (!runId) {
      message.error("请先选择一个运行版本");
      return;
    }
    const selected = ["auto", "optuna"].includes(method) && selectedParams.length === 0
      ? (searchSpace?.parameters || []).map((item: any) => item.name)
      : selectedParams;
    if (!selected.length) {
      message.error("请至少选择一个参数");
      return;
    }
    setLoading(true);
    try {
      await refreshTasks();
      const payload = await runOptimization({
        run_id: runId,
        variant_name: "baseline",
        method,
        selected_parameters: selected,
        parameter_ranges: Object.fromEntries(selected.filter((name: string) => ranges[name]).map((name: string) => [name, ranges[name]])),
        constraints: spaceSuggestion?.constraints || [],
        virtual_parameters: spaceSuggestion?.virtual_parameters || [],
        objective,
        max_trials: 200
      });
      if (payload.error) {
        message.error(payload.error);
      } else {
        message.success("参数优化完成");
        setOptimizationResult(payload);
        setPoolVariant(payload.selected_variant || activeMethod?.variant_name || "manual_grid");
        await loadRunContext(runId);
      }
      await refreshTasks();
    } catch (error) {
      message.error(String(error));
      await refreshTasks().catch(() => undefined);
    } finally {
      setLoading(false);
    }
  }

  async function addSelectedVariantToPool() {
    if (!runId) return;
    setAddingToPool(true);
    try {
      const payload = await addToPool(runId, poolVariant, currentRun?.vt_symbol, poolStrategyName.trim() || undefined);
      await Promise.all([refreshPool(), refreshTasks()]);
      if (payload?.rerun_succeeded) {
        const rerunStart = String(payload?.rerun?.items?.[0]?.rerun_start || "").trim();
        const rerunEnd = String(payload?.rerun?.rerun_end || payload?.rerun?.items?.[0]?.rerun_end || "").trim();
        message.success(rerunStart && rerunEnd ? `已入池并完成 ${formatDate(rerunStart)} 至 ${formatDate(rerunEnd)} 回测` : "已入池并完成全区间回测");
      } else {
        const diagnostic = String(payload?.rerun?.diagnostics?.[0]?.message || "自动重跑未完成");
        message.warning(`已加入策略池，但${diagnostic}`);
      }
      onOpenPool();
    } catch (error) {
      message.error(String(error));
    } finally {
      setAddingToPool(false);
    }
  }

  const parameterColumns: ColumnsType<any> = [
    {
      title: "",
      width: 48,
      render: (_, record) => (
        <Checkbox
          checked={selectedParams.includes(record.name)}
          onChange={(event) => {
            setSelectedParams((current) => event.target.checked ? [...current, record.name] : current.filter((item) => item !== record.name));
          }}
        />
      )
    },
    { title: zh.paramName, dataIndex: "name", render: (value, record) => <div className="param-name-cell"><strong>{value}</strong><span>{record.category || record.role}</span>{record.reason && <small>{record.reason}</small>}</div> },
    { title: zh.currentValue, dataIndex: "current", render: (value) => String(value) },
    { title: "下限", dataIndex: "low", render: (_, record) => <InputNumber value={ranges[record.name]?.low} precision={optimizationPrecision(ranges[record.name]?.step)} step={ranges[record.name]?.step || 1} onChange={(value) => updateRange(record.name, "low", value)} /> },
    { title: "上限", dataIndex: "high", render: (_, record) => <InputNumber value={ranges[record.name]?.high} precision={optimizationPrecision(ranges[record.name]?.step)} step={ranges[record.name]?.step || 1} onChange={(value) => updateRange(record.name, "high", value)} /> },
    { title: "步长", dataIndex: "step", render: (_, record) => <InputNumber value={ranges[record.name]?.step} precision={optimizationPrecision(ranges[record.name]?.step)} step={record.type === "int" ? 1 : 0.001} onChange={(value) => updateRange(record.name, "step", value)} /> },
    { title: "类型", dataIndex: "type" }
  ];

  const performanceColumns: ColumnsType<any> = [
    { title: "版本", dataIndex: "label", width: 180 },
    { title: "策略累计收益", dataIndex: "strategy_return", width: 130, render: (value) => formatReturnPct(value, 2) },
    { title: "buy & hold", dataIndex: "benchmark_return", width: 120, render: (value) => formatReturnPct(value, 2) },
    { title: "超额收益", dataIndex: "excess_return", width: 120, render: (value) => formatReturnPct(value, 2) },
    { title: zh.sharpe, dataIndex: "sharpe", width: 110, render: (value) => formatNumber(value, 2) },
    { title: "交易数", dataIndex: "trade_count", width: 110, render: (value) => Number.isFinite(Number(value)) ? String(value) : "-" },
    { title: "最大回撤", dataIndex: "max_drawdown", width: 120, render: (value) => formatReturnPct(value, 2) }
  ];

  const performanceRows = useMemo(() => {
    if (!runId) return [];
    return curveVariantNames.map((variantName) => {
      const summary = curveSummary(variantCurves[variantName] || []);
      const resultPayload = variantName === "baseline"
        ? runDetail?.baseline_result
        : runDetail?.variant_results?.[variantName];
      const metrics = variantName === "baseline"
        ? baselineMetrics
        : resultPayload?.recommended?.metrics || resultPayload?.metrics || resultPayload || {};
      const tradeCount = variantName === "baseline"
        ? runDetail?.baseline_trades_count
        : optimizationMatchesRun && optimizationResult?.selected_variant === variantName && Number.isFinite(Number(optimizationResult?.optimization?.trade_count))
          ? optimizationResult?.optimization?.trade_count
        : runDetail?.variant_trade_counts?.[variantName] ?? metrics.total_trade_count;
      return {
        key: variantName,
        label: variantName === "baseline" ? "Baseline" : variantName === "manual_grid" ? "Manual Grid Latest" : variantName,
        strategy_return: summary.strategy?.totalReturn,
        benchmark_return: summary.buyHold?.totalReturn,
        excess_return: summary.excess,
        sharpe: metrics.sharpe ?? metrics.sharpe_ratio,
        trade_count: tradeCount,
        max_drawdown: summary.strategy?.maxDrawdown
      };
    });
  }, [baselineMetrics, curveVariantNames, optimizationMatchesRun, optimizationResult, runDetail, runId, variantCurves]);

  const storedManualGridObjective = String(runDetail?.variant_results?.manual_grid?.objective || "sharpe");
  const canUseOptimizationResultGrid = optimizationMatchesRun && optimizationMatchesObjective && Array.isArray(optimizationResult?.grid_summary) && optimizationResult.grid_summary.length > 0;
  const canUseStoredGridSummary = Array.isArray(runDetail?.variant_grid_summaries?.manual_grid)
    && runDetail.variant_grid_summaries.manual_grid.length > 0
    && storedManualGridObjective === objective;
  const manualGridNeedsRerun = method === "manual_grid" && !canUseOptimizationResultGrid && !canUseStoredGridSummary && objective !== "sharpe";
  const manualGridTopRows = useMemo(() => {
    const rows = canUseOptimizationResultGrid
      ? optimizationResult.grid_summary
      : (canUseStoredGridSummary ? runDetail?.variant_grid_summaries?.manual_grid : []);
    return rows
      .filter((item: any) => Number(item?.rank) > 0 && item?.success !== false)
      .sort((a: any, b: any) => Number(a.rank) - Number(b.rank))
      .slice(0, 6);
  }, [canUseOptimizationResultGrid, canUseStoredGridSummary, optimizationResult, runDetail]);

  useEffect(() => {
    if (!curveDateBounds.min || !curveDateBounds.max) return;
    setCurveStartDate((current) => {
      if (!current) return curveDateBounds.min;
      if (current < curveDateBounds.min) return curveDateBounds.min;
      if (current > curveDateBounds.max) return curveDateBounds.min;
      return current;
    });
    setCurveEndDate((current) => {
      if (!current) return curveDateBounds.max;
      if (current > curveDateBounds.max) return curveDateBounds.max;
      if (current < curveDateBounds.min) return curveDateBounds.max;
      return current;
    });
  }, [curveDateBounds.max, curveDateBounds.min, runId]);

  useEffect(() => {
    if (!loading) return;
    refreshTasks().catch(() => undefined);
    const timer = window.setInterval(() => {
      refreshTasks().catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [loading, refreshTasks]);

  const curveSelectorItems = useMemo(() => {
    const rows: Array<{ key: string; label: string; value: number | undefined; type: "strategy" | "benchmark" }> = curveVariantNames.map((variantName) => {
      const summary = curveSummary(filteredVariantCurves[variantName] || []);
      return {
        key: variantName,
        label: variantDisplayLabel(variantName),
        value: summary.strategy?.totalReturn,
        type: "strategy" as const
      };
    });
    const benchmarkSummary = curveSummary(filteredVariantCurves.baseline || filteredVariantCurves[primaryVariant] || []);
    if (benchmarkSummary.buyHold) {
      rows.push({
        key: "buy_hold",
        label: "B&H",
        value: benchmarkSummary.buyHold.totalReturn,
        type: "benchmark" as const
      });
    }
    return rows;
  }, [curveVariantNames, filteredVariantCurves, primaryVariant]);

  function toggleCurveVisibility(nextKey: string) {
    setVisibleCurveKeys((current) => current.includes(nextKey) ? current.filter((key) => key !== nextKey) : [...current, nextKey]);
  }

  function applyCurveShortcut(range: "3m" | "6m" | "1y" | "all") {
    if (!curveDateBounds.min || !curveDateBounds.max) return;
    if (range === "all") {
      setCurveStartDate(curveDateBounds.min);
      setCurveEndDate(curveDateBounds.max);
      return;
    }
    const nextStart = range === "3m"
      ? shiftDate(curveDateBounds.max, -3)
      : range === "6m"
        ? shiftDate(curveDateBounds.max, -6)
        : shiftDate(curveDateBounds.max, 0, -1);
    setCurveStartDate(nextStart < curveDateBounds.min ? curveDateBounds.min : nextStart);
    setCurveEndDate(curveDateBounds.max);
  }

  useEffect(() => {
    window.localStorage.setItem(OPTIMIZE_DRAFT_STORAGE_KEY, JSON.stringify({
      selectedFamily,
      runId,
      method,
      objective,
      poolVariant,
      selectedParams,
      ranges,
      visibleCurveKeys,
      curveStartDate,
      curveEndDate,
    }));
  }, [curveEndDate, curveStartDate, method, objective, poolVariant, ranges, runId, selectedFamily, selectedParams, visibleCurveKeys]);

  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div>
          <p className="eyebrow">Parameter Lab</p>
          <h2>{zh.optimize}</h2>
          <p className="hero-copy">按策略族选择 run，切换不同优化变体，并把最新结果沉淀进策略池。</p>
        </div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{runs.length}</div><div className="metric-label">runs</div></div>
          <div className="metric-tile"><div className="metric-value">{searchSpace?.parameters?.length || 0}</div><div className="metric-label">params</div></div>
          <div className="metric-tile"><div className="metric-value">{variants.length}</div><div className="metric-label">variants</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>{zh.currentSelection}</h3>
            <p>先选策略族和对应 run，页面会直接展示这个 run 下的全部 variants。</p>
          </div>
          <span className={statusClass(runId ? "completed" : "pending")}>{runId ? "ready" : "pending"}</span>
        </div>
        <div className="form-grid optimization-form-grid">
          <label className="field">
            <span>策略族</span>
            <Select value={selectedFamily || undefined} onChange={setSelectedFamily} options={families.map((item) => ({ value: item, label: item }))} />
          </label>
          <label className="field">
            <span>运行版本</span>
            <Select
              value={runId || undefined}
              onChange={(value) => {
                setRunId(value);
              }}
              options={familyRuns.map((item) => ({
                value: item.run_id,
                label: `${item.run_id || "-"} | ${item.vt_symbol || "-"}`
              }))}
            />
          </label>
        </div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>累计收益对比</h3>
            <p>`manual_grid` 只展示最新一条同名结果，先看累计收益曲线，再看绩效表现。</p>
          </div>
        </div>
        <CurveControls
          items={curveSelectorItems}
          visibleKeys={visibleCurveKeys}
          startDate={curveStartDate}
          endDate={curveEndDate}
          bounds={curveDateBounds}
          onToggle={toggleCurveVisibility}
          onSelectAll={() => setVisibleCurveKeys(curveSelectorItems.map((item) => item.key))}
          onClear={() => setVisibleCurveKeys([])}
          onStartDateChange={setCurveStartDate}
          onEndDateChange={setCurveEndDate}
          onShortcut={applyCurveShortcut}
        />
        {visibleCurveKeys.length > 0 && curveVariantNames.length > 0 ? (
          <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={filteredVariantCurves} visibleKeys={visibleCurveKeys} orderedKeys={curveSelectorItems.map((item) => item.key)} showLegend={false} height={420} /></div>
        ) : curveVariantNames.length > 0 ? (
          <div className="empty-state">当前没有展示的曲线，可在上方重新勾选。</div>
        ) : (
          <div className="empty-state">当前运行版本没有可展示的曲线。</div>
        )}
      </section>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>绩效明细</h3>
            <p>这里统一展示当前 run 下各个 variant 的核心表现，不再显示参数列。</p>
          </div>
        </div>
        <Table rowKey="key" columns={performanceColumns} dataSource={performanceRows} pagination={false} scroll={{ x: 900 }} className="workbench-table performance-detail-table" />
      </section>

      <section className="band library-shell">
        <div className="library-section-head optimization-mode-head">
          <div className="optimization-title-block">
            <h3>参数优化</h3>
            <p>生成或调整参数范围，确认后再运行所选优化器。</p>
            <div className="optimization-suggestion-actions">
              <Button loading={suggestionLoading} disabled={!runId} onClick={generateSpaceSuggestion}>AI 生成参数范围</Button>
              <Button disabled={!runId || suggestionLoading} onClick={restoreStaticSpace}>恢复默认</Button>
            </div>
          </div>
          <div className="optimization-mode-inline">
            <label>
              <span>优化模式</span>
              <Select value={method} onChange={setMethod} options={methods.map((item) => ({ value: item.method, label: item.method === "auto" ? "自动优化" : item.method === "manual_grid" ? "手动网格" : item.label }))} />
            </label>
            <label>
              <span>评分方式</span>
              <Select
                value={objective}
                onChange={setObjective}
                options={[
                  { value: "sharpe", label: "Sharpe" },
                  { value: "excess_return", label: "超额收益" }
                ]}
              />
            </label>
            <span className="status-pill status-running">
              {method === "optuna"
                ? totalGridCount > 0 && totalGridCount <= 200
                  ? `全量 ${totalGridCount} 组`
                  : "TPE 200 Trials"
                : `网格 ${totalGridCount}`}
            </span>
          </div>
        </div>
        {suggestionProgress > 0 && (
          <div className="optimization-ai-progress">
            <div>
              <strong>{suggestionProgress >= 100 ? "参数范围已生成" : "AI 正在分析策略参数"}</strong>
              <span>{suggestionProgress >= 100 ? "请检查范围和启用状态" : "正在识别参数语义、约束和合理范围"}</span>
            </div>
            <Progress percent={suggestionProgress} status={suggestionProgress >= 100 ? "success" : "active"} showInfo={false} />
          </div>
        )}
        <div className="parameter-frame">
          <Table rowKey="name" columns={parameterColumns} dataSource={searchSpace?.parameters || []} pagination={false} className="workbench-table parameter-table" />
        </div>
        {(spaceSuggestion?.virtual_parameters || []).length > 0 && (
          <div className="detail-grid optimizer-preview">
            {(spaceSuggestion.virtual_parameters || []).map((item: any) => (
              <div key={item.name}>
                <Checkbox
                  checked={selectedParams.includes(item.name)}
                  onChange={(event) => setSelectedParams((current) => event.target.checked ? [...current, item.name] : current.filter((name) => name !== item.name))}
                >{item.name}</Checkbox>
                <div className="meta-inline">{(item.choices || []).join(" / ")}</div>
                <div className="meta-inline">{item.reason}</div>
              </div>
            ))}
          </div>
        )}
        <div className="action-row optimization-run-row">
          <Button type="primary" loading={loading} disabled={!runId || (method === "manual_grid" && !selectedParams.length)} onClick={submitOptimization}>
            运行优化
          </Button>
        </div>
        {manualGridNeedsRerun && (
          <div className="empty-state">当前这个 run 还没有按“超额收益”生成过手动网格排名，切换评分方式后需要重新运行一次手动优化。</div>
        )}
        {method === "manual_grid" && manualGridTopRows.length > 0 && (
          <div className="detail-grid optimizer-preview">
            {manualGridTopRows.map((item: any) => (
              <div className="viewer-summary-card compact-optimizer-card" key={String(item.label || item.rank)}>
                <div className="summary-label">Top {item.rank} · {item.label || "-"}</div>
                <strong>{formatNumber(item.score, 4)}</strong>
                <div className="meta-inline">
                  {objective === "excess_return"
                    ? `超额 ${formatReturnPct(item.excess_return, 2)}`
                    : `Sharpe ${formatNumber(item.sharpe, 2)}`}
                </div>
                <div className="meta-inline">{summarizeParameters(item.parameters)}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>加入策略池</h3>
            <p>曲线和明细会同时展示全部 variants，加入策略池时再单独选择要入池的版本。</p>
          </div>
          <Button type="primary" loading={addingToPool} disabled={!runId || !poolVariant} onClick={addSelectedVariantToPool}>加入策略池</Button>
        </div>
        <div className="summary-compact-grid">
          <div className="viewer-summary-card"><span className="summary-label">运行版本</span><strong>{runId || "-"}</strong></div>
          <div className="viewer-summary-card">
            <span className="summary-label">入池版本</span>
            <Select
              value={poolVariant || undefined}
              onChange={setPoolVariant}
              options={curveVariantNames
                .map((name) => ({
                  value: name,
                  label: variantDisplayLabel(name)
                }))}
            />
          </div>
          <div className="viewer-summary-card">
            <span className="summary-label">入池名称</span>
            <Input value={poolStrategyName} onChange={(event) => setPoolStrategyName(event.target.value)} placeholder="用于策略池展示的名称" />
          </div>
          <div className="viewer-summary-card"><span className="summary-label">版本 Sharpe</span><strong>{formatNumber(poolVariantMetrics.sharpe ?? poolVariantMetrics.sharpe_ratio)}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">版本交易数</span><strong>{Number.isFinite(Number(poolVariantTradeCount)) ? String(poolVariantTradeCount) : "-"}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">优化器</span><strong>{optimizationResult?.optimization?.optimizer_name || "-"}</strong></div>
        </div>
      </section>
    </section>
  );
}
