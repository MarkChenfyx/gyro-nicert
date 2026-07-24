import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Checkbox, Drawer, Input, InputNumber, Modal, Progress, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  addToPool,
  archiveTerminalTasks,
  comparePool,
  createOptimizationCurveSnapshot,
  createNaturalLanguageSource,
  createResearchBaseline,
  createResearchBaselineFromCode,
  downloadData,
  generateStrategy,
  getDataCoverage,
  getNaturalLanguageSource,
  getOptimizationMethods,
  getOptimizationSearchSpace,
  getGridCandidateCurve,
  suggestOptimizationSearchSpace,
  getPoolItem,
  getVariantCurve,
  getRun,
  listOptimizationCurveSnapshots,
  listRuns,
  listNaturalLanguageSources,
  listPool,
  listTasks,
  removeFromPool,
  deleteOptimizationCurveSnapshot,
  renameOptimizationCurveSnapshot,
  rerunPool,
  runOptimization,
  updateNaturalLanguageSource
} from "../api";
import {
  PageKey,
  TaskRunNavigation,
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
  formatParameterValue,
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
  CurveControlItem,
  CurveControls
} from "../app/ui";


type RangeField = "low" | "high" | "step";
type ParameterField = RangeField | "current";
const GRID_PREVIEW_CURVE_PREFIX = "__grid_candidate_preview__:";
const SAVED_OPTIMIZATION_CURVE_PREFIX = "__saved_optimization_curve__:";

type GridCandidatePreview = { label: string; rank: number; rows: any[] };
type SavedOptimizationCurve = {
  snapshot_id: string;
  name: string;
  source_run_id: string;
  source_variant_name: string;
  created_at: string;
  parameters?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  curve: any[];
};

function gridPreviewCurveKey(label: string) {
  return `${GRID_PREVIEW_CURVE_PREFIX}${label}`;
}

function savedOptimizationCurveKey(snapshotId: string) {
  return `${SAVED_OPTIMIZATION_CURVE_PREFIX}${snapshotId}`;
}

function parseGridParameters(parameters: unknown): Record<string, unknown> {
  if (parameters && typeof parameters === "object" && !Array.isArray(parameters)) {
    return parameters as Record<string, unknown>;
  }
  const text = String(parameters || "").trim();
  if (!text) return {};
  const jsonCandidates = [
    text,
    text.replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false").replace(/\bNone\b/g, "null").replace(/'/g, '"')
  ];
  for (const candidate of jsonCandidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    } catch {
      // Continue with the historical key=value fallback below.
    }
  }
  const result: Record<string, unknown> = {};
  const body = text.replace(/^\s*[\{\[]|[\}\]]\s*$/g, "");
  for (const segment of body.split(",")) {
    const match = segment.match(/^\s*['"]?([^'":=]+)['"]?\s*[:=]\s*(.*?)\s*$/);
    if (!match) continue;
    const key = match[1].trim();
    const rawValue = match[2].replace(/^['"]|['"]$/g, "").trim();
    const numericValue = Number(rawValue);
    result[key] = Number.isFinite(numericValue)
      ? numericValue
      : /^(true|false)$/i.test(rawValue)
        ? rawValue.toLowerCase() === "true"
        : rawValue;
  }
  return result;
}

function poolNamePrefix(value: unknown) {
  return String(value || "").split("|", 1)[0].trim();
}

function parameterDraftValue(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function parsedParameterValue(value: string | null, integerOnly: boolean): number | null | undefined {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return undefined;
  return cleanOptimizationNumber(integerOnly ? Math.trunc(parsed) : parsed);
}

function finiteMetric(source: any, keys: string[]): number | null {
  for (const key of keys) {
    const numeric = Number(source?.[key]);
    if (source?.[key] !== "" && source?.[key] !== null && source?.[key] !== undefined && Number.isFinite(numeric)) return numeric;
  }
  return null;
}

function formatHoldingMinutes(value: number | null): string {
  if (value === null) return "暂无";
  if (value < 60) return `${formatNumber(value, 0)} 分钟`;
  if (value < 1440) return `${formatNumber(value / 60, 1)} 小时`;
  return `${formatNumber(value / 1440, 1)} 天`;
}

const ParameterNumberInput = React.memo(function ParameterNumberInput({
  field,
  parameterType,
  value,
  stepValue,
  onCommit
}: {
  field: ParameterField;
  parameterType: string;
  value: number | null | undefined;
  stepValue: number | null | undefined;
  onCommit: (value: number | null) => void;
}) {
  const integerOnly = parameterType === "int";
  const [draft, setDraft] = useState<string | null>(() => parameterDraftValue(value));
  const draftRef = useRef<string | null>(draft);
  const focusedRef = useRef(false);
  const commitTimerRef = useRef<number | null>(null);

  function updateDraft(nextValue: string | null) {
    draftRef.current = nextValue;
    setDraft(nextValue);
  }

  useEffect(() => {
    if (!focusedRef.current) updateDraft(parameterDraftValue(value));
  }, [value]);

  useEffect(() => () => {
    if (commitTimerRef.current !== null) window.clearTimeout(commitTimerRef.current);
  }, []);

  function cancelPendingCommit() {
    if (commitTimerRef.current === null) return;
    window.clearTimeout(commitTimerRef.current);
    commitTimerRef.current = null;
  }

  function scheduleCommit(nextValue: number | null) {
    cancelPendingCommit();
    commitTimerRef.current = window.setTimeout(() => {
      commitTimerRef.current = null;
      onCommit(nextValue);
    }, 80);
  }

  function commitDraft(normalizeDisplay: boolean) {
    cancelPendingCommit();
    const parsed = parsedParameterValue(draftRef.current, integerOnly);
    if (parsed === undefined) {
      if (normalizeDisplay) updateDraft(parameterDraftValue(value));
      return;
    }
    onCommit(parsed);
    if (normalizeDisplay) updateDraft(parameterDraftValue(parsed));
  }

  const configuredStep = Number(stepValue);
  const inputStep = field === "step"
    ? (integerOnly ? 1 : 0.001)
    : (Number.isFinite(configuredStep) && configuredStep > 0 ? configuredStep : integerOnly ? 1 : 0.001);

  return (
    <InputNumber<string>
      stringMode
      className={field === "current" ? "parameter-current-input" : undefined}
      value={draft}
      precision={integerOnly ? 0 : undefined}
      step={inputStep}
      onFocus={() => { focusedRef.current = true; }}
      onBlur={() => {
        focusedRef.current = false;
        commitDraft(true);
      }}
      onPressEnter={(event) => event.currentTarget.blur()}
      onChange={(nextValue) => {
        updateDraft(nextValue);
        const parsed = parsedParameterValue(nextValue, integerOnly);
        if (parsed !== undefined) scheduleCommit(parsed);
      }}
    />
  );
});


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
  taskRunNavigation,
  onTaskRunApplied,
  refreshPool,
  onOpenPool,
  refreshTasks
}: {
  lastResearch: any;
  taskRunNavigation: TaskRunNavigation | null;
  onTaskRunApplied: (requestId: number) => void;
  refreshPool: () => Promise<void>;
  onOpenPool: (poolItemId: string, vtSymbol: string) => void;
  refreshTasks: () => Promise<void>;
}) {
  const persistedDraft = useMemo(() => loadOptimizeDraft(), []);
  const [runs, setRuns] = useState<any[]>([]);
  const [methods, setMethods] = useState<any[]>([]);
  const [selectedFamily, setSelectedFamily] = useState(String(persistedDraft.selectedFamily || ""));
  const [runId, setRunId] = useState(String(taskRunNavigation?.runId || persistedDraft.runId || lastResearch?.baseline?.run?.run_id || ""));
  const [method, setMethod] = useState(String(persistedDraft.method || "manual_grid"));
  const [objective, setObjective] = useState(String(persistedDraft.objective || "sharpe"));
  const [poolVariant, setPoolVariant] = useState(String(persistedDraft.poolVariant || "manual_grid"));
  const [searchSpace, setSearchSpace] = useState<any>(null);
  const [selectedParams, setSelectedParams] = useState<string[]>(Array.isArray(persistedDraft.selectedParams) ? persistedDraft.selectedParams.map(String) : []);
  const [ranges, setRanges] = useState<Record<string, any>>(persistedDraft.ranges && typeof persistedDraft.ranges === "object" ? persistedDraft.ranges : {});
  const rangesRef = useRef(ranges);
  const [baseParameters, setBaseParameters] = useState<Record<string, number>>(persistedDraft.baseParameters && typeof persistedDraft.baseParameters === "object" ? persistedDraft.baseParameters : {});
  const baseParametersRef = useRef(baseParameters);
  const [originalBaseParameters, setOriginalBaseParameters] = useState<Record<string, number>>({});
  const [runDetail, setRunDetail] = useState<any>(null);
  const [variantCurves, setVariantCurves] = useState<Record<string, any[]>>({});
  const [savedOptimizationCurves, setSavedOptimizationCurves] = useState<SavedOptimizationCurve[]>([]);
  const [curveSnapshotManagerOpen, setCurveSnapshotManagerOpen] = useState(false);
  const [curveSnapshotRenameDrafts, setCurveSnapshotRenameDrafts] = useState<Record<string, string>>({});
  const [curveSnapshotBusyId, setCurveSnapshotBusyId] = useState("");
  const [gridCandidatePreviews, setGridCandidatePreviews] = useState<GridCandidatePreview[]>([]);
  const [gridDiagnosticRow, setGridDiagnosticRow] = useState<any>(null);
  const [gridCandidateLoadingLabel, setGridCandidateLoadingLabel] = useState("");
  const [visibleCurveKeys, setVisibleCurveKeys] = useState<string[]>(Array.isArray(persistedDraft.visibleCurveKeys) ? persistedDraft.visibleCurveKeys.map(String) : []);
  const [curveStartDate, setCurveStartDate] = useState(String(persistedDraft.curveStartDate || ""));
  const [curveEndDate, setCurveEndDate] = useState(String(persistedDraft.curveEndDate || ""));
  const [optimizationResult, setOptimizationResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionProgress, setSuggestionProgress] = useState(0);
  const [spaceSuggestion, setSpaceSuggestion] = useState<any>(null);
  const [parameterDetailsCollapsed, setParameterDetailsCollapsed] = useState(
    String(persistedDraft.runId || "") === runId && Boolean(persistedDraft.parameterDetailsCollapsed)
  );
  const [performanceDetailsCollapsed, setPerformanceDetailsCollapsed] = useState(
    String(persistedDraft.runId || "") === runId && Boolean(persistedDraft.performanceDetailsCollapsed)
  );
  const [poolStrategyName, setPoolStrategyName] = useState("");
  const [poolNote, setPoolNote] = useState("");
  const [addingToPool, setAddingToPool] = useState(false);
  const runContextRequestRef = useRef(0);
  const gridCandidateRequestRef = useRef(0);
  const mainCurveSectionRef = useRef<HTMLElement | null>(null);
  const collapseStateRunIdRef = useRef(runId);

  const clearGridCandidatePreviews = useCallback(() => {
    gridCandidateRequestRef.current += 1;
    setGridCandidatePreviews([]);
    setGridCandidateLoadingLabel("");
  }, []);

  useEffect(() => {
    rangesRef.current = ranges;
  }, [ranges]);

  useEffect(() => {
    baseParametersRef.current = baseParameters;
  }, [baseParameters]);

  useEffect(() => {
    listOptimizationCurveSnapshots()
      .then((payload) => setSavedOptimizationCurves(Array.isArray(payload?.items) ? payload.items : []))
      .catch((error) => message.warning(`保留曲线读取失败：${String(error)}`));
  }, []);

  useEffect(() => {
    if (!suggestionLoading) return;
    const timer = window.setInterval(() => {
      setSuggestionProgress((current) => Math.min(92, current + Math.max(1, Math.ceil((92 - current) * 0.12))));
    }, 180);
    return () => window.clearInterval(timer);
  }, [suggestionLoading]);

  async function refreshRuns(defaultRunId?: string) {
    const payload = await listRuns(defaultRunId ? 1000 : 50);
    const nextRuns = payload.runs || [];
    setRuns(nextRuns);
    const preferred = defaultRunId || runId || lastResearch?.baseline?.run?.run_id || nextRuns[0]?.run_id || "";
    const preferredRun = nextRuns.find((item: any) => item.run_id === preferred) || nextRuns[0];
    const resolvedRunId = String(preferredRun?.run_id || "");
    const preferredFamily = strategyFamily(preferredRun);
    if (preferredFamily) setSelectedFamily(preferredFamily);
    if (resolvedRunId) setRunId(resolvedRunId);
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
    const suggestedRows = cachedSuggestion
      ? [
          ...(cachedSuggestion.parameters || []),
          ...(cachedSuggestion.excluded_parameters || []).filter((item: any) => item.low !== undefined && item.high !== undefined)
        ]
      : (space.parameters || []);
    const inventoryBaseParameters = space.base_parameters || {};
    const editableRows = suggestedRows.map((item: any) => ({
      ...item,
      current: item.current ?? inventoryBaseParameters[item.name]
    }));
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
        const kept = storedDraft.visibleCurveKeys
          .map(String)
          .filter((key: string) => allowed.has(key) || key.startsWith(SAVED_OPTIMIZATION_CURVE_PREFIX));
        if (kept.length) return Array.from(new Set([...kept, ...availableVariants, "buy_hold"]));
      }
      return Array.from(new Set([...availableVariants, "buy_hold"]));
    });
    setPoolVariant((current) => {
      const preferred = shouldReuseDraft ? String(storedDraft.poolVariant || current || defaultPoolVariant) : current;
      return availableVariants.includes(preferred) ? preferred : defaultPoolVariant;
    });
    const nextRanges: Record<string, any> = {};
    const nextBaseParameters: Record<string, number> = {};
    const nextOriginalBaseParameters: Record<string, number> = {};
    for (const item of editableRows) {
      nextRanges[item.name] = { low: item.low, high: item.high, step: item.step, type: item.type };
      const numericCurrent = Number(item.current);
      if (Number.isFinite(numericCurrent)) {
        nextBaseParameters[item.name] = numericCurrent;
        nextOriginalBaseParameters[item.name] = numericCurrent;
      }
    }
    if (shouldReuseDraftParams && storedDraft.ranges && typeof storedDraft.ranges === "object") {
      for (const name of parameterNames) {
        if (storedDraft.ranges[name] && typeof storedDraft.ranges[name] === "object") {
          nextRanges[name] = { ...nextRanges[name], ...storedDraft.ranges[name] };
        }
      }
    }
    setRanges(nextRanges);
    if (shouldReuseDraftParams && storedDraft.baseParameters && typeof storedDraft.baseParameters === "object") {
      for (const name of parameterNames) {
        const numericValue = Number(storedDraft.baseParameters[name]);
        if (Number.isFinite(numericValue)) nextBaseParameters[name] = numericValue;
      }
    }
    baseParametersRef.current = nextBaseParameters;
    setBaseParameters(nextBaseParameters);
    setOriginalBaseParameters(nextOriginalBaseParameters);
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
    const requestedRunId = String(taskRunNavigation?.runId || lastResearch?.baseline?.run?.run_id || "");
    refreshRuns(requestedRunId || undefined)
      .then(() => {
        if (taskRunNavigation) onTaskRunApplied(taskRunNavigation.requestId);
      })
      .catch((error) => message.error(String(error)));
  }, [lastResearch?.baseline?.run?.run_id, taskRunNavigation?.requestId]);

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
    if (collapseStateRunIdRef.current !== runId) {
      collapseStateRunIdRef.current = runId;
      setParameterDetailsCollapsed(false);
      setPerformanceDetailsCollapsed(false);
    }
    clearGridCandidatePreviews();
    setGridDiagnosticRow(null);
    setOptimizationResult((current: any) => (String(current?.run?.run_id || "") === runId ? current : null));
    loadRunContext(runId).catch((error) => message.error(String(error)));
  }, [clearGridCandidatePreviews, runId]);

  const currentRun = runs.find((item) => item.run_id === runId);
  const runLineage = runDetail?.manifest?.lineage;
  const poolRunLineage = runLineage?.source_type === "pool_item" && runLineage?.operation === "rerun_as_baseline" ? runLineage : null;
  useEffect(() => {
    setPoolStrategyName(poolNamePrefix(currentRun?.strategy_name || runDetail?.strategy?.strategy_name || ""));
  }, [currentRun?.strategy_name, runDetail?.strategy?.strategy_name]);
  useEffect(() => {
    setPoolNote("");
  }, [runId, poolVariant]);
  const optimizationRunId = String(optimizationResult?.run?.run_id || "");
  const optimizationObjective = String(optimizationResult?.objective || optimizationResult?.optimization?.objective || "");
  const optimizationMatchesRun = Boolean(optimizationResult) && optimizationRunId === runId;
  const optimizationMatchesObjective = !optimizationObjective || optimizationObjective === objective;
  const variants = useMemo(
    () => Array.from(new Set((runDetail?.variants || []).map((item: any) => String(item.variant_name || "")).filter(Boolean))),
    [runDetail]
  );
  const curveVariantNames = useMemo(() => Object.keys(variantCurves), [variantCurves]);
  const savedOptimizationCurveRows = useMemo<Record<string, any[]>>(
    () => Object.fromEntries(savedOptimizationCurves.map((item) => [savedOptimizationCurveKey(item.snapshot_id), item.curve || []])),
    [savedOptimizationCurves]
  );
  const curveDateBounds = useMemo(
    () => variantCurveDateBounds({ ...variantCurves, ...savedOptimizationCurveRows }),
    [savedOptimizationCurveRows, variantCurves]
  );
  const filteredVariantCurves = useMemo(
    () => Object.fromEntries(Object.entries(variantCurves).map(([name, rows]) => [name, clampDateRange(rows, curveStartDate, curveEndDate)])),
    [curveEndDate, curveStartDate, variantCurves]
  );
  const chartVariantCurves = useMemo(() => {
    const savedCurves = Object.fromEntries(Object.entries(savedOptimizationCurveRows).map(([key, rows]) => [
      key,
      clampDateRange(rows, curveStartDate, curveEndDate)
    ]));
    const previewCurves = Object.fromEntries(gridCandidatePreviews.map((preview) => [
      gridPreviewCurveKey(preview.label),
      clampDateRange(preview.rows, curveStartDate, curveEndDate)
    ]));
    return { ...filteredVariantCurves, ...savedCurves, ...previewCurves };
  }, [curveEndDate, curveStartDate, filteredVariantCurves, gridCandidatePreviews, savedOptimizationCurveRows]);
  const primaryVariant = useMemo(
    () => curveVariantNames.find((name) => name !== "baseline") || curveVariantNames[0] || "baseline",
    [curveVariantNames]
  );
  const retainableOptimizationVariant = useMemo(() => {
    const selectedVariant = optimizationMatchesRun ? String(optimizationResult?.selected_variant || "") : "";
    if (selectedVariant && selectedVariant !== "baseline" && curveVariantNames.includes(selectedVariant)) return selectedVariant;
    return curveVariantNames.find((name) => name !== "baseline") || "";
  }, [curveVariantNames, optimizationMatchesRun, optimizationResult?.selected_variant]);
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

  const updateRange = useCallback((name: string, key: RangeField, value: number | null) => {
    const current = rangesRef.current;
    const next = { ...current, [name]: { ...(current[name] || {}), [key]: cleanOptimizationNumber(value) } };
    rangesRef.current = next;
    setRanges(next);
  }, []);

  const updateBaseParameter = useCallback((name: string, value: number | null) => {
    if (value === null || !Number.isFinite(Number(value))) return;
    const next = { ...baseParametersRef.current, [name]: Number(value) };
    baseParametersRef.current = next;
    setBaseParameters(next);
  }, []);

  const restoreBaseParameter = useCallback((name: string) => {
    const originalValue = originalBaseParameters[name];
    if (!Number.isFinite(Number(originalValue))) return;
    const next = { ...baseParametersRef.current, [name]: originalValue };
    baseParametersRef.current = next;
    setBaseParameters(next);
  }, [originalBaseParameters]);

  const updateRangeType = useCallback((name: string, nextType: "int" | "float") => {
    const current = rangesRef.current;
    const currentSpec = { ...(current[name] || {}) };
    const nextSpec = nextType === "int"
      ? {
          ...currentSpec,
          low: Number.isFinite(Number(currentSpec.low)) ? Math.round(Number(currentSpec.low)) : currentSpec.low,
          high: Number.isFinite(Number(currentSpec.high)) ? Math.round(Number(currentSpec.high)) : currentSpec.high,
          step: Number.isFinite(Number(currentSpec.step)) ? Math.max(1, Math.round(Number(currentSpec.step))) : 1,
          type: "int"
        }
      : { ...currentSpec, type: "float" };
    const next = { ...current, [name]: nextSpec };
    rangesRef.current = next;
    setRanges(next);
    if (nextType === "int" && Number.isFinite(Number(baseParametersRef.current[name]))) {
      const nextBase = { ...baseParametersRef.current, [name]: Math.round(Number(baseParametersRef.current[name])) };
      baseParametersRef.current = nextBase;
      setBaseParameters(nextBase);
    }
  }, []);

  async function generateSpaceSuggestion() {
    if (!runId) return;
    setSuggestionProgress(6);
    setSuggestionLoading(true);
    try {
      const payload = await suggestOptimizationSearchSpace(runId, "baseline", true);
      const editableRows = [
        ...(payload.parameters || []),
        ...(payload.excluded_parameters || []).filter((item: any) => item.low !== undefined && item.high !== undefined)
      ].map((item: any) => ({
        ...item,
        current: baseParametersRef.current[item.name] ?? item.current ?? searchSpace?.base_parameters?.[item.name]
      }));
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
    clearGridCandidatePreviews();
    setLoading(true);
    try {
      await refreshTasks();
      const payload = await runOptimization({
        run_id: runId,
        variant_name: "baseline",
        method,
        base_parameters: Object.fromEntries(
          (searchSpace?.parameters || [])
            .map((item: any) => String(item.name))
            .filter((name: string) => Number.isFinite(Number(baseParametersRef.current[name])))
            .map((name: string) => [name, baseParametersRef.current[name]])
        ),
        selected_parameters: selected,
        parameter_ranges: Object.fromEntries(selected.filter((name: string) => rangesRef.current[name]).map((name: string) => [name, rangesRef.current[name]])),
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
      const payload = await addToPool(runId, poolVariant, currentRun?.vt_symbol, poolStrategyName.trim() || undefined, poolNote);
      await Promise.all([refreshPool(), refreshTasks()]);
      if (payload?.rerun_succeeded) {
        const rerunStart = String(payload?.rerun?.items?.[0]?.rerun_start || "").trim();
        const rerunEnd = String(payload?.rerun?.rerun_end || payload?.rerun?.items?.[0]?.rerun_end || "").trim();
        message.success(rerunStart && rerunEnd ? `已入池并完成 ${formatDate(rerunStart)} 至 ${formatDate(rerunEnd)} 回测` : "已入池并完成全区间回测");
      } else {
        const diagnostic = String(payload?.rerun?.diagnostics?.[0]?.message || "自动重跑未完成");
        message.warning(`已加入策略池，但${diagnostic}`);
      }
      setPoolNote("");
      onOpenPool(
        String(payload?.pool_item_id || ""),
        String(payload?.vt_symbol || currentRun?.vt_symbol || "")
      );
    } catch (error) {
      message.error(String(error));
    } finally {
      setAddingToPool(false);
    }
  }

  const parameterRows = useMemo(
    () => (searchSpace?.parameters || []).map((record: any) => ({
      ...record,
      current: baseParameters[record.name] ?? record.current,
      originalCurrent: originalBaseParameters[record.name],
      currentModified: Number.isFinite(Number(originalBaseParameters[record.name]))
        && Number(baseParameters[record.name] ?? record.current) !== Number(originalBaseParameters[record.name]),
      rangeLow: ranges[record.name]?.low,
      rangeHigh: ranges[record.name]?.high,
      rangeStep: ranges[record.name]?.step,
      rangeType: ranges[record.name]?.type || record.type
    })),
    [baseParameters, originalBaseParameters, ranges, searchSpace?.parameters]
  );

  const toggleSelectedParam = useCallback((name: string, checked: boolean) => {
    setSelectedParams((current) => checked
      ? Array.from(new Set([...current, name]))
      : current.filter((item) => item !== name));
  }, []);

  const parameterColumns: ColumnsType<any> = useMemo(() => [
    {
      title: "",
      width: 48,
      render: (_, record) => (
        <Checkbox
          checked={selectedParams.includes(record.name)}
          onChange={(event) => toggleSelectedParam(record.name, event.target.checked)}
        />
      )
    },
    { title: zh.paramName, dataIndex: "name", render: (value, record) => <div className="param-name-cell"><strong>{value}</strong><span>{record.category || record.role}</span>{record.reason && <small>{record.reason}</small>}</div> },
    {
      title: "本次默认值",
      dataIndex: "current",
      width: 112,
      render: (value, record) => (
        <div className={`parameter-default-cell${record.currentModified ? " is-modified" : ""}`}>
          <ParameterNumberInput
            field="current"
            parameterType={record.rangeType}
            value={value}
            stepValue={record.rangeStep}
            onCommit={(nextValue) => updateBaseParameter(record.name, nextValue)}
          />
          {record.currentModified && (
            <button
              type="button"
              className="parameter-default-restore"
              title={`还原为 ${String(record.originalCurrent)}`}
              aria-label={`${record.name} 还原为原默认值 ${String(record.originalCurrent)}`}
              onClick={() => restoreBaseParameter(record.name)}
            >↺</button>
          )}
        </div>
      )
    },
    {
      title: "下限",
      dataIndex: "rangeLow",
      render: (value, record) => <ParameterNumberInput field="low" parameterType={record.rangeType} value={value} stepValue={record.rangeStep} onCommit={(nextValue) => updateRange(record.name, "low", nextValue)} />
    },
    {
      title: "上限",
      dataIndex: "rangeHigh",
      render: (value, record) => <ParameterNumberInput field="high" parameterType={record.rangeType} value={value} stepValue={record.rangeStep} onCommit={(nextValue) => updateRange(record.name, "high", nextValue)} />
    },
    {
      title: "步长",
      dataIndex: "rangeStep",
      render: (value, record) => <ParameterNumberInput field="step" parameterType={record.rangeType} value={value} stepValue={value} onCommit={(nextValue) => updateRange(record.name, "step", nextValue)} />
    },
    {
      title: "类型",
      dataIndex: "rangeType",
      width: 96,
      render: (value, record) => (
        <span title="默认按策略代码推断，可按本轮优化需要调整">
          <Select<"int" | "float">
            size="small"
            value={value === "int" ? "int" : "float"}
            onChange={(nextType) => updateRangeType(record.name, nextType)}
            options={[
              { value: "int", label: "整数" },
              { value: "float", label: "小数" }
            ]}
          />
        </span>
      )
    }
  ], [restoreBaseParameter, selectedParams, toggleSelectedParam, updateBaseParameter, updateRange, updateRangeType]);

  const performanceColumns: ColumnsType<any> = [
    { title: "版本", dataIndex: "label", width: 180 },
    { title: "策略累计收益", dataIndex: "strategy_return", width: 130, render: (value) => formatReturnPct(value, 2) },
    { title: "B&H", dataIndex: "benchmark_return", width: 120, render: (value) => formatReturnPct(value, 2) },
    { title: "超额收益", dataIndex: "excess_return", width: 120, render: (value) => formatReturnPct(value, 2) },
    { title: zh.sharpe, dataIndex: "sharpe", width: 110, render: (value) => formatNumber(value, 2) },
    { title: "交易次数", dataIndex: "trade_count", width: 110, render: (value) => Number.isFinite(Number(value)) ? String(value) : "-" },
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
        label: variantDisplayLabel(variantName),
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
  const manualGridResultPayload = canUseOptimizationResultGrid
    ? optimizationResult?.optimization
    : runDetail?.variant_results?.manual_grid;
  const manualGridRecommendedLabel = String(manualGridResultPayload?.recommended?.label || "");
  const manualGridRecommendedMetrics = manualGridResultPayload?.recommended?.metrics || {};
  const manualGridTopRows = useMemo(() => {
    const rows = canUseOptimizationResultGrid
      ? optimizationResult.grid_summary
      : (canUseStoredGridSummary ? runDetail?.variant_grid_summaries?.manual_grid : []);
    return rows
      .filter((item: any) => Number(item?.rank) > 0 && item?.success !== false)
      .sort((a: any, b: any) => Number(a.rank) - Number(b.rank))
      .slice(0, 10)
      .map((item: any) => String(item?.label || "") === manualGridRecommendedLabel
        ? { ...manualGridRecommendedMetrics, ...item }
        : item);
  }, [canUseOptimizationResultGrid, canUseStoredGridSummary, manualGridRecommendedLabel, manualGridRecommendedMetrics, optimizationResult, runDetail]);
  const manualGridTableRows = useMemo(
    () => manualGridTopRows.map((item: any) => ({
      ...item,
      key: `rank-${item.rank}-${String(item.label || "")}`,
      parsedParameters: parseGridParameters(item.parameters)
    })),
    [manualGridTopRows]
  );
  async function toggleGridCandidatePreview(record: any) {
    const candidateLabel = String(record?.label || "").trim();
    const rank = Number(record?.rank || 0);
    if (!candidateLabel || !runId || rank <= 0 || gridCandidateLoadingLabel === candidateLabel) return;
    if (gridCandidatePreviews.some((preview) => preview.label === candidateLabel)) {
      setGridCandidatePreviews((current) => current.filter((preview) => preview.label !== candidateLabel));
      return;
    }
    const requestId = ++gridCandidateRequestRef.current;
    setParameterDetailsCollapsed(true);
    setPerformanceDetailsCollapsed(true);
    setGridCandidateLoadingLabel(candidateLabel);
    try {
      const payload = await getGridCandidateCurve(runId, "manual_grid", candidateLabel);
      if (requestId !== gridCandidateRequestRef.current) return;
      const rows = Array.isArray(payload?.data) ? payload.data : [];
      if (!rows.length) throw new Error("该参数组合没有可展示的候选曲线。");
      setGridCandidatePreviews((current) => current.some((preview) => preview.label === candidateLabel)
        ? current
        : [...current, { label: candidateLabel, rank, rows }]);
      window.setTimeout(() => mainCurveSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      if (requestId === gridCandidateRequestRef.current) message.warning(String(error));
    } finally {
      if (requestId === gridCandidateRequestRef.current) setGridCandidateLoadingLabel("");
    }
  }
  const manualGridParameterNames = useMemo(() => {
    const names = new Set<string>();
    for (const row of manualGridTableRows) {
      Object.keys(row.parsedParameters).forEach((name) => names.add(name));
    }
    return Array.from(names);
  }, [manualGridTableRows]);
  const manualGridColumns: ColumnsType<any> = useMemo(() => [
    {
      title: "排名",
      dataIndex: "rank",
      width: 68,
      fixed: "left" as const,
      render: (value, record) => (
        <span className="optimizer-grid-rank-cell">
          <strong className="optimizer-grid-rank">#{value}</strong>
          {gridCandidateLoadingLabel === String(record?.label || "") && <small>加载中</small>}
        </span>
      )
    },
    ...manualGridParameterNames.map((name) => ({
      title: <span className="optimizer-grid-param-name" title={name}>{name}</span>,
      key: `parameter-${name}`,
      width: 124,
      render: (_: unknown, record: any) => (
        <span title={`${name}=${formatParameterValue(record.parsedParameters[name])}`}>
          {formatParameterValue(record.parsedParameters[name])}
        </span>
      )
    })),
    {
      title: "超额收益",
      dataIndex: "excess_return",
      width: 118,
      className: objective === "excess_return" ? "optimizer-current-metric" : "",
      onHeaderCell: () => ({ className: objective === "excess_return" ? "optimizer-current-metric" : "" }),
      render: (value) => formatReturnPct(value, 2)
    },
    {
      title: "Sharpe",
      dataIndex: "sharpe",
      width: 100,
      className: objective === "sharpe" ? "optimizer-current-metric" : "",
      onHeaderCell: () => ({ className: objective === "sharpe" ? "optimizer-current-metric" : "" }),
      render: (value) => formatNumber(value, 2)
    },
    {
      title: "",
      key: "diagnostic",
      width: 62,
      fixed: "right" as const,
      render: (_: unknown, record: any) => (
        <Button
          type="text"
          size="small"
          className="optimizer-grid-diagnostic-button"
          onClick={(event) => {
            event.stopPropagation();
            setGridDiagnosticRow(record);
          }}
        >诊断</Button>
      )
    }
  ], [gridCandidateLoadingLabel, manualGridParameterNames, objective]);
  const manualGridTableWidth = 68 + manualGridParameterNames.length * 124 + 280;

  const gridDiagnosticCoreRows = useMemo(() => {
    if (!gridDiagnosticRow) return [];
    const baselineCurve = curveSummary(variantCurves.baseline || []);
    const candidateCosts = [finiteMetric(gridDiagnosticRow, ["total_commission"]), finiteMetric(gridDiagnosticRow, ["total_slippage"])]
      .reduce<number | null>((sum, value) => value === null ? sum : (sum ?? 0) + value, null);
    const baselineCosts = [finiteMetric(baselineMetrics, ["total_commission"]), finiteMetric(baselineMetrics, ["total_slippage"])]
      .reduce<number | null>((sum, value) => value === null ? sum : (sum ?? 0) + value, null);
    return [
      { label: "Sharpe", value: finiteMetric(gridDiagnosticRow, ["sharpe", "sharpe_ratio"]), baseline: finiteMetric(baselineMetrics, ["sharpe", "sharpe_ratio"]), format: "number" },
      { label: "策略收益", value: finiteMetric(gridDiagnosticRow, ["strategy_return"]), baseline: baselineCurve.strategy?.totalReturn ?? null, format: "percent" },
      { label: "超额收益", value: finiteMetric(gridDiagnosticRow, ["excess_return"]), baseline: baselineCurve.excess ?? null, format: "percent" },
      { label: "净盈亏", value: finiteMetric(gridDiagnosticRow, ["total_net_pnl"]), baseline: finiteMetric(baselineMetrics, ["total_net_pnl"]), format: "money" },
      { label: "成交笔数", value: finiteMetric(gridDiagnosticRow, ["total_trade_count"]), baseline: finiteMetric(baselineMetrics, ["total_trade_count"]) ?? (Number.isFinite(Number(runDetail?.baseline_trades_count)) ? Number(runDetail.baseline_trades_count) : null), format: "integer" },
      { label: "手续费 + 滑点", value: candidateCosts, baseline: baselineCosts, format: "money" },
      { label: "最大回撤", value: finiteMetric(gridDiagnosticRow, ["max_drawdown_value", "max_drawdown"]), baseline: finiteMetric(baselineMetrics, ["max_drawdown_value", "max_drawdown"]), format: "money" },
      { label: "回撤持续", value: finiteMetric(gridDiagnosticRow, ["max_drawdown_duration"]), baseline: finiteMetric(baselineMetrics, ["max_drawdown_duration"]), format: "days" }
    ];
  }, [baselineMetrics, gridDiagnosticRow, runDetail?.baseline_trades_count, variantCurves.baseline]);

  const gridDiagnosticTradeRows = useMemo(() => gridDiagnosticRow ? [
    { label: "完整交易", value: finiteMetric(gridDiagnosticRow, ["closed_trade_count"]), format: "integer" },
    { label: "交易胜率", value: finiteMetric(gridDiagnosticRow, ["trade_win_rate"]), format: "percent" },
    { label: "平均盈亏比", value: finiteMetric(gridDiagnosticRow, ["profit_loss_ratio"]), format: "number" },
    { label: "Profit Factor", value: finiteMetric(gridDiagnosticRow, ["profit_factor"]), format: "number" },
    { label: "单笔毛期望", value: finiteMetric(gridDiagnosticRow, ["gross_expectancy"]), format: "money" },
    { label: "平均持仓", value: finiteMetric(gridDiagnosticRow, ["average_holding_minutes"]), format: "holding" },
    { label: "中位持仓", value: finiteMetric(gridDiagnosticRow, ["median_holding_minutes"]), format: "holding" },
    { label: "隔夜交易", value: finiteMetric(gridDiagnosticRow, ["overnight_trade_count"]), format: "integer" }
  ] : [], [gridDiagnosticRow]);

  const renderDiagnosticValue = useCallback((value: number | null, format: string) => {
    if (value === null) return "暂无";
    if (format === "percent") return formatReturnPct(value, 2);
    if (format === "integer") return formatNumber(value, 0);
    if (format === "money") return formatNumber(value, 3);
    if (format === "days") return `${formatNumber(value, 0)} 天`;
    if (format === "holding") return formatHoldingMinutes(value);
    return formatNumber(value, 2);
  }, []);

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
    for (const item of savedOptimizationCurves) {
      const key = savedOptimizationCurveKey(item.snapshot_id);
      const summary = curveSummary(chartVariantCurves[key] || []);
      rows.push({
        key,
        label: item.name,
        value: summary.strategy?.totalReturn,
        type: "strategy" as const
      });
    }
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
  }, [chartVariantCurves, curveVariantNames, filteredVariantCurves, primaryVariant, savedOptimizationCurves]);
  const orderedCurveKeys = useMemo(() => curveSelectorItems.map((item) => item.key), [curveSelectorItems]);
  const gridPreviewCurveKeys = useMemo(
    () => gridCandidatePreviews.map((preview) => gridPreviewCurveKey(preview.label)),
    [gridCandidatePreviews]
  );
  const chartVisibleCurveKeys = useMemo(
    () => Array.from(new Set([...visibleCurveKeys, ...gridPreviewCurveKeys])),
    [gridPreviewCurveKeys, visibleCurveKeys]
  );
  const chartOrderedCurveKeys = useMemo(
    () => [...orderedCurveKeys, ...gridPreviewCurveKeys],
    [gridPreviewCurveKeys, orderedCurveKeys]
  );
  const chartCurveLabels = useMemo<Record<string, string>>(() => {
    const labels: Record<string, string> = {};
    for (const item of savedOptimizationCurves) {
      labels[savedOptimizationCurveKey(item.snapshot_id)] = item.name;
    }
    for (const preview of gridCandidatePreviews) {
      labels[gridPreviewCurveKey(preview.label)] = `Grid #${preview.rank}`;
    }
    return labels;
  }, [gridCandidatePreviews, savedOptimizationCurves]);

  function toggleCurveVisibility(nextKey: string) {
    setVisibleCurveKeys((current) => current.includes(nextKey) ? current.filter((key) => key !== nextKey) : [...current, nextKey]);
  }

  function openCurveSnapshotManager() {
    setCurveSnapshotRenameDrafts(Object.fromEntries(savedOptimizationCurves.map((item) => [item.snapshot_id, item.name])));
    setCurveSnapshotManagerOpen(true);
  }

  function retainCurrentOptimizationCurve() {
    if (!runId || !retainableOptimizationVariant) return;
    let snapshotName = `${variantDisplayLabel(retainableOptimizationVariant)} ${new Date().toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    })}`;
    Modal.confirm({
      title: "保留优化曲线",
      content: (
        <Input
          size="small"
          maxLength={48}
          defaultValue={snapshotName}
          onChange={(event) => { snapshotName = event.target.value; }}
        />
      ),
      okText: "保留",
      cancelText: "取消",
      onOk: async () => {
        setCurveSnapshotBusyId("create");
        try {
          const payload = await createOptimizationCurveSnapshot(runId, retainableOptimizationVariant, snapshotName.trim());
          const item = payload?.item as SavedOptimizationCurve;
          if (!item?.snapshot_id || !Array.isArray(item?.curve)) throw new Error("保留曲线返回数据不完整");
          setSavedOptimizationCurves((current) => [item, ...current.filter((entry) => entry.snapshot_id !== item.snapshot_id)]);
          setVisibleCurveKeys((current) => Array.from(new Set([...current, savedOptimizationCurveKey(item.snapshot_id)])));
          message.success("优化曲线已保留");
        } catch (error) {
          message.error(String(error));
          throw error;
        } finally {
          setCurveSnapshotBusyId("");
        }
      }
    });
  }

  async function renameSavedOptimizationCurve(item: SavedOptimizationCurve) {
    const nextName = String(curveSnapshotRenameDrafts[item.snapshot_id] || "").trim();
    if (!nextName || nextName === item.name) return;
    setCurveSnapshotBusyId(item.snapshot_id);
    try {
      const payload = await renameOptimizationCurveSnapshot(item.snapshot_id, nextName);
      const updated = payload?.item as SavedOptimizationCurve;
      setSavedOptimizationCurves((current) => current.map((entry) => entry.snapshot_id === item.snapshot_id ? updated : entry));
      setCurveSnapshotRenameDrafts((current) => ({ ...current, [item.snapshot_id]: updated.name }));
      message.success("名称已更新");
    } catch (error) {
      message.error(String(error));
    } finally {
      setCurveSnapshotBusyId("");
    }
  }

  function confirmDeleteSavedOptimizationCurve(item: SavedOptimizationCurve) {
    Modal.confirm({
      title: `删除“${item.name}”？`,
      content: "只删除保留的曲线快照，不影响原始 Run 和优化结果。",
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setCurveSnapshotBusyId(item.snapshot_id);
        try {
          await deleteOptimizationCurveSnapshot(item.snapshot_id);
          const curveKey = savedOptimizationCurveKey(item.snapshot_id);
          setSavedOptimizationCurves((current) => current.filter((entry) => entry.snapshot_id !== item.snapshot_id));
          setVisibleCurveKeys((current) => current.filter((key) => key !== curveKey));
          message.success("保留曲线已删除");
        } catch (error) {
          message.error(String(error));
          throw error;
        } finally {
          setCurveSnapshotBusyId("");
        }
      }
    });
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

  const optimizeDraft = useMemo(() => ({
      selectedFamily,
      runId,
      method,
      objective,
      poolVariant,
      selectedParams,
      baseParameters,
      ranges,
      visibleCurveKeys,
      curveStartDate,
      curveEndDate,
      parameterDetailsCollapsed,
      performanceDetailsCollapsed,
    }), [baseParameters, curveEndDate, curveStartDate, method, objective, parameterDetailsCollapsed, performanceDetailsCollapsed, poolVariant, ranges, runId, selectedFamily, selectedParams, visibleCurveKeys]);
  const latestOptimizeDraftRef = useRef(optimizeDraft);
  latestOptimizeDraftRef.current = optimizeDraft;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      window.localStorage.setItem(OPTIMIZE_DRAFT_STORAGE_KEY, JSON.stringify(optimizeDraft));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [optimizeDraft]);

  useEffect(() => {
    const flushDraft = () => {
      window.localStorage.setItem(OPTIMIZE_DRAFT_STORAGE_KEY, JSON.stringify(latestOptimizeDraftRef.current));
    };
    window.addEventListener("pagehide", flushDraft);
    return () => window.removeEventListener("pagehide", flushDraft);
  }, []);

  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div>
          <p className="eyebrow">参数实验</p>
          <h2>{zh.optimize}</h2>
          <p className="hero-copy">按策略族选择运行版本，切换不同优化结果，并将最新结果加入策略池。</p>
        </div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{runs.length}</div><div className="metric-label">运行版本</div></div>
          <div className="metric-tile"><div className="metric-value">{searchSpace?.parameters?.length || 0}</div><div className="metric-label">可调参数</div></div>
          <div className="metric-tile"><div className="metric-value">{variants.length}</div><div className="metric-label">结果版本</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>运行版本</h3>
            <p>先选择策略族和运行版本，页面会直接展示该版本下的全部结果曲线。</p>
          </div>
          <span className={statusClass(runId ? "completed" : "pending")}>{runId ? "已就绪" : "待选择"}</span>
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
        {poolRunLineage && (
          <p className="band-note">来自策略池 · 原版本：{variantDisplayLabel(String(poolRunLineage.source_variant || poolRunLineage.source_variant_name || poolRunLineage.source_variant_id || "-"))} · 已重跑为基线</p>
        )}
      </section>

      <section ref={mainCurveSectionRef} className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>累计收益对比</h3>
            <p>手动网格展示最新结果；需要跨轮对比时可先留存一条曲线。</p>
          </div>
          <div className="optimization-curve-retention-actions">
            <Button
              type="text"
              size="small"
              loading={curveSnapshotBusyId === "create"}
              disabled={!retainableOptimizationVariant}
              title="复制当前优化曲线，后续优化不会覆盖"
              onClick={retainCurrentOptimizationCurve}
            >留存</Button>
            {savedOptimizationCurves.length > 0 && (
              <Button type="text" size="small" onClick={openCurveSnapshotManager}>已留 {savedOptimizationCurves.length}</Button>
            )}
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
        {chartVisibleCurveKeys.length > 0 && Object.keys(chartVariantCurves).length > 0 ? (
          <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={chartVariantCurves} visibleKeys={chartVisibleCurveKeys} labels={chartCurveLabels} orderedKeys={chartOrderedCurveKeys} showLegend={false} height={420} /></div>
        ) : curveSelectorItems.length > 0 ? (
          <div className="empty-state">当前没有展示的曲线，可在上方重新勾选。</div>
        ) : (
          <div className="empty-state">当前运行版本没有可展示的曲线。</div>
        )}
      </section>

      <Modal
        title="已保留曲线"
        open={curveSnapshotManagerOpen}
        width={520}
        footer={null}
        onCancel={() => setCurveSnapshotManagerOpen(false)}
      >
        <div className="optimization-curve-snapshot-list">
          {savedOptimizationCurves.map((item) => (
            <div className="optimization-curve-snapshot-row" key={item.snapshot_id}>
              <div className="optimization-curve-snapshot-copy">
                <Input
                  size="small"
                  maxLength={48}
                  value={curveSnapshotRenameDrafts[item.snapshot_id] ?? item.name}
                  onChange={(event) => setCurveSnapshotRenameDrafts((current) => ({
                    ...current,
                    [item.snapshot_id]: event.target.value
                  }))}
                />
                <small>{variantDisplayLabel(item.source_variant_name)} · {formatDate(item.created_at)} · {item.source_run_id}</small>
              </div>
              <Button
                type="text"
                size="small"
                loading={curveSnapshotBusyId === item.snapshot_id}
                disabled={!String(curveSnapshotRenameDrafts[item.snapshot_id] ?? item.name).trim() || String(curveSnapshotRenameDrafts[item.snapshot_id] ?? item.name).trim() === item.name}
                onClick={() => renameSavedOptimizationCurve(item)}
              >改名</Button>
              <Button type="text" danger size="small" onClick={() => confirmDeleteSavedOptimizationCurve(item)}>删</Button>
            </div>
          ))}
        </div>
      </Modal>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>绩效明细</h3>
            <p>这里统一展示当前运行版本下各结果版本的核心表现，不再重复显示参数列。</p>
          </div>
          <Button type="text" size="small" className="section-collapse-toggle" onClick={() => setPerformanceDetailsCollapsed((current) => !current)}>
            {performanceDetailsCollapsed ? "展开明细" : "收起明细"}
          </Button>
        </div>
        {!performanceDetailsCollapsed && (
          <Table rowKey="key" columns={performanceColumns} dataSource={performanceRows} pagination={false} scroll={{ x: 900 }} className="workbench-table performance-detail-table" />
        )}
      </section>

      <section className="band library-shell">
        <div className="library-section-head optimization-mode-head">
          <div className="optimization-title-block">
            <div className="collapsible-section-title">
              <h3>参数优化</h3>
              <Button type="text" size="small" className="section-collapse-toggle" onClick={() => setParameterDetailsCollapsed((current) => !current)}>
                {parameterDetailsCollapsed ? "展开参数" : "收起参数"}
              </Button>
            </div>
            <p>可直接修改本次默认值；未选中的参数按该值固定，选中的参数再按范围搜索。本次设置不会改写策略源文件。</p>
            {!parameterDetailsCollapsed && (
              <div className="optimization-suggestion-actions">
                <Button loading={suggestionLoading} disabled={!runId} onClick={generateSpaceSuggestion}>AI 生成参数范围</Button>
                <Button disabled={!runId || suggestionLoading} onClick={restoreStaticSpace}>恢复默认</Button>
              </div>
            )}
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
                  : "TPE 试验 200 次"
                : `网格 ${totalGridCount}`}
            </span>
          </div>
        </div>
        {!parameterDetailsCollapsed && suggestionProgress > 0 && (
          <div className="optimization-ai-progress">
            <div>
              <strong>{suggestionProgress >= 100 ? "参数范围已生成" : "AI 正在分析策略参数"}</strong>
              <span>{suggestionProgress >= 100 ? "请检查范围和启用状态" : "正在识别参数语义、约束和合理范围"}</span>
            </div>
            <Progress percent={suggestionProgress} status={suggestionProgress >= 100 ? "success" : "active"} showInfo={false} />
          </div>
        )}
        {!parameterDetailsCollapsed && (
          <>
            <div className="parameter-frame">
              <Table rowKey="name" columns={parameterColumns} dataSource={parameterRows} pagination={false} className="workbench-table parameter-table" />
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
          </>
        )}
        <div className="action-row optimization-run-row">
          <Button type="primary" loading={loading} disabled={!runId || (method === "manual_grid" && !selectedParams.length)} onClick={submitOptimization}>
            运行优化
          </Button>
        </div>
        {method === "manual_grid" && manualGridTopRows.length > 0 && (
          <div className="optimizer-grid-results">
            <div className="optimizer-grid-results-head">
              <strong>排名前 10 的参数组合</strong>
              <span>按当前评分方式排列 · 点击行添加或移除曲线，可同时对比多组</span>
            </div>
            <Table
              rowKey="key"
              columns={manualGridColumns}
              dataSource={manualGridTableRows}
              pagination={false}
              size="small"
              scroll={{ x: manualGridTableWidth }}
              rowClassName={(record) => [
                Number(record.rank) === 1 ? "optimizer-grid-first" : "",
                gridCandidatePreviews.some((preview) => preview.label === String(record.label || "")) ? "optimizer-grid-preview-selected" : ""
              ].filter(Boolean).join(" ")}
              onRow={(record) => {
                const candidateLabel = String(record.label || "");
                const selectedIndex = gridCandidatePreviews.findIndex((preview) => preview.label === candidateLabel);
                const previewColor = selectedIndex >= 0
                  ? curveColorForKey(
                      gridPreviewCurveKey(candidateLabel),
                      `Grid #${record.rank}`,
                      "strategy",
                      chartOrderedCurveKeys,
                      orderedCurveKeys.length + selectedIndex
                    )
                  : undefined;
                return {
                  tabIndex: 0,
                  style: previewColor ? { "--grid-preview-color": previewColor } as React.CSSProperties : undefined,
                  onClick: () => toggleGridCandidatePreview(record),
                  onKeyDown: (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      toggleGridCandidatePreview(record);
                    }
                  }
                };
              }}
              className="workbench-table optimizer-grid-table"
            />
          </div>
        )}
      </section>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>加入策略池</h3>
            <p>曲线和绩效明细会同时展示全部结果版本，加入策略池时再选择目标版本。</p>
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
            <span className="summary-label">入池名称前缀</span>
            <Input value={poolStrategyName} onChange={(event) => setPoolStrategyName(poolNamePrefix(event.target.value))} placeholder="只填写名称，版本由入池时间生成" />
            <small className="pool-version-hint">入池后自动显示为“名称 | 快照版本”</small>
          </div>
          <div className="viewer-summary-card"><span className="summary-label">版本夏普比率</span><strong>{formatNumber(poolVariantMetrics.sharpe ?? poolVariantMetrics.sharpe_ratio)}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">版本交易次数</span><strong>{Number.isFinite(Number(poolVariantTradeCount)) ? String(poolVariantTradeCount) : "-"}</strong></div>
          <div className="viewer-summary-card pool-note-input-card">
            <span className="summary-label">入池备注</span>
            <Input.TextArea
              value={poolNote}
              onChange={(event) => setPoolNote(event.target.value)}
              autoSize={{ minRows: 1, maxRows: 3 }}
              maxLength={500}
              placeholder="可选，记录策略特点、适用场景或注意事项。"
            />
          </div>
        </div>
      </section>

      <Drawer
        title={gridDiagnosticRow ? `参数诊断 · #${String(gridDiagnosticRow.rank || "-")}` : "参数诊断"}
        placement="right"
        width={480}
        open={Boolean(gridDiagnosticRow)}
        onClose={() => setGridDiagnosticRow(null)}
        className="optimizer-diagnostic-drawer"
      >
        {gridDiagnosticRow && (
          <div className="optimizer-diagnostic-content">
            <div className="optimizer-diagnostic-parameters">
              <span>候选参数</span>
              <div>
                {Object.entries(gridDiagnosticRow.parsedParameters || {}).map(([name, value]) => (
                  <em key={name}>{name}={formatParameterValue(value)}</em>
                ))}
              </div>
            </div>

            <section>
              <div className="optimizer-diagnostic-section-head">
                <strong>核心表现</strong>
                <small>候选组合与本次 Baseline</small>
              </div>
              <div className="optimizer-diagnostic-comparison-grid">
                {gridDiagnosticCoreRows.map((item) => (
                  <div className="optimizer-diagnostic-metric" key={item.label}>
                    <span>{item.label}</span>
                    <strong>{renderDiagnosticValue(item.value, item.format)}</strong>
                    <small>Baseline {renderDiagnosticValue(item.baseline, item.format)}</small>
                  </div>
                ))}
              </div>
            </section>

            <section>
              <div className="optimizer-diagnostic-section-head">
                <strong>交易结构</strong>
                <small>毛盈亏口径，不含手续费与滑点</small>
              </div>
              {gridDiagnosticTradeRows.some((item) => item.value !== null) ? (
                <div className="optimizer-diagnostic-comparison-grid compact">
                  {gridDiagnosticTradeRows.map((item) => (
                    <div className="optimizer-diagnostic-metric" key={item.label}>
                      <span>{item.label}</span>
                      <strong>{renderDiagnosticValue(item.value, item.format)}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="optimizer-diagnostic-empty">
                  该历史网格没有保存交易结构摘要。重新运行参数优化后会自动生成，无需保存完整候选成交记录。
                </div>
              )}
            </section>

            <p className="optimizer-diagnostic-note">
              点击候选行仍只负责预览曲线；诊断抽屉不会触发回测或网络计算。MFE/MAE 需要持仓期间逐 K 路径，暂未纳入轻量摘要。
            </p>
          </div>
        )}
      </Drawer>
    </section>
  );
}
