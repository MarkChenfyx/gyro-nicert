import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Checkbox, Drawer, Input, InputNumber, Modal, Progress, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  addToPool,
  archiveTerminalTasks,
  comparePool,
  continuePoolOptimization,
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
  updatePoolNotes,
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
  CurveControlItem,
  CurveControls
} from "../app/ui";

const POOL_QUICK_LIMIT_STORAGE_KEY = "gyro_nicert.pool_quick_limit";

function loadPoolQuickLimit() {
  const stored = Number(window.localStorage.getItem(POOL_QUICK_LIMIT_STORAGE_KEY) || 5);
  return Number.isFinite(stored) ? Math.max(1, Math.min(50, Math.round(stored))) : 5;
}

export default function PoolPage({
  poolItems,
  poolNavigation,
  onPoolNavigationApplied,
  refreshPool,
  refreshTasks,
  onContinueOptimization
}: {
  poolItems: any[];
  poolNavigation: { poolItemId: string; vtSymbol: string; requestId: number } | null;
  onPoolNavigationApplied: (requestId: number) => void;
  refreshPool: () => Promise<void>;
  refreshTasks: () => Promise<void>;
  onContinueOptimization: (runId: string) => void;
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [displayedCurveIds, setDisplayedCurveIds] = useState<string[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [searchText, setSearchText] = useState("");
  const [selectionMode, setSelectionMode] = useState("recent");
  const [quickLimit, setQuickLimit] = useState(loadPoolQuickLimit);
  const [quickLimitDraft, setQuickLimitDraft] = useState<number | null>(() => loadPoolQuickLimit());
  const [poolSortKey, setPoolSortKey] = useState<"created_at" | "total_return" | "sharpe" | "trade_count" | "max_drawdown" | "excess_return">("created_at");
  const [poolSortOrder, setPoolSortOrder] = useState<"asc" | "desc">("desc");
  const [selectedDetailId, setSelectedDetailId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [comparison, setComparison] = useState<any>({ items: [], benchmark: { curve: [] }, diagnostics: [] });
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [rerunProgress, setRerunProgress] = useState(0);
  const [rerunMessage, setRerunMessage] = useState("");
  const [continuingPoolItemId, setContinuingPoolItemId] = useState("");
  const [editingNotes, setEditingNotes] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [poolRerunStartDate, setPoolRerunStartDate] = useState("");
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [curveStartDate, setCurveStartDate] = useState("");
  const [curveEndDate, setCurveEndDate] = useState("");
  const [curveReturnCache, setCurveReturnCache] = useState<Record<string, number>>({});
  const [poolSelectionInitialized, setPoolSelectionInitialized] = useState(false);
  const presetRequestRef = useRef(0);
  const comparisonRequestRef = useRef(0);

  function itemTags(item: any): string[] {
    try {
      const parsed = JSON.parse(item?.tags || "[]");
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch {
      return [];
    }
  }

  function poolItemLabel(item: any) {
    return strategyLabel(item);
  }

  function compareItemLabel(item: any) {
    return `${strategyLabel(item)} | ${item.variant_name || "-"} | ${item.vt_symbol || "-"}`;
  }

  function metricValue(metrics: any, ...names: string[]) {
    for (const name of names) {
      const value = Number(metrics?.[name]);
      if (Number.isFinite(value)) return value;
    }
    return null;
  }

  function excessReturn(item: any) {
    const summary = curveSummary(item?.curve || []);
    const strategy = summary.strategy?.totalReturn;
    const benchmark = summary.buyHold?.totalReturn;
    if (strategy === undefined || benchmark === undefined) return null;
    if (!Number.isFinite(strategy) || !Number.isFinite(benchmark)) return null;
    return strategy - benchmark;
  }

  function strategyCurveMetrics(item: any) {
    const summary = curveSummary(item?.curve || []);
    return {
      totalReturn: summary.strategy?.totalReturn ?? null,
      maxDrawdown: summary.strategy?.maxDrawdown ?? null,
      buyHoldReturn: summary.buyHold?.totalReturn ?? null,
      excessReturn: excessReturn(item),
      tradeCount: Number(item?.trade_count ?? item?.trades_preview?.length ?? 0),
      sharpe: metricValue(item?.metrics, "sharpe", "sharpe_ratio"),
    };
  }

  function togglePoolSort(nextKey: "created_at" | "total_return" | "sharpe" | "trade_count" | "max_drawdown" | "excess_return") {
    if (poolSortKey === nextKey) {
      setPoolSortOrder((current) => current === "desc" ? "asc" : "desc");
      return;
    }
    setPoolSortKey(nextKey);
    setPoolSortOrder("desc");
  }

  function sortArrow(key: "created_at" | "total_return" | "sharpe" | "trade_count" | "max_drawdown" | "excess_return") {
    if (poolSortKey !== key) return null;
    return poolSortOrder === "desc" ? "down" : "up";
  }

  function SortCaret({ state }: { state: "up" | "down" | null }) {
    return (
      <span className={`table-sort-caret ${state ? `is-${state}` : ""}`} aria-hidden="true">
        <span />
        <span />
      </span>
    );
  }

  const symbols = useMemo(() => Array.from(new Set(poolItems.map((item) => String(item.vt_symbol || "")).filter(Boolean))).sort(), [poolItems]);
  const latestCreatedAt = useMemo(() => poolItems.map((item) => String(item.created_at || "")).sort().at(-1), [poolItems]);
  const candidateItems = useMemo(() => {
    const needle = searchText.trim().toLowerCase();
    return poolItems
      .filter((item) => !selectedSymbol || String(item.vt_symbol || "") === selectedSymbol)
      .filter((item) => {
        if (!needle) return true;
        return [
          item.pool_item_id,
          item.strategy_id,
          strategyLabel(item),
          item.source_run_id,
          item.source_variant_id,
          item.vt_symbol,
          item.created_at,
          ...itemTags(item)
        ].map((value) => String(value || "").toLowerCase()).some((value) => value.includes(needle));
      });
  }, [poolItems, searchText, selectedSymbol]);

  function presetItems(mode = selectionMode, records = candidateItems, limit = quickLimit) {
    const safeLimit = Math.max(1, Math.min(50, Math.round(Number(limit) || 5)));
    if (mode === "top_sharpe") {
      return records.slice().sort((a, b) => Number(b.sharpe ?? -Infinity) - Number(a.sharpe ?? -Infinity)).slice(0, safeLimit);
    }
    if (mode === "top_excess") {
      return records
        .slice()
        .sort((a, b) => Number(strategyCurveMetrics(b).excessReturn ?? -Infinity) - Number(strategyCurveMetrics(a).excessReturn ?? -Infinity))
        .slice(0, safeLimit);
    }
    if (mode === "recent") {
      return records.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, safeLimit);
    }
    return records;
  }

  async function applyPreset(mode: string, limit = quickLimit) {
    const requestId = ++presetRequestRef.current;
    setSelectionMode(mode);
    if (mode !== "top_excess") {
      const nextIds = presetItems(mode, candidateItems, limit).map((item) => String(item.pool_item_id));
      setDisplayedCurveIds(nextIds);
      setSelectedIds(nextIds);
      return;
    }
    const candidateIds = candidateItems.map((item) => String(item.pool_item_id)).filter(Boolean);
    if (!candidateIds.length) {
      setDisplayedCurveIds([]);
      setSelectedIds([]);
      return;
    }
    setLoading(true);
    try {
      const payload = await comparePool(candidateIds);
      if (requestId !== presetRequestRef.current) return;
      const nextIds = presetItems("top_excess", payload.items || [], limit).map((item) => String(item.pool_item_id));
      setDisplayedCurveIds(nextIds);
      setSelectedIds(nextIds);
    } catch (error) {
      if (requestId === presetRequestRef.current) message.error(String(error));
    } finally {
      if (requestId === presetRequestRef.current) setLoading(false);
    }
  }

  function commitQuickLimit() {
    const resolved = Math.max(1, Math.min(50, Math.round(Number(quickLimitDraft) || quickLimit || 5)));
    setQuickLimit(resolved);
    setQuickLimitDraft(resolved);
    window.localStorage.setItem(POOL_QUICK_LIMIT_STORAGE_KEY, String(resolved));
    if (selectionMode !== "all") void applyPreset(selectionMode, resolved);
  }

  function togglePoolItem(poolItemId: string) {
    setSelectedIds((current) => current.includes(poolItemId)
      ? current.filter((value) => value !== poolItemId)
      : Array.from(new Set([...current, poolItemId])));
  }

  async function openItem(record: any) {
    const poolItemId = String(record.pool_item_id || "");
    setSelectedDetailId(poolItemId);
    setLoading(true);
    try {
      const detailPayload = await getPoolItem(poolItemId);
      setDetail(detailPayload);
      setNoteDraft(String(detailPayload?.notes || ""));
      setEditingNotes(false);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoading(false);
    }
  }

  async function continueOptimizationFromPool() {
    const poolItemId = String(detail?.pool_item?.pool_item_id || "");
    if (!poolItemId) return;
    setContinuingPoolItemId(poolItemId);
    try {
      const payload = await continuePoolOptimization(poolItemId);
      const newRunId = String(payload?.baseline?.run?.run_id || "");
      if (!newRunId) throw new Error("重跑完成，但没有返回新的运行版本");
      await refreshTasks();
      message.success("已重跑为新的基线，正在打开参数优化");
      onContinueOptimization(newRunId);
    } catch (error) {
      message.error(`继续参数优化失败：${String(error)}`);
    } finally {
      setContinuingPoolItemId("");
    }
  }

  function beginEditingNotes() {
    setNoteDraft(String(detail?.notes || ""));
    setEditingNotes(true);
  }

  function cancelEditingNotes() {
    setNoteDraft(String(detail?.notes || ""));
    setEditingNotes(false);
  }

  async function saveNotes() {
    const poolItemId = String(detail?.pool_item?.pool_item_id || "");
    if (!poolItemId || savingNotes) return;
    setSavingNotes(true);
    try {
      const payload = await updatePoolNotes(poolItemId, noteDraft);
      const savedNote = String(payload?.note ?? noteDraft);
      setDetail((current: any) => String(current?.pool_item?.pool_item_id || "") === poolItemId
        ? { ...current, notes: savedNote }
        : current);
      setNoteDraft(savedNote);
      setEditingNotes(false);
      message.success("备注已保存");
    } catch (error) {
      message.error(`备注保存失败：${String(error)}`);
    } finally {
      setSavingNotes(false);
    }
  }

  async function rerunSelectedToToday() {
    if (!selectedIds.length) {
      message.warning("请至少选择一个策略。");
      return;
    }
    if (!poolRerunStartDate) {
      message.warning("请选择重跑开始日期。");
      return;
    }
    setRerunning(true);
    setRerunProgress(0.02);
    setRerunMessage("正在创建重跑任务");
    const startedAt = Date.now();
    const progressTimer = window.setInterval(() => {
      listTasks()
        .then((payload) => {
          const task = (payload.tasks || []).find((item: any) => {
            if (item.task_type !== "pool_rebuild") return false;
            const createdAt = new Date(String(item.created_at || "")).getTime();
            return !Number.isFinite(createdAt) || createdAt >= startedAt - 5000;
          });
          if (!task) return;
          setRerunProgress(Math.max(0.02, Math.min(1, Number(task.progress || 0))));
          setRerunMessage(String(task.message || "正在重跑策略"));
        })
        .catch(() => undefined);
    }, 700);
    try {
      const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
      const payload = await rerunPool(selectedIds, poolRerunStartDate, today);
      setComparison(payload);
      setCurveReturnCache((current) => {
        const next = { ...current };
        for (const item of payload?.items || []) {
          const poolItemId = String(item?.pool_item_id || "");
          const totalReturn = curveSummary(item?.curve || []).strategy?.totalReturn;
          if (poolItemId && Number.isFinite(totalReturn)) next[poolItemId] = Number(totalReturn);
        }
        return next;
      });
      setRerunProgress(1);
      setRerunMessage("策略池重跑完成");
      await refreshTasks();
      const rerunEnd = String(payload?.rerun_end || "").trim();
      message.success(rerunEnd ? `已重跑到 ${formatDate(rerunEnd)}` : "已完成重跑");
    } catch (error) {
      setRerunMessage(`重跑失败：${String(error)}`);
      message.error(String(error));
    } finally {
      window.clearInterval(progressTimer);
      setRerunning(false);
    }
  }

  useEffect(() => {
    if (!poolItems.length) {
      presetRequestRef.current += 1;
      setSelectedSymbol("");
      setDisplayedCurveIds([]);
      setSelectedIds([]);
      setPoolSelectionInitialized(false);
      return;
    }
    const nextSymbol = selectedSymbol && symbols.includes(selectedSymbol) ? selectedSymbol : symbols[0] || "";
    if (nextSymbol !== selectedSymbol) {
      presetRequestRef.current += 1;
      setPoolSelectionInitialized(false);
      setDisplayedCurveIds([]);
      setSelectedIds([]);
      setSelectedSymbol(nextSymbol);
    }
  }, [poolItems, selectedSymbol, symbols]);

  useEffect(() => {
    if (!poolNavigation || !poolItems.length) return;
    const targetItem = poolItems.find((item) => String(item.pool_item_id || "") === poolNavigation.poolItemId);
    if (poolNavigation.poolItemId && !targetItem) return;
    const targetSymbol = String(poolNavigation.vtSymbol || targetItem?.vt_symbol || "").trim();
    if (!targetSymbol) return;
    const symbolItems = poolItems.filter((item) => String(item.vt_symbol || "") === targetSymbol);
    if (!symbolItems.length) return;
    const recentItems = presetItems("recent", symbolItems, quickLimit);
    const selected = [
      ...(targetItem ? [targetItem] : []),
      ...recentItems.filter((item) => String(item.pool_item_id || "") !== poolNavigation.poolItemId)
    ].slice(0, quickLimit);
    presetRequestRef.current += 1;
    setSearchText("");
    setSelectedSymbol(targetSymbol);
    setSelectionMode("recent");
    const selectedPoolIds = selected.map((item) => String(item.pool_item_id));
    setDisplayedCurveIds(selectedPoolIds);
    setSelectedIds(selectedPoolIds);
    setPoolSelectionInitialized(true);
    onPoolNavigationApplied(poolNavigation.requestId);
  }, [onPoolNavigationApplied, poolItems, poolNavigation, quickLimit]);

  useEffect(() => {
    if (poolNavigation) return;
    if (!selectedSymbol) return;
    const candidateIds = candidateItems.map((item) => String(item.pool_item_id));
    const displayed = displayedCurveIds.filter((id) => candidateIds.includes(id));
    const kept = selectedIds.filter((id) => candidateIds.includes(id));
    if (displayed.length !== displayedCurveIds.length || kept.length !== selectedIds.length) {
      setDisplayedCurveIds(displayed);
      setSelectedIds(kept);
      return;
    }
    if (!poolSelectionInitialized && !displayed.length && candidateItems.length) {
      const nextIds = presetItems(selectionMode, candidateItems).map((item) => String(item.pool_item_id));
      setDisplayedCurveIds(nextIds);
      setSelectedIds(nextIds);
      setPoolSelectionInitialized(true);
    }
  }, [candidateItems, displayedCurveIds, poolNavigation, poolSelectionInitialized, selectedIds, selectedSymbol, selectionMode]);

  useEffect(() => {
    const requestId = ++comparisonRequestRef.current;
    if (!selectedIds.length) {
      setComparison({ items: [], benchmark: { curve: [] }, diagnostics: [] });
      return;
    }
    setLoading(true);
    comparePool(selectedIds)
      .then((payload) => {
        if (requestId !== comparisonRequestRef.current) return;
        setComparison(payload);
        setCurveReturnCache((current) => {
          const next = { ...current };
          for (const item of payload?.items || []) {
            const poolItemId = String(item?.pool_item_id || "");
            const totalReturn = curveSummary(item?.curve || []).strategy?.totalReturn;
            if (poolItemId && Number.isFinite(totalReturn)) next[poolItemId] = Number(totalReturn);
          }
          return next;
        });
      })
      .catch((error) => {
        if (requestId === comparisonRequestRef.current) message.error(String(error));
      })
      .finally(() => {
        if (requestId === comparisonRequestRef.current) setLoading(false);
      });
  }, [selectedIds]);

  const compareItems = useMemo(() => {
    const items = [...(comparison?.items || [])];
    const direction = poolSortOrder === "desc" ? -1 : 1;
    if (poolSortKey === "created_at") {
      items.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")) * direction);
      return items;
    }
    items.sort((a, b) => {
      const aMetrics = strategyCurveMetrics(a);
      const bMetrics = strategyCurveMetrics(b);
      const aValue = poolSortKey === "total_return"
        ? Number(aMetrics.totalReturn ?? -Infinity)
        : poolSortKey === "sharpe"
          ? Number(aMetrics.sharpe ?? -Infinity)
          : poolSortKey === "max_drawdown"
            ? Number(aMetrics.maxDrawdown ?? -Infinity)
            : poolSortKey === "excess_return"
              ? Number(aMetrics.excessReturn ?? -Infinity)
              : Number(aMetrics.tradeCount ?? -Infinity);
      const bValue = poolSortKey === "total_return"
        ? Number(bMetrics.totalReturn ?? -Infinity)
        : poolSortKey === "sharpe"
          ? Number(bMetrics.sharpe ?? -Infinity)
          : poolSortKey === "max_drawdown"
            ? Number(bMetrics.maxDrawdown ?? -Infinity)
            : poolSortKey === "excess_return"
              ? Number(bMetrics.excessReturn ?? -Infinity)
              : Number(bMetrics.tradeCount ?? -Infinity);
      return (aValue - bValue) * direction;
    });
    return items;
  }, [comparison, poolSortKey, poolSortOrder]);
  const compareCurves = useMemo(() => Object.fromEntries(compareItems.map((item: any) => [item.pool_item_id, item.curve || []])), [compareItems]);
  const poolCurveDateBounds = useMemo(
    () => curveDateBoundsForRows(Object.values(compareCurves).flatMap((rows: any) => rows)),
    [compareCurves]
  );

  useEffect(() => {
    if (!poolCurveDateBounds.min || !poolCurveDateBounds.max) return;
    setCurveStartDate((current) => {
      if (!current || current < poolCurveDateBounds.min) return poolCurveDateBounds.min;
      if (current > poolCurveDateBounds.max) return poolCurveDateBounds.max;
      return current;
    });
    setCurveEndDate((current) => {
      if (!current || current > poolCurveDateBounds.max) return poolCurveDateBounds.max;
      if (current < poolCurveDateBounds.min) return poolCurveDateBounds.min;
      return current;
    });
  }, [poolCurveDateBounds.max, poolCurveDateBounds.min]);

  const filteredCompareCurves = useMemo(
    () => Object.fromEntries(Object.entries(compareCurves).map(([key, rows]) => [key, clampDateRange(rows as any[], curveStartDate, curveEndDate)])),
    [compareCurves, curveEndDate, curveStartDate]
  );
  const compareLabels = useMemo(() => Object.fromEntries(compareItems.map((item: any) => [item.pool_item_id, compareItemLabel(item)])), [compareItems]);
  const poolVisibleKeys = useMemo(() => [...selectedIds, ...(showBenchmark ? ["buy_hold"] : [])], [selectedIds, showBenchmark]);
  const displayedCurveItems = useMemo(() => {
    const candidateById = new Map(candidateItems.map((item) => [String(item.pool_item_id), item]));
    return displayedCurveIds.map((id) => candidateById.get(id)).filter(Boolean);
  }, [candidateItems, displayedCurveIds]);
  const poolCurveControlItems = useMemo<CurveControlItem[]>(() =>
    displayedCurveItems.map((item: any) => {
      const poolItemId = String(item.pool_item_id);
      const totalReturn = curveReturnCache[poolItemId] ?? curveSummary(item?.curve || []).strategy?.totalReturn;
      return {
        key: poolItemId,
        label: poolItemLabel(item),
        type: "strategy" as const,
        value: totalReturn,
        detail: `${item.vt_symbol || "-"} · ${formatReturnPct(totalReturn, 2)}`
      };
    }),
  [curveReturnCache, displayedCurveItems]);

  function applyPoolCurveShortcut(range: "3m" | "6m" | "1y" | "all") {
    const next = shortcutDateRange(poolCurveDateBounds, range);
    setCurveStartDate(next.start);
    setCurveEndDate(next.end);
  }
  const comparisonColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "池内名称",
        dataIndex: "strategy_name",
        width: 330,
        render: (value, record) => (
          <div className="strategy-pool-name-cell">
            <strong>{strategyLabel(record)}</strong>
            <span>{record.pool_item_id}</span>
          </div>
        )
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("created_at")}>
            入池时间 <SortCaret state={sortArrow("created_at")} />
          </button>
        ),
        dataIndex: "created_at",
        width: 136,
        render: (value) => formatDate(value).slice(0, 16)
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("total_return")}>
            累计收益 <SortCaret state={sortArrow("total_return")} />
          </button>
        ),
        width: 104,
        render: (_, record) => formatReturnPct(strategyCurveMetrics(record).totalReturn)
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("trade_count")}>
            交易次数 <SortCaret state={sortArrow("trade_count")} />
          </button>
        ),
        width: 82,
        render: (_, record) => formatNumber(strategyCurveMetrics(record).tradeCount, 0)
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("sharpe")}>
            {zh.sharpe} <SortCaret state={sortArrow("sharpe")} />
          </button>
        ),
        width: 96,
        render: (_, record) => formatNumber(metricValue(record.metrics, "sharpe", "sharpe_ratio"))
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("max_drawdown")}>
            最大回撤 <SortCaret state={sortArrow("max_drawdown")} />
          </button>
        ),
        width: 104,
        render: (_, record) => formatReturnPct(strategyCurveMetrics(record).maxDrawdown)
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("excess_return")}>
            超额收益 <SortCaret state={sortArrow("excess_return")} />
          </button>
        ),
        width: 104,
        render: (_, record) => formatReturnPct(strategyCurveMetrics(record).excessReturn)
      },
      {
        title: "操作",
        width: 86,
        render: (_, record) => (
          <div className="strategy-pool-action-stack">
            <Button size="small" danger onClick={() => handleDeletePoolItem(String(record.pool_item_id))}>移除</Button>
            <Button size="small" onClick={() => openItem(record)}>查看</Button>
          </div>
        )
      }
    ],
    [comparison, poolSortKey, poolSortOrder]
  );

  async function handleDeletePoolItem(poolItemId: string) {
    Modal.confirm({
      title: "确认移除",
      content: `确定要将 ${poolItemId} 从策略池中移除吗？此操作不可撤销，相关的快照文件也会被删除。`,
      okText: "确认移除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          await removeFromPool(poolItemId);
          message.success(`已从策略池移除 ${poolItemId}`);
          setSelectedIds((current) => current.filter((id) => id !== poolItemId));
          if (selectedDetailId === poolItemId) setDetail(null);
          await refreshPool();
          await refreshTasks();
        } catch (error) {
          message.error(String(error));
        }
      }
    });
  }

  const metrics = detail?.result?.metrics || detail?.result || {};
  const detailCurveSummary = curveSummary(detail?.daily_results?.data || []);
  const detailParams = detail?.params || {};
  const resultParams = detail?.result?.recommended?.parameters || detail?.result?.params || detail?.result?.parameters || {};
  const params = detail?.config?.parameters || detail?.manifest?.parameters || detailParams || resultParams || {};
  const trades = detail?.trades?.data || [];
  const sortedTrades = useMemo(() => [...trades].sort((left: any, right: any) => {
    const leftDatetime = String(left?.datetime || left?.date || left?.trading_day || "");
    const rightDatetime = String(right?.datetime || right?.date || right?.trading_day || "");
    const datetimeOrder = rightDatetime.localeCompare(leftDatetime, "zh-CN", { numeric: true });
    if (datetimeOrder !== 0) return datetimeOrder;
    return String(right?.tradeid || "").localeCompare(String(left?.tradeid || ""), "zh-CN", { numeric: true });
  }), [trades]);
  const tradeValueLabel = (value: unknown, labels: Record<string, string>) => {
    const text = String(value ?? "").trim();
    return labels[text.toLowerCase()] || text || "-";
  };
  const tradeColumns: ColumnsType<any> = [
    {
      title: "成交时间",
      key: "datetime",
      width: 180,
      render: (_, row) => formatDate(row?.datetime || row?.date || row?.trading_day)
    },
    {
      title: "方向",
      dataIndex: "direction",
      width: 72,
      render: (value) => tradeValueLabel(value, { long: "多", short: "空", "direction.long": "多", "direction.short": "空" })
    },
    {
      title: "开平",
      dataIndex: "offset",
      width: 82,
      render: (value) => tradeValueLabel(value, {
        open: "开仓",
        close: "平仓",
        closetoday: "平今",
        closeyesterday: "平昨",
        "offset.open": "开仓",
        "offset.close": "平仓",
        "offset.closetoday": "平今",
        "offset.closeyesterday": "平昨"
      })
    },
    {
      title: "成交价格",
      dataIndex: "price",
      width: 110,
      align: "right"
    },
    {
      title: "数量",
      dataIndex: "volume",
      width: 80,
      align: "right"
    },
    {
      title: "标的",
      key: "symbol",
      width: 130,
      render: (_, row) => {
        const symbol = String(row?.vt_symbol || row?.symbol || "").trim();
        const exchange = String(row?.exchange || "").replace(/^Exchange\./i, "").trim();
        if (!symbol) return "-";
        return exchange && !symbol.toUpperCase().endsWith(`.${exchange.toUpperCase()}`) ? `${symbol}.${exchange}` : symbol;
      }
    },
    { title: "交易编号", dataIndex: "tradeid", width: 130, ellipsis: true },
    { title: "订单编号", dataIndex: "orderid", width: 130, ellipsis: true }
  ];

  return (
    <section className="view is-active">
      <div className="hero-band library-hero-band">
        <div>
          <p className="eyebrow">策略池</p>
          <h2>{zh.pool}</h2>
          <p className="hero-copy">已经确认的策略快照会集中放在这里，方便筛选、对比和查看详情。</p>
        </div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{poolItems.length}</div><div className="metric-label">池内条目</div></div>
          <div className="metric-tile"><div className="metric-value">{new Set(poolItems.map((item) => item.vt_symbol).filter(Boolean)).size}</div><div className="metric-label">标的数量</div></div>
          <div className="metric-tile"><div className="metric-value">{latestCreatedAt ? formatDate(latestCreatedAt).slice(5, 16) : "-"}</div><div className="metric-label">最近加入</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>筛选条件</h3>
            <p>选择标的、搜索策略，然后勾选要对比的策略池条目。</p>
          </div>
          <Button onClick={() => refreshPool().catch((error) => message.error(String(error)))}>{zh.refresh}</Button>
        </div>
        <div className="strategy-pool-filter-grid">
          <label className="field library-folder-field">
            <span>标的</span>
            <Select value={selectedSymbol || undefined} onChange={(value) => { presetRequestRef.current += 1; setSelectionMode("recent"); setPoolSelectionInitialized(false); setSelectedSymbol(value); setDisplayedCurveIds([]); setSelectedIds([]); }} options={symbols.map((item) => ({ value: item, label: item }))} />
          </label>
          <label className="field library-folder-field">
            <span>策略搜索</span>
            <Input value={searchText} onChange={(event) => { presetRequestRef.current += 1; setPoolSelectionInitialized(false); setSearchText(event.target.value); setDisplayedCurveIds([]); setSelectedIds([]); }} placeholder="策略 / 运行版本 / 结果版本 / 标签" />
          </label>
          <div className="field library-folder-field strategy-pool-preset-field">
            <div className="strategy-pool-preset-head">
              <span>快捷选择</span>
              <div className="strategy-pool-limit-control">
                <span>条数</span>
                <InputNumber
                  size="small"
                  min={1}
                  max={50}
                  precision={0}
                  controls={false}
                  value={quickLimitDraft}
                  onChange={(value) => setQuickLimitDraft(value === null ? null : Number(value))}
                  onKeyDown={(event) => { if (event.key === "Enter") commitQuickLimit(); }}
                />
                <Button type="text" size="small" onClick={commitQuickLimit}>确定</Button>
              </div>
            </div>
            <div className="strategy-pool-preset-buttons">
              {([
                ["all", `全部（${candidateItems.length}）`],
                ["top_sharpe", "最高夏普"],
                ["top_excess", "最高超额"],
                ["recent", "最近"]
              ] as Array<[string, string]>).map(([key, label]) => (
                <button type="button" key={key} className={selectionMode === key ? "is-active" : ""} onClick={() => applyPreset(key)}>{label}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="strategy-pool-date-action">
          <label className="field strategy-pool-rerun-mode-field">
            <span>重跑开始日期</span>
            <Input
              type="date"
              value={poolRerunStartDate}
              max={new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" })}
              onChange={(event) => setPoolRerunStartDate(event.target.value)}
            />
          </label>
          <Button type="primary" disabled={!selectedIds.length || !poolRerunStartDate} loading={rerunning} onClick={rerunSelectedToToday}>重跑到今天</Button>
          <span>
            {comparison?.rerun_end
              ? `当前对比结果重跑区间：${formatDate(comparison.rerun_start || poolRerunStartDate)} 至 ${formatDate(comparison.rerun_end)}。`
              : poolRerunStartDate ? `将从 ${formatDate(poolRerunStartDate)} 重跑到今天。` : "请选择开始日期后重跑。"}
          </span>
          {(rerunning || rerunProgress > 0) && (
            <div className={`pool-rerun-progress ${rerunning ? "is-running" : "is-complete"}`}>
              <div className="pool-rerun-progress-head">
                <strong>{rerunMessage || "正在准备重跑"}</strong>
                <span>{Math.round(rerunProgress * 100)}%</span>
              </div>
              <div className="pool-rerun-progress-track"><span style={{ width: `${Math.round(rerunProgress * 100)}%` }} /></div>
            </div>
          )}
        </div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>累计收益对比</h3><p>已选择 {selectedIds.length} 个策略，展示其按昨收归一并逐日累加后的收益曲线。</p></div><span className={statusClass(compareItems.length ? "completed" : "pending")}>{compareItems.length ? "已就绪" : "暂无曲线"}</span></div>
        <CurveControls
          items={poolCurveControlItems}
          visibleKeys={selectedIds}
          startDate={curveStartDate}
          endDate={curveEndDate}
          bounds={poolCurveDateBounds}
          onToggle={togglePoolItem}
          onSelectAll={() => setSelectedIds(displayedCurveIds)}
          onClear={() => setSelectedIds([])}
          onStartDateChange={setCurveStartDate}
          onEndDateChange={setCurveEndDate}
          onShortcut={applyPoolCurveShortcut}
        />
        <div className="pool-benchmark-toggle-row">
          <label className="pool-benchmark-toggle">
            <input type="checkbox" checked={showBenchmark} onChange={(event) => setShowBenchmark(event.target.checked)} disabled={!selectedIds.length} />
            <span className="curve-swatch is-dashed" style={{ borderLeftColor: BENCHMARK_CURVE_COLOR }} />
            <span>显示 B&amp;H</span>
          </label>
        </div>
        {compareItems.length && poolVisibleKeys.length > 0 ? <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={filteredCompareCurves} visibleKeys={poolVisibleKeys} labels={compareLabels} orderedKeys={[...poolCurveControlItems.map((item) => item.key), ...(showBenchmark ? ["buy_hold"] : [])]} showLegend={false} height={420} /></div> : compareItems.length ? <div className="empty-state">当前没有展示的曲线，可在上方重新勾选。</div> : <div className="empty-state">请至少选择一个策略。</div>}
        {(comparison?.diagnostics || []).length > 0 && <div className="diagnostic-list">{comparison.diagnostics.map((item: any, index: number) => <Tag color="orange" key={`${item.message}-${index}`}>{item.message}</Tag>)}</div>}
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>绩效明细</h3><p>这里展示当前参与对比策略的核心指标。</p></div></div>
        <div className="library-table-wrap">
          <Table rowKey="pool_item_id" columns={comparisonColumns} dataSource={compareItems} pagination={{ pageSize: 8 }} loading={loading} tableLayout="fixed" scroll={{ x: 1042 }} className="workbench-table strategy-pool-detail-table" rowClassName={(record) => (record.pool_item_id === selectedDetailId ? "is-selected" : "")} />
        </div>
      </section>

      {detail && (
        <section className="band library-shell">
          <div className="library-section-head"><div><h3>{strategyLabel(detail.pool_item)}</h3><p className="pool-detail-identity"><span>入池时间：{formatDate(detail.pool_item?.created_at).slice(0, 16)}</span><span>快照编号：{detail.pool_item?.pool_item_id || "-"}</span></p></div><div className="detail-head-actions"><span className="status-pill status-completed">快照已就绪</span><Button size="small" loading={continuingPoolItemId === String(detail.pool_item?.pool_item_id)} onClick={continueOptimizationFromPool}>继续参数优化</Button><Button size="small" danger disabled={Boolean(continuingPoolItemId)} onClick={() => handleDeletePoolItem(String(detail.pool_item?.pool_item_id))}>从池中移除</Button></div></div>
          <div className="library-metric-grid">
            <div className="library-metric-card"><span>{zh.sharpe}</span><strong>{formatNumber(detail.pool_item?.sharpe ?? metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card positive"><span>策略累计收益</span><strong>{detailCurveSummary.strategy ? formatReturnPct(detailCurveSummary.strategy.totalReturn, 2) : "-"}</strong></div>
            <div className="library-metric-card negative"><span>{zh.drawdown}</span><strong>{detailCurveSummary.strategy ? formatReturnPct(detailCurveSummary.strategy.maxDrawdown, 2) : "-"}</strong></div>
            <div className="library-metric-card"><span>卡玛比率</span><strong>{formatNumber(detail.pool_item?.calmar ?? metrics.calmar)}</strong></div>
          </div>
          <div className="detail-grid">
            <div className="viewer-summary-card"><span className="summary-label">参数</span><pre className="mini-code">{JSON.stringify(params, null, 2)}</pre></div>
            <div className="viewer-summary-card pool-note-card">
              <div className="pool-note-card-head">
                <span className="summary-label">{zh.notes}</span>
                {editingNotes ? (
                  <div className="pool-note-card-actions">
                    <Button type="link" size="small" loading={savingNotes} disabled={savingNotes} onClick={saveNotes}>保存</Button>
                    <Button type="link" size="small" disabled={savingNotes} onClick={cancelEditingNotes}>取消</Button>
                  </div>
                ) : (
                  <Button type="link" size="small" onClick={beginEditingNotes}>编辑</Button>
                )}
              </div>
              {editingNotes ? (
                <Input.TextArea
                  value={noteDraft}
                  onChange={(event) => setNoteDraft(event.target.value)}
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  maxLength={500}
                  placeholder="可选，记录策略特点、适用场景或注意事项。"
                />
              ) : (
                <p className="notes-text pool-note-text">{detail.notes || "-"}</p>
              )}
            </div>
          </div>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.trades}</h3></div></div><Table rowKey={(row) => `${row?.datetime || row?.date || row?.trading_day || "trade"}-${row?.tradeid || ""}-${row?.orderid || ""}`} dataSource={sortedTrades} pagination={{ pageSize: 6, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }} scroll={{ x: 900 }} className="workbench-table" columns={tradeColumns} /></section>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.code}</h3></div></div><pre className="code-block">{detail.strategy_code || ""}</pre></section>
        </section>
      )}
    </section>
  );
}
