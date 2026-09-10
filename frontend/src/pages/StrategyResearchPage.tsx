import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, InputNumber, Modal, Select, Space, Spin, Table, message } from "antd";
import { createPoolResearchAiOverview, getPoolResearchContext, runPoolResearchHeatmap, runPoolResearchWalkForward, runPoolWalkForwardRankAnalysis } from "../api";
import ResearchHeatmap from "../components/ResearchHeatmap";
import { CurveChart, MultiVariantCurveChart, UI_TEXT, curveSummary, formatDate, strategyLabel } from "../app/ui";

const RESEARCH_POOL_STORAGE_KEY = "gyro_nicert.research_pool_item_id";
const RESEARCH_TAB_STORAGE_KEY = "gyro_nicert.research_tab";

type ResearchTab = "overview" | "heatmap" | "walk_forward";
type RangeSpec = { low: number; high: number; step: number };

function initialResearchTab(): ResearchTab {
  const saved = window.localStorage.getItem(RESEARCH_TAB_STORAGE_KEY);
  return saved === "heatmap" || saved === "walk_forward" ? saved : "overview";
}

function formatPercent(value: unknown, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}%` : "-";
}

function formatNumber(value: unknown, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "-";
}

function formatRatio(value: unknown, digits = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(digits)}%` : "-";
}

function hasFiniteValue(value: unknown) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function gridValueCount(spec?: RangeSpec) {
  if (!spec) return 0;
  const low = Number(spec.low);
  const high = Number(spec.high);
  const step = Number(spec.step);
  if (![low, high, step].every(Number.isFinite) || step <= 0 || high < low) return 0;
  return Math.max(1, Math.floor((high - low) / step + 1.0000001));
}

function parameterAxisValues(rows: any[], parameterName: string): Array<string | number> {
  const unique = new Map<string, string | number>();
  for (const row of rows) {
    const value = row?.parameters?.[parameterName];
    if (value === undefined || value === null) continue;
    const number = Number(value);
    const normalized = Number.isFinite(number) ? number : String(value);
    unique.set(`${typeof normalized}:${String(normalized)}`, normalized);
  }
  const values = Array.from(unique.values());
  const numeric = values.every((value) => typeof value === "number");
  return values.sort((left, right) => numeric
    ? Number(left) - Number(right)
    : String(left).localeCompare(String(right)));
}

function compactSearchText(value: unknown) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[\s_|·./\\:：()（）\[\]【】-]+/g, "");
}

function fuzzySearchMatch(input: string, source: unknown) {
  const needle = compactSearchText(input);
  const haystack = compactSearchText(source);
  if (!needle) return true;
  if (haystack.includes(needle)) return true;
  if (needle.length < 3) return false;
  let matched = 0;
  for (const character of haystack) {
    if (character === needle[matched]) matched += 1;
    if (matched === needle.length) return true;
  }
  return false;
}

function fuzzySearchScore(input: string, source: unknown) {
  const needle = compactSearchText(input);
  const haystack = compactSearchText(source);
  if (!needle) return 0;
  if (haystack.startsWith(needle)) return 0;
  const index = haystack.indexOf(needle);
  if (index >= 0) return 10 + index;
  return fuzzySearchMatch(input, source) ? 100 : 1000;
}

export default function StrategyResearchPage({
  poolItems,
  navigation,
  onNavigationApplied,
  refreshTasks
}: {
  poolItems: any[];
  navigation: { poolItemId: string; requestId: number } | null;
  onNavigationApplied: (requestId: number) => void;
  refreshTasks: () => Promise<void>;
}) {
  const [selectedPoolItemId, setSelectedPoolItemId] = useState(() => window.localStorage.getItem(RESEARCH_POOL_STORAGE_KEY) || "");
  const [activeTab, setActiveTab] = useState<ResearchTab>(initialResearchTab);
  const [context, setContext] = useState<any>(null);
  const [heatmap, setHeatmap] = useState<any>(null);
  const [walkForward, setWalkForward] = useState<any>(null);
  const [aiOverview, setAiOverview] = useState<any>(null);
  const [loadingAiOverview, setLoadingAiOverview] = useState(false);
  const [aiOverviewError, setAiOverviewError] = useState("");
  const [loadingContext, setLoadingContext] = useState(false);
  const [running, setRunning] = useState(false);
  const [runningWalkForward, setRunningWalkForward] = useState(false);
  const [runningRankAnalysis, setRunningRankAnalysis] = useState(false);
  const [xParameter, setXParameter] = useState("");
  const [yParameter, setYParameter] = useState("");
  const [ranges, setRanges] = useState<Record<string, RangeSpec>>({});
  const [metric, setMetric] = useState<"excess_return" | "sharpe">("excess_return");
  const [trainingStartDate, setTrainingStartDate] = useState("");
  const [trainingMonths, setTrainingMonths] = useState(24);
  const [walkObjective, setWalkObjective] = useState<"sharpe">("sharpe");
  const [walkParameters, setWalkParameters] = useState<string[]>([]);
  const [walkRanges, setWalkRanges] = useState<Record<string, RangeSpec>>({});
  const [rankDetailWindowIndex, setRankDetailWindowIndex] = useState(1);
  const [heatmapWindowIndex, setHeatmapWindowIndex] = useState<number | null>(null);
  const contextRequestRef = useRef(0);

  const sortedPoolItems = useMemo(
    () => poolItems.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))),
    [poolItems]
  );
  const selectedPoolItem = useMemo(
    () => poolItems.find((item) => String(item.pool_item_id) === selectedPoolItemId),
    [poolItems, selectedPoolItemId]
  );
  const selectedSymbol = selectedPoolItem ? String(selectedPoolItem.vt_symbol || "未标记标的") : undefined;
  const symbolOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of sortedPoolItems) {
      const symbol = String(item.vt_symbol || "未标记标的");
      counts.set(symbol, (counts.get(symbol) || 0) + 1);
    }
    return Array.from(counts.entries())
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([symbol, count]) => ({ value: symbol, label: `${symbol}（${count}）` }));
  }, [sortedPoolItems]);
  const strategyOptions = useMemo(() => sortedPoolItems
    .filter((item) => String(item.vt_symbol || "未标记标的") === selectedSymbol)
    .map((item) => ({
      value: String(item.pool_item_id),
      label: `${strategyLabel(item)} · ${formatDate(item.created_at)}`,
      searchText: [
        strategyLabel(item),
        item.strategy_name,
        item.strategy_family,
        item.pool_item_id,
        item.pool_version,
        item.strategy_version,
        item.source_strategy_version,
        item.created_at,
        item.tags
      ].join(" ")
    })), [selectedSymbol, sortedPoolItems]);

  function selectSymbol(symbol: string) {
    const latest = sortedPoolItems.find((item) => String(item.vt_symbol || "未标记标的") === symbol);
    setSelectedPoolItemId(String(latest?.pool_item_id || ""));
  }

  useEffect(() => {
    if (navigation?.poolItemId && poolItems.some((item) => String(item.pool_item_id) === navigation.poolItemId)) {
      setSelectedPoolItemId(navigation.poolItemId);
      onNavigationApplied(navigation.requestId);
      return;
    }
    if (!poolItems.length) return;
    if (!selectedPoolItemId || !poolItems.some((item) => String(item.pool_item_id) === selectedPoolItemId)) {
      setSelectedPoolItemId(String(sortedPoolItems[0]?.pool_item_id || ""));
    }
  }, [navigation, onNavigationApplied, poolItems, selectedPoolItemId, sortedPoolItems]);

  useEffect(() => {
    if (!selectedPoolItemId) {
      setContext(null);
      setHeatmap(null);
      setWalkForward(null);
      setRankDetailWindowIndex(1);
      setHeatmapWindowIndex(null);
      return;
    }
    window.localStorage.setItem(RESEARCH_POOL_STORAGE_KEY, selectedPoolItemId);
    const requestId = ++contextRequestRef.current;
    setLoadingContext(true);
    setHeatmapWindowIndex(null);
    getPoolResearchContext(selectedPoolItemId)
      .then((payload) => {
        if (requestId !== contextRequestRef.current) return;
        const parameters = (payload.parameters || []) as any[];
        const parameterNames = new Set(parameters.map((item) => String(item.name)));
        const latest = payload.latest_heatmap || null;
        const latestWalkForward = payload.latest_walk_forward || null;
        const nextX = parameterNames.has(String(latest?.x_parameter)) ? String(latest.x_parameter) : String(parameters[0]?.name || "");
        const nextY = parameterNames.has(String(latest?.y_parameter)) && String(latest?.y_parameter) !== nextX
          ? String(latest.y_parameter)
          : String(parameters.find((item) => String(item.name) !== nextX)?.name || "");
        const defaultRanges = Object.fromEntries(parameters.map((item) => [String(item.name), {
          low: Number(item.low),
          high: Number(item.high),
          step: Number(item.step)
        }]));
        setContext(payload);
        setHeatmap(latest);
        setWalkForward(latestWalkForward);
        setRankDetailWindowIndex(Number(latestWalkForward?.windows?.[0]?.index || 1));
        setXParameter(nextX);
        setYParameter(nextY);
        setRanges({ ...defaultRanges, ...(latest?.parameter_ranges || {}) });
        setMetric(latest?.objective === "sharpe" ? "sharpe" : "excess_return");
        const savedWalkParameters = (latestWalkForward?.selected_parameters || [])
          .map((name: unknown) => String(name))
          .filter((name: string) => parameterNames.has(name))
          .slice(0, 3);
        setWalkParameters(savedWalkParameters.length ? savedWalkParameters : parameters.slice(0, 2).map((item) => String(item.name)));
        setWalkRanges({ ...defaultRanges, ...(latestWalkForward?.parameter_ranges || {}) });
        setTrainingStartDate(String(latestWalkForward?.training_start_date || payload.config?.start_date || "").slice(0, 10));
        setTrainingMonths(Number(latestWalkForward?.training_months || 24));
        setWalkObjective("sharpe");
      })
      .catch((error) => {
        if (requestId === contextRequestRef.current) {
          setContext(null);
          setHeatmap(null);
          setWalkForward(null);
          setRankDetailWindowIndex(1);
          setHeatmapWindowIndex(null);
          message.error(String(error));
        }
      })
      .finally(() => {
        if (requestId === contextRequestRef.current) setLoadingContext(false);
      });
  }, [selectedPoolItemId]);

  useEffect(() => {
    let active = true;
    setAiOverview(null);
    setAiOverviewError("");
    if (!selectedPoolItemId || context?.pool_item?.pool_item_id !== selectedPoolItemId) {
      setLoadingAiOverview(false);
      return () => {
        active = false;
      };
    }
    setLoadingAiOverview(true);
    createPoolResearchAiOverview(selectedPoolItemId)
      .then((payload) => {
        if (active) setAiOverview(payload);
      })
      .catch((error) => {
        if (active) setAiOverviewError(String(error));
      })
      .finally(() => {
        if (active) setLoadingAiOverview(false);
      });
    return () => {
      active = false;
    };
  }, [context?.pool_item?.pool_item_id, selectedPoolItemId]);

  async function refreshAiOverview() {
    if (!selectedPoolItemId || loadingAiOverview) return;
    setLoadingAiOverview(true);
    setAiOverviewError("");
    try {
      setAiOverview(await createPoolResearchAiOverview(selectedPoolItemId, true));
    } catch (error) {
      setAiOverviewError(String(error));
    } finally {
      setLoadingAiOverview(false);
    }
  }

  function switchTab(tab: ResearchTab) {
    setActiveTab(tab);
    window.localStorage.setItem(RESEARCH_TAB_STORAGE_KEY, tab);
  }

  function updateRange(name: string, key: keyof RangeSpec, value: number | null) {
    if (value === null) return;
    setRanges((current) => ({ ...current, [name]: { ...(current[name] || { low: 0, high: 0, step: 1 }), [key]: Number(value) } }));
  }

  function updateWalkRange(name: string, key: keyof RangeSpec, value: number | null) {
    if (value === null) return;
    setWalkRanges((current) => ({ ...current, [name]: { ...(current[name] || { low: 0, high: 0, step: 1 }), [key]: Number(value) } }));
  }

  const parameterOptions = useMemo(
    () => (context?.parameters || []).map((item: any) => ({ value: String(item.name), label: String(item.name) })),
    [context]
  );
  const xParameterMeta = (context?.parameters || []).find((item: any) => String(item.name) === xParameter);
  const yParameterMeta = (context?.parameters || []).find((item: any) => String(item.name) === yParameter);
  const totalGridCount = gridValueCount(ranges[xParameter]) * gridValueCount(ranges[yParameter]);
  const walkGridCount = walkParameters.length
    ? walkParameters.reduce((total, name) => total * gridValueCount(walkRanges[name]), 1)
    : 0;

  async function runHeatmap() {
    if (!selectedPoolItemId || !xParameter || !yParameter) {
      message.warning("请选择两个不同的研究参数");
      return;
    }
    if (totalGridCount < 4 || totalGridCount > 100) {
      message.warning("参数网格需要控制在 4～100 组");
      return;
    }
    setRunning(true);
    try {
      await refreshTasks().catch(() => undefined);
      const payload = await runPoolResearchHeatmap(selectedPoolItemId, {
        x_parameter: xParameter,
        y_parameter: yParameter,
        parameter_ranges: {
          [xParameter]: ranges[xParameter],
          [yParameter]: ranges[yParameter]
        },
        objective: metric,
        max_trials: 100
      });
      setHeatmap(payload);
      message.success("参数稳定性分析已完成");
      await refreshTasks().catch(() => undefined);
    } catch (error) {
      message.error(String(error));
      await refreshTasks().catch(() => undefined);
    } finally {
      setRunning(false);
    }
  }

  async function runWalkForward() {
    if (!selectedPoolItemId || !walkParameters.length) {
      message.warning("请至少选择一个优化参数");
      return;
    }
    if (walkGridCount < 2 || walkGridCount > 100) {
      message.warning("每个训练窗口的参数组合需要控制在 2～100 组");
      return;
    }
    const configuredStartDate = String(context?.config?.start_date || "").slice(0, 10);
    const configuredEndDate = String(context?.config?.end_date || "").slice(0, 10);
    if (!trainingStartDate) {
      message.warning("请选择训练开始日期");
      return;
    }
    if ((configuredStartDate && trainingStartDate < configuredStartDate) || (configuredEndDate && trainingStartDate > configuredEndDate)) {
      message.warning(`训练开始日期需要位于 ${configuredStartDate} 至 ${configuredEndDate} 之间`);
      return;
    }
    setRunningWalkForward(true);
    try {
      await refreshTasks().catch(() => undefined);
      const payload = await runPoolResearchWalkForward(selectedPoolItemId, {
        training_start_date: trainingStartDate,
        training_months: trainingMonths,
        test_months: 6,
        selected_parameters: walkParameters,
        parameter_ranges: Object.fromEntries(walkParameters.map((name) => [name, walkRanges[name]])),
        objective: walkObjective,
        max_trials: 100
      });
      setWalkForward(payload);
      setRankDetailWindowIndex(Number(payload?.windows?.[0]?.index || 1));
      setHeatmapWindowIndex(null);
      message.success("滚动优化已完成");
      await refreshTasks().catch(() => undefined);
    } catch (error) {
      message.error(String(error));
      await refreshTasks().catch(() => undefined);
    } finally {
      setRunningWalkForward(false);
    }
  }

  async function runRankAnalysis() {
    const experimentId = String(walkForward?.experiment_id || "");
    if (!selectedPoolItemId || !experimentId) {
      message.warning("请先完成一次滚动优化");
      return;
    }
    setRunningRankAnalysis(true);
    try {
      await refreshTasks().catch(() => undefined);
      const payload = await runPoolWalkForwardRankAnalysis(selectedPoolItemId, experimentId);
      setWalkForward(payload);
      setRankDetailWindowIndex(Number(payload?.windows?.[0]?.index || 1));
      message.success(payload?.cached ? "已读取完整参数横截面分析" : "完整参数横截面分析已完成");
      await refreshTasks().catch(() => undefined);
    } catch (error) {
      message.error(String(error));
      await refreshTasks().catch(() => undefined);
    } finally {
      setRunningRankAnalysis(false);
    }
  }

  function openWindowHeatmaps(window: any) {
    if ((walkForward?.selected_parameters || []).length !== 2) {
      message.info("训练期与样本外期双热力图仅支持恰好两个优化参数");
      return;
    }
    if (!(window?.rank_analysis?.rows || []).length) {
      message.info("请先计算完整参数横截面");
      return;
    }
    setHeatmapWindowIndex(Number(window.index));
  }

  const curveRows = context?.curve || [];
  const summary = useMemo(() => curveSummary(curveRows), [curveRows]);
  const metrics = context?.metrics || {};
  const strategyReturn = summary.strategy?.totalReturn ?? metrics.total_return;
  const benchmarkReturn = summary.buyHold?.totalReturn;
  const excessReturn = strategyReturn !== undefined && benchmarkReturn !== undefined ? Number(strategyReturn) - Number(benchmarkReturn) : null;
  const maxDrawdown = summary.strategy?.maxDrawdown ?? metrics.max_drawdown_pct ?? metrics.max_ddpercent;
  const heatmapRows = heatmap?.grid_summary || [];
  const positiveRows = heatmapRows.filter((row: any) => row?.success && Number.isFinite(Number(row?.[metric])));
  const positiveRatio = positiveRows.length ? positiveRows.filter((row: any) => Number(row[metric]) > 0).length / positiveRows.length : null;
  const walkCurveRows = walkForward?.curve || [];
  const walkSummary = useMemo(() => curveSummary(walkCurveRows), [walkCurveRows]);
  const fixedCurveRows = walkForward?.fixed_curve || [];
  const fixedSummary = useMemo(() => curveSummary(fixedCurveRows), [fixedCurveRows]);
  const fixedComparisonAvailable = fixedCurveRows.length > 0;
  const walkTradeCount = (walkForward?.windows || []).reduce((total: number, window: any) => {
    const value = Number(window?.test_metrics?.total_trade_count);
    return total + (Number.isFinite(value) ? value : 0);
  }, 0);
  const fixedTradeCount = (walkForward?.windows || []).reduce((total: number, window: any) => {
    const value = Number(window?.fixed_test_metrics?.total_trade_count);
    return total + (Number.isFinite(value) ? value : 0);
  }, 0);
  const walkReturnUplift = walkSummary.strategy && fixedSummary.strategy
    ? walkSummary.strategy.totalReturn - fixedSummary.strategy.totalReturn
    : null;
  const predictability = walkForward?.parameter_predictability || {};
  const rankAnalysisWindows = (walkForward?.windows || [])
    .filter((window: any) => (window?.rank_analysis?.rows || []).length > 0)
    .slice()
    .sort((left: any, right: any) => Number(left.index) - Number(right.index));
  const rankAnalysisComplete = (walkForward?.windows || []).length > 0
    && (walkForward?.windows || []).every((window: any) => (window?.rank_analysis?.rows || []).length > 0);
  const rankDetailWindow = rankAnalysisWindows.find((window: any) => Number(window.index) === rankDetailWindowIndex)
    || rankAnalysisWindows[0]
    || null;
  const walkHeatmapParameters = (walkForward?.selected_parameters || []).map((name: unknown) => String(name));
  const selectedHeatmapWindow = (walkForward?.windows || []).find((window: any) => Number(window.index) === heatmapWindowIndex) || null;
  const selectedHeatmapRows = selectedHeatmapWindow?.rank_analysis?.rows || [];
  const selectedHeatmapRankIc = selectedHeatmapWindow?.rank_analysis?.rank_ic;
  const selectedHeatmapHasRankIc = hasFiniteValue(selectedHeatmapRankIc);
  const heatmapWindowPosition = rankAnalysisWindows.findIndex((window: any) => Number(window.index) === heatmapWindowIndex);
  const previousHeatmapWindow = heatmapWindowPosition > 0 ? rankAnalysisWindows[heatmapWindowPosition - 1] : null;
  const nextHeatmapWindow = heatmapWindowPosition >= 0 && heatmapWindowPosition < rankAnalysisWindows.length - 1
    ? rankAnalysisWindows[heatmapWindowPosition + 1]
    : null;
  const dualHeatmapSupported = walkHeatmapParameters.length === 2;
  const heatmapXParameter = walkHeatmapParameters[0] || "";
  const heatmapYParameter = walkHeatmapParameters[1] || "";
  const walkHeatmapXValues = parameterAxisValues(selectedHeatmapRows, heatmapXParameter);
  const walkHeatmapYValues = parameterAxisValues(selectedHeatmapRows, heatmapYParameter);
  const trainingHeatmapRows = selectedHeatmapRows.map((row: any) => ({
    ...row,
    success: hasFiniteValue(row.training_score),
    sharpe: row.training_score,
    excess_return: row.training_excess_return
  }));
  const testHeatmapRows = selectedHeatmapRows.map((row: any) => ({
    ...row,
    success: hasFiniteValue(row.test_score),
    sharpe: row.test_score,
    excess_return: row.test_excess_return
  }));
  const sharedHeatmapScores = [
    ...trainingHeatmapRows.filter((row: any) => row.success).map((row: any) => Number(row.sharpe)),
    ...testHeatmapRows.filter((row: any) => row.success).map((row: any) => Number(row.sharpe))
  ];
  const sharedHeatmapRange = sharedHeatmapScores.length ? {
    min: Math.min(...sharedHeatmapScores),
    max: Math.max(...sharedHeatmapScores)
  } : undefined;
  const rankGroupRows = predictability.groups || [];
  const rankWindowColumns = [
    { title: "窗口", dataIndex: "index", width: 80, render: (value: unknown) => `第 ${value} 期` },
    {
      title: "样本外区间",
      key: "test_period",
      width: 220,
      render: (_value: unknown, row: any) => `${row.test_start} 至 ${row.test_end}`
    },
    { title: "有效组合", key: "combination_count", width: 100, render: (_value: unknown, row: any) => row.rank_analysis?.combination_count || 0 },
    { title: "Rank IC", key: "rank_ic", width: 105, render: (_value: unknown, row: any) => formatNumber(row.rank_analysis?.rank_ic, 3) },
    { title: "Top 20% Lift", key: "top_lift", width: 125, render: (_value: unknown, row: any) => formatNumber(row.rank_analysis?.top_20_lift, 3) },
    { title: "训练最优测试百分位", key: "best_percentile", width: 170, render: (_value: unknown, row: any) => formatPercent(row.rank_analysis?.training_best_test_percentile, 1) },
    { title: "分组单调性", key: "monotonicity", width: 120, render: (_value: unknown, row: any) => formatNumber(row.rank_analysis?.monotonicity, 3) }
  ];
  const rankDetailColumns = [
    { title: "训练排名", dataIndex: "training_rank", width: 100, render: (value: unknown) => formatNumber(value, 1) },
    {
      title: "参数组合",
      dataIndex: "parameters",
      width: 280,
      render: (parameters: Record<string, unknown>) => (
        <div className="rank-parameter-cell">
          {Object.entries(parameters || {}).map(([name, value]) => <em key={name}>{name}={String(value)}</em>)}
        </div>
      )
    },
    { title: "训练期夏普比率", dataIndex: "training_score", width: 140, render: (value: unknown) => formatNumber(value, 3) },
    { title: "样本外期夏普比率", dataIndex: "test_score", width: 150, render: (value: unknown) => formatNumber(value, 3) },
    { title: "样本外排名", dataIndex: "test_rank", width: 110, render: (value: unknown) => formatNumber(value, 1) }
  ];
  const walkPerformanceColumns = [
    { title: "对照方式", dataIndex: "label", width: 180 },
    { title: UI_TEXT.metric.totalReturn, dataIndex: "strategy_return", width: 130, render: (value: unknown) => formatPercent(value) },
    { title: UI_TEXT.metric.benchmarkReturn, dataIndex: "benchmark_return", width: 130, render: (value: unknown) => formatPercent(value) },
    { title: UI_TEXT.metric.excessReturn, dataIndex: "excess_return", width: 120, render: (value: unknown) => formatPercent(value) },
    { title: UI_TEXT.metric.sharpe, dataIndex: "sharpe", width: 110, render: (value: unknown) => formatNumber(value) },
    { title: UI_TEXT.metric.tradeCount, dataIndex: "trade_count", width: 110, render: (value: unknown) => Number.isFinite(Number(value)) ? String(value) : "-" },
    { title: UI_TEXT.metric.maxDrawdown, dataIndex: "max_drawdown", width: 120, render: (value: unknown) => formatPercent(value) }
  ];
  const walkPerformanceRows = walkForward ? [{
    key: "walk_forward",
    label: "滚动优化样本外",
    strategy_return: walkSummary.strategy?.totalReturn,
    benchmark_return: walkSummary.buyHold?.totalReturn,
    excess_return: walkSummary.excess,
    sharpe: walkForward.metrics?.sharpe,
    trade_count: walkTradeCount,
    max_drawdown: walkSummary.strategy?.maxDrawdown
  }, ...(fixedComparisonAvailable ? [{
    key: "fixed_parameters",
    label: "固定参数对照",
    strategy_return: fixedSummary.strategy?.totalReturn,
    benchmark_return: fixedSummary.buyHold?.totalReturn,
    excess_return: fixedSummary.excess,
    sharpe: walkForward.fixed_metrics?.sharpe,
    trade_count: fixedTradeCount,
    max_drawdown: fixedSummary.strategy?.maxDrawdown
  }] : [])] : [];
  function renderRangeRow(
    parameterName: string,
    parameterMeta: any,
    sourceRanges: Record<string, RangeSpec> = ranges,
    onUpdate: (name: string, key: keyof RangeSpec, value: number | null) => void = updateRange
  ) {
    const spec = sourceRanges[parameterName];
    if (!parameterName || !spec) return null;
    const integerOnly = String(parameterMeta?.type) === "int";
    return (
      <div className="research-range-row" key={parameterName}>
        <strong title={parameterName}>{parameterName}</strong>
        {(["low", "high", "step"] as Array<keyof RangeSpec>).map((key) => (
          <label key={key}>
            <span>{key === "low" ? "下限" : key === "high" ? "上限" : "步长"}</span>
            <InputNumber
              value={spec[key]}
              precision={integerOnly ? 0 : undefined}
              step={integerOnly ? 1 : undefined}
              onChange={(value) => onUpdate(parameterName, key, value === null ? null : Number(value))}
            />
          </label>
        ))}
      </div>
    );
  }

  return (
    <div className="view strategy-research-view">
      <section className="hero-band research-hero-band">
        <div>
          <p className="eyebrow">研究工作台</p>
          <h2>{UI_TEXT.page.research}</h2>
          <p className="hero-copy">从策略快照出发，检查收益表现和参数稳定性，不修改原策略与参数优化结果。</p>
        </div>
      </section>

      <section className="band research-selector-band">
        <label className="field research-symbol-select">
          <span>{UI_TEXT.term.tradingSymbol}</span>
          <Select
            showSearch
            value={selectedSymbol}
            onChange={selectSymbol}
            optionFilterProp="label"
            placeholder="选择交易标的"
            options={symbolOptions}
          />
        </label>
        <label className="field research-strategy-select">
          <span>{UI_TEXT.term.poolSnapshot}</span>
          <Select
            showSearch
            value={selectedPoolItemId || undefined}
            onChange={setSelectedPoolItemId}
            filterOption={(input, option) => fuzzySearchMatch(input, (option as any)?.searchText || option?.label)}
            filterSort={(left, right, info) => fuzzySearchScore(info.searchValue, (left as any)?.searchText || left?.label)
              - fuzzySearchScore(info.searchValue, (right as any)?.searchText || right?.label)}
            placeholder={selectedSymbol ? "搜索当前交易标的下的策略快照" : "请先选择交易标的"}
            disabled={!selectedSymbol}
            options={strategyOptions}
          />
        </label>
        {selectedPoolItem && (
          <div className="research-selected-strategy">
            <strong>{strategyLabel(selectedPoolItem)}</strong>
            <span>{selectedPoolItem.vt_symbol || "-"} · 入池时间 {formatDate(selectedPoolItem.created_at)}</span>
          </div>
        )}
      </section>

      <nav className="research-tabs" aria-label="研究功能">
        <button type="button" className={activeTab === "overview" ? "is-active" : ""} onClick={() => switchTab("overview")}>研究概览</button>
        <button type="button" className={activeTab === "heatmap" ? "is-active" : ""} onClick={() => switchTab("heatmap")}>{UI_TEXT.research.parameterStability}</button>
        <button type="button" className={activeTab === "walk_forward" ? "is-active" : ""} onClick={() => switchTab("walk_forward")}>{UI_TEXT.research.walkForward}</button>
      </nav>

      {loadingContext ? (
        <section className="band empty-state"><Spin size="small" /> 正在读取策略快照…</section>
      ) : !context ? (
        <section className="band empty-state">选择一个策略快照后开始研究。</section>
      ) : activeTab === "overview" ? (
        <>
          <section className="library-metric-grid research-metric-grid">
            <div className="library-metric-card"><span>{UI_TEXT.metric.totalReturn}</span><strong>{formatPercent(strategyReturn)}</strong></div>
            <div className={`library-metric-card ${Number(excessReturn) >= 0 ? "positive" : "negative"}`}><span>{UI_TEXT.metric.excessReturn}</span><strong>{formatPercent(excessReturn)}</strong></div>
            <div className="library-metric-card"><span>{UI_TEXT.metric.sharpe}</span><strong>{formatNumber(metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card negative"><span>{UI_TEXT.metric.maxDrawdown}</span><strong>{formatPercent(maxDrawdown)}</strong></div>
          </section>

          <section className="band research-ai-overview">
            <div className="research-ai-overview-copy">
              <span>AI 研究提示</span>
              {loadingAiOverview && !aiOverview
                ? <p>正在生成当前策略的研究提示…</p>
                : aiOverviewError && !aiOverview
                  ? <p className="is-error">AI 研究提示暂不可用：{aiOverviewError}</p>
                  : <p>{aiOverview?.summary || "等待生成研究提示。"}</p>}
            </div>
            <Button type="text" size="small" loading={loadingAiOverview} onClick={refreshAiOverview}>
              {aiOverview ? "重新生成" : "生成"}
            </Button>
          </section>

          <section className="band research-overview-grid">
            <div className="library-curve-panel">
              <CurveChart
                rows={curveRows}
                benchmarkLabel={String(context?.pool_item?.vt_symbol || "buy_hold")}
                height={360}
              />
            </div>
            <aside className="research-snapshot-card">
              <div><span>交易标的 / K 线周期</span><strong>{context.pool_item?.vt_symbol || "-"} · {context.config?.interval || "-"}</strong></div>
              <div><span>回测区间</span><strong>{context.config?.start_date || "-"} 至 {context.config?.end_date || "-"}</strong></div>
              <div><span>{UI_TEXT.metric.tradeCount}</span><strong>{Number(metrics.total_trade_count || 0).toLocaleString()}</strong></div>
              <div><span>{UI_TEXT.term.poolSnapshotId}</span><strong>{context.pool_item?.pool_item_id || "-"}</strong></div>
              <div className="research-parameter-summary">
                <span>当前参数</span>
                <div>{Object.entries(context.base_parameters || {}).filter(([name]) => name !== "fixed_size").map(([name, value]) => <em key={name}>{name}={String(value)}</em>)}</div>
              </div>
            </aside>
          </section>

          <section className="band research-conclusion-card">
            <div className="library-section-head"><div><h3>研究结论</h3><p>结论仅描述当前已完成的二维参数网格，不替代样本外检验。</p></div></div>
            {heatmap ? (
              <div className="research-conclusion-line">
                <span className={`research-status-dot is-${positiveRatio !== null && positiveRatio >= 0.7 ? "stable" : positiveRatio !== null && positiveRatio >= 0.4 ? "general" : "sensitive"}`} />
                <strong>{heatmap.x_parameter} × {heatmap.y_parameter}</strong>
                <span>{positiveRows.length} 个有效组合，{positiveRatio === null ? "-" : `${Math.round(positiveRatio * 100)}%`} 的{metric === "excess_return" ? UI_TEXT.metric.excessReturn : UI_TEXT.metric.sharpe}为正。</span>
                <Button type="link" size="small" onClick={() => switchTab("heatmap")}>查看热力图</Button>
              </div>
            ) : <div className="empty-state compact-empty">尚未运行参数稳定性分析。</div>}
          </section>
        </>
      ) : activeTab === "heatmap" ? (
        <>
          <section className="band research-settings-band">
            <div className="library-section-head">
              <div><h3>二维参数网格</h3><p>固定其他参数，只改变横纵轴两个参数；第一版最多运行 100 组。</p></div>
              <Button type="primary" loading={running} disabled={!xParameter || !yParameter || totalGridCount < 4 || totalGridCount > 100} onClick={runHeatmap}>运行稳定性分析</Button>
            </div>
            <div className="research-axis-grid">
              <label className="field"><span>横轴参数</span><Select value={xParameter || undefined} onChange={(value) => setXParameter(value)} options={parameterOptions.filter((item: { value: string }) => item.value !== yParameter)} /></label>
              <label className="field"><span>纵轴参数</span><Select value={yParameter || undefined} onChange={(value) => setYParameter(value)} options={parameterOptions.filter((item: { value: string }) => item.value !== xParameter)} /></label>
              <label className="field"><span>{UI_TEXT.research.displayMetric}</span><Select value={metric} onChange={setMetric} options={[{ value: "excess_return", label: UI_TEXT.metric.excessReturn }, { value: "sharpe", label: UI_TEXT.metric.sharpe }]} /></label>
              <div className="research-grid-count"><span>参数组合</span><strong>{totalGridCount || 0} 组</strong></div>
            </div>
            <div className="research-range-list">
              {renderRangeRow(xParameter, xParameterMeta)}
              {renderRangeRow(yParameter, yParameterMeta)}
            </div>
          </section>

          {heatmap ? (
            <section className="band research-heatmap-section">
              <div className="library-section-head">
                <div><h3>{UI_TEXT.research.parameterStabilityHeatmap}</h3><p>{heatmap.x_parameter} × {heatmap.y_parameter} · {formatDate(heatmap.created_at)} · ● 当前参数，★ 当前指标最优</p></div>
              </div>
              <div className="research-heatmap-layout">
                <ResearchHeatmap
                  rows={heatmapRows}
                  xParameter={heatmap.x_parameter}
                  yParameter={heatmap.y_parameter}
                  xValues={heatmap.x_values || []}
                  yValues={heatmap.y_values || []}
                  metric={metric}
                  currentParameters={context.base_parameters || {}}
                />
                <aside className="research-stability-card">
                  <span>当前网格</span>
                  <strong>{positiveRatio !== null && positiveRatio >= 0.7 ? "较稳定" : positiveRatio !== null && positiveRatio >= 0.4 ? "一般" : "较敏感"}</strong>
                  <p>{positiveRows.length} 个有效组合中，{positiveRatio === null ? "-" : `${Math.round(positiveRatio * 100)}%`} 的{metric === "excess_return" ? UI_TEXT.metric.excessReturn : UI_TEXT.metric.sharpe}为正。</p>
                  <dl>
                    <div><dt>横轴</dt><dd>{heatmap.x_parameter}</dd></div>
                    <div><dt>纵轴</dt><dd>{heatmap.y_parameter}</dd></div>
                    <div><dt>成功组合</dt><dd>{positiveRows.length}</dd></div>
                  </dl>
                </aside>
              </div>
            </section>
          ) : (
            <section className="band empty-state">设置两个参数范围并运行研究后，这里会显示热力图。</section>
          )}
        </>
      ) : (
        <>
          <section className="band research-settings-band">
            <div className="library-section-head">
              <div>
                <h3>{UI_TEXT.research.walkForward}配置</h3>
                <p>通过滚动样本外检验，使用过去一段时间训练选参，再用固定参数运行后续 6 个月样本外回测。</p>
              </div>
              <Button
                type="primary"
                loading={runningWalkForward}
                disabled={!walkParameters.length || walkGridCount < 2 || walkGridCount > 100}
                onClick={runWalkForward}
              >
                运行滚动优化
              </Button>
            </div>
            <div className="walk-forward-settings-grid">
              <label className="field">
                <span>训练开始日期</span>
                <input
                  className="research-date-input"
                  type="date"
                  min={String(context?.config?.start_date || "").slice(0, 10) || undefined}
                  max={String(context?.config?.end_date || "").slice(0, 10) || undefined}
                  value={trainingStartDate}
                  onChange={(event) => setTrainingStartDate(event.target.value)}
                />
              </label>
              <label className="field">
                <span>训练窗口</span>
                <Space.Compact block>
                  <InputNumber
                    min={6}
                    max={120}
                    step={6}
                    value={trainingMonths}
                    onChange={(value) => setTrainingMonths(Number(value || 24))}
                  />
                  <Input value="个月" disabled readOnly style={{ width: 64, textAlign: "center" }} />
                </Space.Compact>
              </label>
              <label className="field">
                <span>样本外窗口</span>
                <Space.Compact block>
                  <InputNumber value={6} disabled />
                  <Input value="个月" disabled readOnly style={{ width: 64, textAlign: "center" }} />
                </Space.Compact>
              </label>
              <label className="field">
                <span>{UI_TEXT.research.optimizationObjective}</span>
                <Select
                  value={walkObjective}
                  onChange={setWalkObjective}
                  options={[{ value: "sharpe", label: UI_TEXT.metric.sharpe }]}
                />
              </label>
              <div className="research-grid-count"><span>每期参数组合</span><strong>{walkGridCount || 0} 组</strong></div>
            </div>
            <label className="field walk-forward-parameter-select">
              <span>优化参数（最多 3 个）</span>
              <Select
                mode="multiple"
                value={walkParameters}
                onChange={(values) => {
                  if (values.length > 3) {
                    message.warning("第一版最多同时优化 3 个参数");
                    return;
                  }
                  setWalkParameters(values);
                }}
                options={parameterOptions}
                placeholder="选择需要滚动优化的参数"
              />
            </label>
            <div className="research-range-list">
              {walkParameters.map((name) => renderRangeRow(
                name,
                (context?.parameters || []).find((item: any) => String(item.name) === name),
                walkRanges,
                updateWalkRange
              ))}
            </div>
            <p className="walk-forward-note">第一版按 6 个月向前滚动；每个样本外窗口独立冷启动，不继承上一窗口的持仓与内部状态。完成后可按需计算完整样本外参数横截面。</p>
          </section>

          {walkForward ? (
            <>
              <section className="band research-walk-forward-results">
                <div className="library-section-head">
                  <div>
                    <h3>{UI_TEXT.research.walkForward}样本外曲线</h3>
                    <p>{walkForward.training_months} 个月训练期 / {walkForward.test_months} 个月样本外期 · {formatDate(walkForward.created_at)}</p>
                  </div>
                </div>
                <MultiVariantCurveChart
                  curves={{ walk_forward: walkCurveRows, fixed_parameters: fixedCurveRows }}
                  visibleKeys={["walk_forward", ...(fixedComparisonAvailable ? ["fixed_parameters"] : []), "buy_hold"]}
                  labels={{ walk_forward: UI_TEXT.research.walkForward, fixed_parameters: "固定参数对照" }}
                  benchmarkLabel={String(context?.pool_item?.vt_symbol || "buy_hold")}
                  orderedKeys={["walk_forward", "fixed_parameters", "buy_hold"]}
                  height={380}
                />
              </section>
              <section className="band library-shell">
                <div className="library-section-head">
                  <div>
                    <h3>绩效明细</h3>
                    <p>仅统计所有完整样本外窗口拼接后的表现，不包含训练期。</p>
                  </div>
                </div>
                <Table
                  rowKey="key"
                  columns={walkPerformanceColumns}
                  dataSource={walkPerformanceRows}
                  pagination={false}
                  scroll={{ x: 900 }}
                  className="workbench-table performance-detail-table"
                />
              </section>
              <section className="band research-walk-forward-windows">
                <div className="library-section-head">
                  <div>
                    <h3>各期选参</h3>
                    <p>参数只由对应训练期决定；完成完整参数横截面分析后可查看单期 Rank IC 和训练期/样本外期双热力图。</p>
                  </div>
                  <Button
                    type={rankAnalysisComplete ? "default" : "primary"}
                    loading={runningRankAnalysis}
                    disabled={rankAnalysisComplete || !walkForward.experiment_id}
                    onClick={runRankAnalysis}
                  >
                    {rankAnalysisComplete ? "参数横截面已计算" : "计算完整参数横截面"}
                  </Button>
                </div>
                <div className="walk-forward-window-list">
                  {(walkForward.windows || []).map((window: any) => {
                    const rankIc = Number(window?.rank_analysis?.rank_ic);
                    const hasRankIc = hasFiniteValue(window?.rank_analysis?.rank_ic);
                    const hasHeatmapRows = (window?.rank_analysis?.rows || []).length > 0;
                    const canOpenHeatmaps = dualHeatmapSupported && hasHeatmapRows;
                    const heatmapHint = !dualHeatmapSupported
                      ? "双热力图仅支持两个参数"
                      : hasHeatmapRows
                        ? "点击比较训练期 / 样本外期热力图"
                        : "完成参数横截面分析后可查看";
                    return (
                      <button
                        type="button"
                        className={`walk-forward-window-row ${canOpenHeatmaps ? "is-clickable" : ""}`}
                        key={window.index}
                        disabled={!canOpenHeatmaps}
                        title={heatmapHint}
                        aria-label={`第 ${window.index} 期，${heatmapHint}`}
                        onClick={() => openWindowHeatmaps(window)}
                      >
                        <div className="walk-forward-window-lead">
                          <strong>第 {window.index} 期</strong>
                          <span className={`walk-forward-rank-ic ${hasRankIc ? rankIc >= 0 ? "positive" : "negative" : "pending"}`}>
                            Rank IC <b>{hasRankIc ? formatNumber(rankIc, 3) : "待计算"}</b>
                          </span>
                        </div>
                        <span>训练期 {window.train_start} 至 {window.train_end}<b>{UI_TEXT.metric.sharpe} {formatNumber(window.train_metrics?.sharpe ?? window.train_metrics?.sharpe_ratio)}</b></span>
                        <span>
                          样本外期 {window.test_start} 至 {window.test_end}
                          <b>滚动选参夏普比率 {formatNumber(window.test_metrics?.sharpe ?? window.test_metrics?.sharpe_ratio)}</b>
                          <b>固定参数夏普比率 {formatNumber(window.fixed_test_metrics?.sharpe ?? window.fixed_test_metrics?.sharpe_ratio)}</b>
                        </span>
                        <div className="walk-forward-window-parameters">
                          <div>{Object.entries(window.selected_parameters || {}).map(([name, value]) => <em key={name}>{name}={String(value)}</em>)}</div>
                          <small>{heatmapHint}</small>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </section>
              <section className="library-metric-grid research-metric-grid">
                <div className="library-metric-card"><span>完整窗口</span><strong>{Number(walkForward.window_count || 0)}</strong></div>
                <div className="library-metric-card"><span>滚动选参累计收益</span><strong>{formatPercent(walkSummary.strategy?.totalReturn)}</strong></div>
                <div className="library-metric-card"><span>固定参数累计收益</span><strong>{fixedComparisonAvailable ? formatPercent(fixedSummary.strategy?.totalReturn) : "-"}</strong></div>
                <div className={`library-metric-card ${Number(walkReturnUplift) >= 0 ? "positive" : "negative"}`}><span>相对固定参数</span><strong>{walkReturnUplift === null ? "-" : formatPercent(walkReturnUplift)}</strong></div>
              </section>
              {rankAnalysisWindows.length ? (
                <>
                  <section className="library-metric-grid research-metric-grid rank-analysis-metrics">
                    <div className={`library-metric-card ${Number(predictability.mean_rank_ic) >= 0 ? "positive" : "negative"}`}>
                      <span>平均 Rank IC</span>
                      <strong>{formatNumber(predictability.mean_rank_ic, 3)}</strong>
                    </div>
                    <div className="library-metric-card">
                      <span>Rank IC 为正窗口</span>
                      <strong>{formatRatio(predictability.positive_rank_ic_ratio)}</strong>
                    </div>
                    <div className="library-metric-card">
                      <span>ICIR</span>
                      <strong>{formatNumber(predictability.icir, 3)}</strong>
                    </div>
                    <div className={`library-metric-card ${Number(predictability.mean_top_20_lift) >= 0 ? "positive" : "negative"}`}>
                      <span>平均 Top 20% Lift</span>
                      <strong>{formatNumber(predictability.mean_top_20_lift, 3)}</strong>
                    </div>
                    <div className={`library-metric-card ${Number(predictability.group_monotonicity) >= 0 ? "positive" : "negative"}`}>
                      <span>分组单调性</span>
                      <strong>{formatNumber(predictability.group_monotonicity, 3)}</strong>
                    </div>
                  </section>

                  <section className="band library-shell research-rank-analysis">
                    <div className="library-section-head">
                      <div>
                        <h3>参数预测能力</h3>
                        <p>同一参数横截面分别在训练期与紧随其后的样本外期评分；Rank IC 为两期夏普比率排名的 Spearman 相关。</p>
                      </div>
                    </div>
                    <div className="rank-group-strip" aria-label="参数分组单调性">
                      {rankGroupRows.map((group: any) => (
                        <div className={`rank-group-card ${Number(group.test_score_mean) >= 0 ? "positive" : "negative"}`} key={group.label}>
                          <span>{group.label}<small>训练排名由低到高</small></span>
                          <strong>{formatNumber(group.test_score_mean, 3)}</strong>
                          <em>样本外期夏普比率均值</em>
                          <small>训练均值 {formatNumber(group.training_score_mean, 3)} · {group.window_count} 个窗口</small>
                        </div>
                      ))}
                    </div>
                    <p className="rank-analysis-note">Q 编号越高，训练期排名越靠前。理想情况下样本外期夏普比率应随 Q1 → Q5 大致上升；分组单调性越接近 1 越好。</p>
                    <Table
                      rowKey="index"
                      columns={rankWindowColumns}
                      dataSource={rankAnalysisWindows}
                      pagination={false}
                      scroll={{ x: 1000 }}
                      className="workbench-table rank-window-table"
                      onRow={(row: any) => ({ onClick: () => setRankDetailWindowIndex(Number(row.index)) })}
                    />
                  </section>

                  <section className="band library-shell research-rank-detail">
                    <div className="library-section-head">
                      <div>
                        <h3>参数横截面明细</h3>
                        <p>按训练期排名展示同一组合在样本外期的评分和名次，便于识别孤立高点、排序反转与稳定区域。</p>
                      </div>
                      <Select
                        value={Number(rankDetailWindow?.index || rankDetailWindowIndex)}
                        onChange={(value) => setRankDetailWindowIndex(Number(value))}
                        options={rankAnalysisWindows.map((window: any) => ({
                          value: Number(window.index),
                          label: `第 ${window.index} 期 · ${window.test_start} 至 ${window.test_end}`
                        }))}
                        className="rank-window-select"
                      />
                    </div>
                    <Table
                      rowKey={(row: any) => `${rankDetailWindow?.index || 0}-${row.label}`}
                      columns={rankDetailColumns}
                      dataSource={rankDetailWindow?.rank_analysis?.rows || []}
                      pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
                      scroll={{ x: 820 }}
                      className="workbench-table rank-detail-table"
                    />
                  </section>
                </>
              ) : (
                <section className="band empty-state">尚未计算参数 Rank IC。点击“计算完整参数横截面”后，平台会按需复测并生成分组单调性。</section>
              )}
              <Modal
                open={selectedHeatmapWindow !== null}
                onCancel={() => setHeatmapWindowIndex(null)}
                footer={null}
                width={1400}
                centered
                className="walk-forward-heatmap-modal"
                title={selectedHeatmapWindow ? (
                  <div className="walk-forward-heatmap-modal-title">
                    <strong>第 {selectedHeatmapWindow.index} 期训练期 / 样本外期夏普比率热力图</strong>
                    <small>
                      训练期 {selectedHeatmapWindow.train_start} 至 {selectedHeatmapWindow.train_end}
                      <i>·</i>
                      样本外期 {selectedHeatmapWindow.test_start} 至 {selectedHeatmapWindow.test_end}
                      <i>·</i>
                      Rank IC <b className={selectedHeatmapHasRankIc ? Number(selectedHeatmapRankIc) >= 0 ? "positive" : "negative" : "pending"}>
                        {selectedHeatmapHasRankIc ? formatNumber(selectedHeatmapRankIc, 3) : "待计算"}
                      </b>
                    </small>
                  </div>
                ) : "训练期 / 样本外期夏普比率热力图"}
                destroyOnHidden
              >
                {selectedHeatmapWindow && (
                  <>
                    <nav className="walk-forward-heatmap-period-nav" aria-label="切换滚动优化期数">
                      <button
                        type="button"
                        disabled={!previousHeatmapWindow}
                        onClick={() => previousHeatmapWindow && setHeatmapWindowIndex(Number(previousHeatmapWindow.index))}
                        aria-label={previousHeatmapWindow ? `查看第 ${previousHeatmapWindow.index} 期` : "已经是第一期"}
                        title={previousHeatmapWindow ? `上一期：第 ${previousHeatmapWindow.index} 期` : "已经是第一期"}
                      >
                        ‹
                      </button>
                      <span>第 {heatmapWindowPosition + 1} / {rankAnalysisWindows.length} 期</span>
                      <button
                        type="button"
                        disabled={!nextHeatmapWindow}
                        onClick={() => nextHeatmapWindow && setHeatmapWindowIndex(Number(nextHeatmapWindow.index))}
                        aria-label={nextHeatmapWindow ? `查看第 ${nextHeatmapWindow.index} 期` : "已经是最后一期"}
                        title={nextHeatmapWindow ? `下一期：第 ${nextHeatmapWindow.index} 期` : "已经是最后一期"}
                      >
                        ›
                      </button>
                    </nav>
                    <div className="walk-forward-dual-heatmap-grid">
                      <section className="walk-forward-heatmap-panel">
                        <div>
                          <h4>训练期夏普比率</h4>
                          <p>★ 为训练期最优，● 为该期最终选中的参数。</p>
                        </div>
                        <ResearchHeatmap
                          rows={trainingHeatmapRows}
                          xParameter={heatmapXParameter}
                          yParameter={heatmapYParameter}
                          xValues={walkHeatmapXValues}
                          yValues={walkHeatmapYValues}
                          metric="sharpe"
                          currentParameters={selectedHeatmapWindow.selected_parameters || {}}
                          visualRange={sharedHeatmapRange}
                        />
                      </section>
                      <section className="walk-forward-heatmap-panel">
                        <div>
                          <h4>样本外期夏普比率</h4>
                          <p>★ 为样本外期最优，● 仍标记训练期选中的参数。</p>
                        </div>
                        <ResearchHeatmap
                          rows={testHeatmapRows}
                          xParameter={heatmapXParameter}
                          yParameter={heatmapYParameter}
                          xValues={walkHeatmapXValues}
                          yValues={walkHeatmapYValues}
                          metric="sharpe"
                          currentParameters={selectedHeatmapWindow.selected_parameters || {}}
                          visualRange={sharedHeatmapRange}
                        />
                      </section>
                    </div>
                    <p className="walk-forward-heatmap-shared-note">
                      两图横纵轴和颜色范围完全一致；失败的参数组合保留为空白格，便于直接比较样本内外的稳定性。
                    </p>
                  </>
                )}
              </Modal>
            </>
          ) : (
            <section className="band empty-state">设置训练窗口和优化参数后运行，这里会显示拼接后的样本外曲线。</section>
          )}
        </>
      )}
    </div>
  );
}
