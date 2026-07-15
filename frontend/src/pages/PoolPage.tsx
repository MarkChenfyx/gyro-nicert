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

export default function PoolPage({
  poolItems,
  refreshPool,
  refreshTasks
}: {
  poolItems: any[];
  refreshPool: () => Promise<void>;
  refreshTasks: () => Promise<void>;
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [searchText, setSearchText] = useState("");
  const [selectionMode, setSelectionMode] = useState("all");
  const [poolSortKey, setPoolSortKey] = useState<"created_at" | "total_return" | "sharpe" | "trade_count" | "max_drawdown">("created_at");
  const [poolSortOrder, setPoolSortOrder] = useState<"asc" | "desc">("desc");
  const [selectedDetailId, setSelectedDetailId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [comparison, setComparison] = useState<any>({ items: [], benchmark: { curve: [] }, diagnostics: [] });
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [rerunProgress, setRerunProgress] = useState(0);
  const [rerunMessage, setRerunMessage] = useState("");
  const [poolRerunStartMode, setPoolRerunStartMode] = useState("auto_earliest");
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [curveStartDate, setCurveStartDate] = useState("");
  const [curveEndDate, setCurveEndDate] = useState("");
  const [poolSelectionInitialized, setPoolSelectionInitialized] = useState(false);
  const presetRequestRef = useRef(0);

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

  function togglePoolSort(nextKey: "total_return" | "sharpe" | "trade_count" | "max_drawdown") {
    if (poolSortKey === nextKey) {
      setPoolSortOrder((current) => current === "desc" ? "asc" : "desc");
      return;
    }
    setPoolSortKey(nextKey);
    setPoolSortOrder("desc");
  }

  function sortArrow(key: "total_return" | "sharpe" | "trade_count" | "max_drawdown") {
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

  function presetItems(mode = selectionMode, records = candidateItems) {
    if (mode === "top_sharpe") {
      return records.slice().sort((a, b) => Number(b.sharpe ?? -Infinity) - Number(a.sharpe ?? -Infinity)).slice(0, 5);
    }
    if (mode === "top_excess") {
      return records
        .slice()
        .sort((a, b) => Number(strategyCurveMetrics(b).excessReturn ?? -Infinity) - Number(strategyCurveMetrics(a).excessReturn ?? -Infinity))
        .slice(0, 5);
    }
    if (mode === "recent") {
      return records.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 5);
    }
    return records;
  }

  async function applyPreset(mode: string) {
    const requestId = ++presetRequestRef.current;
    setSelectionMode(mode);
    if (mode !== "top_excess") {
      setSelectedIds(presetItems(mode).map((item) => String(item.pool_item_id)));
      return;
    }
    const candidateIds = candidateItems.map((item) => String(item.pool_item_id)).filter(Boolean);
    if (!candidateIds.length) {
      setSelectedIds([]);
      return;
    }
    setLoading(true);
    try {
      const payload = await comparePool(candidateIds);
      if (requestId !== presetRequestRef.current) return;
      setSelectedIds(
        presetItems("top_excess", payload.items || []).map((item) => String(item.pool_item_id))
      );
    } catch (error) {
      if (requestId === presetRequestRef.current) message.error(String(error));
    } finally {
      if (requestId === presetRequestRef.current) setLoading(false);
    }
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
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoading(false);
    }
  }

  async function rerunSelectedToToday() {
    if (!selectedIds.length) {
      message.warning("请至少选择一个策略。");
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
      const payload = await rerunPool(selectedIds, today, poolRerunStartMode);
      setComparison(payload);
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
      setSelectedSymbol("");
      setSelectedIds([]);
      return;
    }
    const nextSymbol = selectedSymbol && symbols.includes(selectedSymbol) ? selectedSymbol : symbols[0] || "";
    if (nextSymbol !== selectedSymbol) setSelectedSymbol(nextSymbol);
  }, [poolItems, selectedSymbol, symbols]);

  useEffect(() => {
    const candidateIds = candidateItems.map((item) => String(item.pool_item_id));
    const kept = selectedIds.filter((id) => candidateIds.includes(id));
    if (kept.length !== selectedIds.length) {
      setSelectedIds(kept);
      return;
    }
    if (!poolSelectionInitialized && !kept.length && candidateItems.length) {
      setSelectedIds(presetItems(selectionMode, candidateItems).map((item) => String(item.pool_item_id)));
      setPoolSelectionInitialized(true);
    }
  }, [candidateItems, poolSelectionInitialized, selectedIds, selectionMode]);

  useEffect(() => {
    if (!selectedIds.length) {
      setComparison({ items: [], benchmark: { curve: [] }, diagnostics: [] });
      return;
    }
    setLoading(true);
    comparePool(selectedIds)
      .then((payload) => setComparison(payload))
      .catch((error) => message.error(String(error)))
      .finally(() => setLoading(false));
  }, [selectedIds]);

  const compareItems = useMemo(() => {
    const items = [...(comparison?.items || [])];
    const direction = poolSortOrder === "desc" ? -1 : 1;
    if (poolSortKey === "created_at") {
      items.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")) * direction);
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
            : Number(aMetrics.tradeCount ?? -Infinity);
      const bValue = poolSortKey === "total_return"
        ? Number(bMetrics.totalReturn ?? -Infinity)
        : poolSortKey === "sharpe"
          ? Number(bMetrics.sharpe ?? -Infinity)
          : poolSortKey === "max_drawdown"
            ? Number(bMetrics.maxDrawdown ?? -Infinity)
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
  const selectedCurveSetKey = useMemo(() => [...selectedIds].sort().join("|"), [selectedIds]);

  useEffect(() => {
    if (!poolCurveDateBounds.min || !poolCurveDateBounds.max) return;
    setCurveStartDate(poolCurveDateBounds.min);
    setCurveEndDate(poolCurveDateBounds.max);
  }, [poolCurveDateBounds.max, poolCurveDateBounds.min, selectedCurveSetKey]);

  const filteredCompareCurves = useMemo(
    () => Object.fromEntries(Object.entries(compareCurves).map(([key, rows]) => [key, clampDateRange(rows as any[], curveStartDate, curveEndDate)])),
    [compareCurves, curveEndDate, curveStartDate]
  );
  const compareLabels = useMemo(() => Object.fromEntries(compareItems.map((item: any) => [item.pool_item_id, compareItemLabel(item)])), [compareItems]);
  const poolVisibleKeys = useMemo(() => [...selectedIds, ...(showBenchmark ? ["buy_hold"] : [])], [selectedIds, showBenchmark]);
  const poolCurveControlItems = useMemo<CurveControlItem[]>(() =>
    candidateItems.map((item) => ({
      key: String(item.pool_item_id),
      label: poolItemLabel(item),
      type: "strategy" as const,
      value: curveSummary(item?.curve || []).strategy?.totalReturn,
      detail: `${item.vt_symbol || "-"} · ${formatReturnPct(curveSummary(item?.curve || []).strategy?.totalReturn, 2)}`
    })),
  [candidateItems]);

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
        render: (value, record) => (
          <div className="strategy-pool-name-cell">
            <strong>{strategyLabel(record)}</strong>
            <span>{record.source_run_id || record.pool_item_id}</span>
          </div>
        )
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("total_return")}>
            累计收益 <SortCaret state={sortArrow("total_return")} />
          </button>
        ),
        render: (_, record) => formatReturnPct(strategyCurveMetrics(record).totalReturn)
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("trade_count")}>
            交易数 <SortCaret state={sortArrow("trade_count")} />
          </button>
        ),
        render: (_, record) => formatNumber(strategyCurveMetrics(record).tradeCount, 0)
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("sharpe")}>
            {zh.sharpe} <SortCaret state={sortArrow("sharpe")} />
          </button>
        ),
        render: (_, record) => formatNumber(metricValue(record.metrics, "sharpe", "sharpe_ratio"))
      },
      {
        title: (
          <button type="button" className="table-sort-button" onClick={() => togglePoolSort("max_drawdown")}>
            最大回撤 <SortCaret state={sortArrow("max_drawdown")} />
          </button>
        ),
        render: (_, record) => formatReturnPct(strategyCurveMetrics(record).maxDrawdown)
      },
      { title: "超额收益", render: (_, record) => formatReturnPct(strategyCurveMetrics(record).excessReturn) },
      {
        title: "操作",
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
  const tradeColumns = (detail?.trades?.columns || Object.keys(trades[0] || {})).slice(0, 8).map((column: string) => ({ title: column, dataIndex: column }));

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
            <Select value={selectedSymbol || undefined} onChange={(value) => { presetRequestRef.current += 1; setSelectedSymbol(value); setSelectedIds([]); }} options={symbols.map((item) => ({ value: item, label: item }))} />
          </label>
          <label className="field library-folder-field">
            <span>策略搜索</span>
            <Input value={searchText} onChange={(event) => { presetRequestRef.current += 1; setSearchText(event.target.value); setSelectedIds([]); }} placeholder="策略 / run / 变体 / 标签" />
          </label>
          <div className="field library-folder-field strategy-pool-preset-field">
            <span>快捷选择</span>
            <div className="strategy-pool-preset-buttons">
              {([
                ["all", "全部"],
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
            <span>重跑起点</span>
            <Select
              value={poolRerunStartMode}
              onChange={setPoolRerunStartMode}
              options={[
                { value: "auto_earliest", label: "自动最早" },
                { value: "saved", label: "沿用入池日期" }
              ]}
            />
          </label>
          <Button type="primary" disabled={!selectedIds.length} loading={rerunning} onClick={rerunSelectedToToday}>重跑到今天</Button>
          <span>
            {comparison?.rerun_end
              ? `当前对比结果已重跑到 ${formatDate(comparison.rerun_end)}。${poolRerunStartMode === "auto_earliest" ? "起点使用本地行情最早日期。" : "起点沿用入池时保存的开始日期。"}`
              : "当前展示的是已保存的策略池快照曲线。"}
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
        <div className="library-section-head"><div><h3>累计收益对比</h3><p>已选择 {selectedIds.length} 个策略，展示其按昨收归一并逐日累加后的收益曲线。</p></div><span className={statusClass(compareItems.length ? "completed" : "pending")}>{compareItems.length ? "ready" : "empty"}</span></div>
        <CurveControls
          items={poolCurveControlItems}
          visibleKeys={selectedIds}
          startDate={curveStartDate}
          endDate={curveEndDate}
          bounds={poolCurveDateBounds}
          onToggle={togglePoolItem}
          onSelectAll={() => { setSelectedIds(candidateItems.map((item) => String(item.pool_item_id))); setShowBenchmark(true); }}
          onClear={() => { setSelectedIds([]); setShowBenchmark(false); }}
          onStartDateChange={setCurveStartDate}
          onEndDateChange={setCurveEndDate}
          onShortcut={applyPoolCurveShortcut}
        />
        <div className="pool-benchmark-toggle-row">
          <label className="pool-benchmark-toggle">
            <input type="checkbox" checked={showBenchmark} onChange={(event) => setShowBenchmark(event.target.checked)} disabled={!selectedIds.length} />
            <span className="curve-swatch is-dashed" style={{ borderLeftColor: BENCHMARK_CURVE_COLOR }} />
            <span>显示 Buy & Hold</span>
          </label>
        </div>
        {compareItems.length && poolVisibleKeys.length > 0 ? <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={filteredCompareCurves} visibleKeys={poolVisibleKeys} labels={compareLabels} orderedKeys={[...poolCurveControlItems.map((item) => item.key), ...(showBenchmark ? ["buy_hold"] : [])]} showLegend={false} height={420} /></div> : compareItems.length ? <div className="empty-state">当前没有展示的曲线，可在上方重新勾选。</div> : <div className="empty-state">请至少选择一个策略。</div>}
        {(comparison?.diagnostics || []).length > 0 && <div className="diagnostic-list">{comparison.diagnostics.map((item: any, index: number) => <Tag color="orange" key={`${item.message}-${index}`}>{item.message}</Tag>)}</div>}
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>表现明细</h3><p>这里展示当前参与对比策略的核心指标。</p></div></div>
        <div className="library-table-wrap">
          <Table rowKey="pool_item_id" columns={comparisonColumns} dataSource={compareItems} pagination={{ pageSize: 8 }} loading={loading} scroll={{ x: 960 }} className="workbench-table strategy-pool-detail-table" rowClassName={(record) => (record.pool_item_id === selectedDetailId ? "is-selected" : "")} />
        </div>
      </section>

      {detail && (
        <section className="band library-shell">
          <div className="library-section-head"><div><h3>{strategyLabel(detail.pool_item)}</h3><p>{detail.pool_item?.pool_item_id}</p></div><div className="detail-head-actions"><span className="status-pill status-completed">completed</span><Button size="small" danger onClick={() => handleDeletePoolItem(String(detail.pool_item?.pool_item_id))}>从池中移除</Button></div></div>
          <div className="library-metric-grid">
            <div className="library-metric-card"><span>{zh.sharpe}</span><strong>{formatNumber(detail.pool_item?.sharpe ?? metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card positive"><span>策略累计收益</span><strong>{detailCurveSummary.strategy ? formatReturnPct(detailCurveSummary.strategy.totalReturn, 2) : "-"}</strong></div>
            <div className="library-metric-card negative"><span>{zh.drawdown}</span><strong>{detailCurveSummary.strategy ? formatReturnPct(detailCurveSummary.strategy.maxDrawdown, 2) : "-"}</strong></div>
            <div className="library-metric-card"><span>卡玛比率</span><strong>{formatNumber(detail.pool_item?.calmar ?? metrics.calmar)}</strong></div>
          </div>
          <div className="detail-grid">
            <div className="viewer-summary-card"><span className="summary-label">参数</span><pre className="mini-code">{JSON.stringify(params, null, 2)}</pre></div>
            <div className="viewer-summary-card"><span className="summary-label">{zh.notes}</span><p className="notes-text">{detail.notes || "-"}</p></div>
          </div>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.trades}</h3></div></div><Table rowKey={(_, index) => String(index)} dataSource={trades} pagination={{ pageSize: 6 }} className="workbench-table" columns={tradeColumns} /></section>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.code}</h3></div></div><pre className="code-block">{detail.strategy_code || ""}</pre></section>
        </section>
      )}
    </section>
  );
}
