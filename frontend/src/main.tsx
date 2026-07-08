import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { Button, Checkbox, ConfigProvider, Input, InputNumber, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import * as echarts from "echarts";
import {
  addToPool,
  comparePool,
  createResearch,
  downloadData,
  generateStrategy,
  getDataCoverage,
  getNaturalLanguageSource,
  getOptimizationMethods,
  getOptimizationSearchSpace,
  getPoolItem,
  getVariantCurve,
  getRun,
  listRuns,
  listNaturalLanguageSources,
  listPool,
  listTasks,
  runOptimization
} from "./api";
import "./styles.css";

type PageKey = "launch" | "generate" | "optimize" | "pool";

const zh = {
  workbench: "\u7814\u7a76\u5de5\u4f5c\u53f0",
  subtitle: "\u81ea\u7136\u8bed\u8a00\u7b56\u7565\u751f\u6210\u3001\u53c2\u6570\u5b9e\u9a8c\u548c\u7b56\u7565\u6c60\u6c89\u6dc0\u7684\u7edf\u4e00\u5165\u53e3\u3002",
  launchFlow: "\u542f\u52a8\u6d41\u7a0b",
  generate: "\u7b56\u7565\u751f\u6210",
  optimize: "\u53c2\u6570\u4f18\u5316",
  pool: "\u7b56\u7565\u6c60",
  status: "\u5de5\u4f5c\u53f0\u72b6\u6001",
  recentTasks: "\u6700\u8fd1\u4efb\u52a1",
  clearAll: "\u6e05\u9664\u5168\u90e8",
  refresh: "\u5237\u65b0",
  waiting: "\u7b49\u5f85\u4efb\u52a1",
  strategyCodeGeneration: "\u751f\u6210 strategy.py",
  baselineBacktest: "\u57fa\u7ebf\u56de\u6d4b",
  startConfig: "\u542f\u52a8\u914d\u7f6e",
  currentProgress: "\u5f53\u524d\u8fdb\u5ea6",
  resultHub: "\u7ed3\u679c\u5165\u53e3",
  sourceFiles: "\u81ea\u7136\u8bed\u8a00\u6587\u4ef6",
  sourceText: "\u81ea\u7136\u8bed\u8a00\u8f93\u5165",
  backtestConfig: "\u56de\u6d4b\u8303\u56f4\u4e0e\u6210\u672c",
  symbolPoolFile: "\u6807\u7684\u6c60\u6587\u4ef6",
  symbol: "\u6807\u7684",
  exchange: "\u4ea4\u6613\u6240",
  interval: "\u5468\u671f",
  rate: "\u624b\u7eed\u8d39\u7387",
  startDate: "\u5f00\u59cb\u65e5\u671f",
  endDate: "\u7ed3\u675f\u65e5\u671f",
  slippage: "\u6ed1\u70b9",
  dataCoverage: "\u6570\u636e\u8986\u76d6",
  checkCoverage: "\u68c0\u67e5\u8986\u76d6",
  downloadMarketData: "\u4e0b\u8f7d\u884c\u60c5",
  localRange: "\u672c\u5730\u533a\u95f4",
  barCount: "K\u7ebf\u6570\u91cf",
  missingRanges: "\u7f3a\u5931\u533a\u95f4",
  researchFailed: "\u56de\u6d4b\u672a\u5b8c\u6210",
  dataMissingHint: "\u6570\u636e\u7f3a\u5931\u65f6\uff0c\u8bf7\u5148\u4e0b\u8f7d\u884c\u60c5\u518d\u542f\u52a8\u7814\u7a76\u3002",
  loadSource: "\u8f7d\u5165\u6587\u672c",
  selectAll: "\u5168\u9009",
  clear: "\u6e05\u7a7a",
  edit: "\u7f16\u8f91",
  startResearch: "\u542f\u52a8\u7814\u7a76\u6d41\u7a0b",
  generateOnly: "\u53ea\u751f\u6210 strategy.py",
  goOptimize: "\u53bb\u53c2\u6570\u4f18\u5316",
  latestRun: "\u6700\u8fd1 run",
  latestStrategy: "\u6700\u8fd1 strategy",
  parameterEngineNotConnected: "\u53c2\u6570\u4f18\u5316\u5f15\u64ce\u5c1a\u672a\u63a5\u5165\u3002\u6b64\u5904\u4e0d\u4f7f\u7528 mock \u5047\u88c5\u771f\u5b9e\u4f18\u5316\u3002",
  currentSelection: "\u5f53\u524d\u9009\u62e9",
  paramName: "\u53c2\u6570\u540d",
  currentValue: "\u5f53\u524d\u503c",
  startOptimization: "\u542f\u52a8\u4f18\u5316",
  poolList: "\u7b56\u7565\u6c60\u5217\u8868",
  strategyName: "\u7b56\u7565\u540d",
  sharpe: "Sharpe",
  return: "\u6536\u76ca",
  drawdown: "\u6700\u5927\u56de\u64a4",
  createdAt: "\u521b\u5efa\u65f6\u95f4",
  tags: "tags",
  action: "\u64cd\u4f5c",
  open: "\u67e5\u770b",
  notes: "notes",
  curve: "curve chart",
  trades: "trades table",
  code: "strategy code"
};

const PIPELINE_STAGES = [
  { key: "generation", title: zh.strategyCodeGeneration, note: "\u6839\u636e\u81ea\u7136\u8bed\u8a00\u8f93\u5165\u751f\u6210 vn.py CTA strategy.py\uff0c\u5e76\u767b\u8bb0\u7b56\u7565\u4ee3\u7801\u7248\u672c\u3002" },
  { key: "backtest", title: zh.baselineBacktest, note: "\u4f7f\u7528\u672c\u5730 SQLite \u884c\u60c5\u6570\u636e\u8fd0\u884c\u771f\u5b9e baseline \u56de\u6d4b\uff0c\u751f\u6210 run\u3001curve \u548c trades\u3002" }
];

const SOURCE_FILES = [
  "opening_range_breakout_intraday.txt",
  "bollinger_rsi_reversion_loose.txt",
  "dual_thrust_classic.txt",
  "turtle_trading_classic.txt"
];

type SourceFile = {
  name: string;
  size?: number;
  modified_at?: string;
};

const PARAM_ROWS = [
  { key: "fast_window", current: 10, low: 5, high: 40, step: 1, type: "int" },
  { key: "slow_window", current: 30, low: 20, high: 120, step: 5, type: "int" },
  { key: "atr_multiplier", current: 2.0, low: 1.0, high: 5.0, step: 0.25, type: "float" },
  { key: "stop_loss_pct", current: 0.03, low: 0.01, high: 0.12, step: 0.01, type: "float" }
];

function formatDate(value?: string) {
  if (!value) return "-";
  const text = String(value);
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/.test(text);
  const parseText = hasTimezone ? text : text.includes("T") ? `${text}+08:00` : text;
  const parsed = new Date(parseText);
  if (Number.isNaN(parsed.getTime())) return text.replace("T", " ");
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(parsed).replace(/\//g, "-");
}

function formatNumber(value: unknown, digits = 2) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "-";
}

function formatPercent(value: unknown, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "-";
  const normalized = Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
  return `${normalized.toFixed(digits)}%`;
}

function formatReturnPct(value: unknown, digits = 2) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}%` : "-";
}

function statusClass(status?: string) {
  const normalized = String(status || "pending").toLowerCase();
  if (["succeeded", "completed", "optimized"].includes(normalized)) return "status-pill status-completed";
  if (["running", "queued"].includes(normalized)) return "status-pill status-running";
  if (normalized === "failed") return "status-pill status-failed";
  return "status-pill status-pending";
}

function coverageStatusClass(status?: string) {
  const normalized = String(status || "unchecked").toLowerCase();
  if (["covered", "available", "ok"].includes(normalized)) return "status-pill status-completed";
  if (normalized === "partial") return "status-pill status-running";
  if (["missing", "failed"].includes(normalized)) return "status-pill status-failed";
  return "status-pill status-pending";
}

function extractMissingRanges(payload: any): any[] {
  const direct = Array.isArray(payload?.missing_ranges) ? payload.missing_ranges : [];
  if (direct.length > 0) return direct;
  if (!Array.isArray(payload?.diagnostics)) return [];
  return payload.diagnostics.flatMap((item: any) => Array.isArray(item?.missing_ranges) ? item.missing_ranges : []);
}

function missingRangeLabel(range: any) {
  const start = range?.start_date || range?.start || "?";
  const end = range?.end_date || range?.end || "?";
  return `${start} - ${end}`;
}

type NormalizedCurvePoint = {
  date: string;
  value: number;
};

type NormalizedCurveSeries = {
  key: string;
  label: string;
  type: "strategy" | "benchmark";
  points: NormalizedCurvePoint[];
  totalReturn: number;
  basis?: "capital" | "position";
};

function finiteNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function rowDate(row: any): string {
  return String(row?.date || row?.datetime || row?.trading_day || "");
}

function firstFinite(rows: any[], keys: string[]): number | null {
  for (const row of rows) {
    for (const key of keys) {
      const value = finiteNumber(row?.[key]);
      if (value !== null && value !== 0) return value;
    }
  }
  return null;
}

function valueFromKeys(row: any, keys: string[]): number | null {
  for (const key of keys) {
    const value = finiteNumber(row?.[key]);
    if (value !== null) return value;
  }
  return null;
}

function normalizeSeries(rows: any[], keys: string[], baseValue: number | null): NormalizedCurvePoint[] {
  if (!baseValue) return [];
  return rows
    .map((row) => {
      const value = valueFromKeys(row, keys);
      if (value === null) return null;
      return {
        date: rowDate(row),
        value: ((value / baseValue) - 1) * 100
      };
    })
    .filter((item): item is NormalizedCurvePoint => Boolean(item));
}

function pointRange(points: NormalizedCurvePoint[]): number {
  if (points.length === 0) return 0;
  const values = points.map((point) => point.value);
  return Math.max(...values) - Math.min(...values);
}

function cumulativeNetPnlSeries(rows: any[], baseValue: number | null): NormalizedCurvePoint[] {
  if (!baseValue) return [];
  let cumulative = 0;
  return rows
    .map((row) => {
      const netPnl = finiteNumber(row?.net_pnl);
      if (netPnl === null) return null;
      cumulative += netPnl;
      return {
        date: rowDate(row),
        value: (cumulative / baseValue) * 100
      };
    })
    .filter((item): item is NormalizedCurvePoint => Boolean(item));
}

function buildStrategyCurve(rows: any[], balanceBase: number | null, closeBase: number | null): NormalizedCurveSeries | null {
  const capitalPoints = normalizeSeries(rows, ["balance", "net_value", "equity"], balanceBase);
  const capitalRange = pointRange(capitalPoints);
  const positionPoints = cumulativeNetPnlSeries(rows, closeBase);
  if (positionPoints.length > 0 && capitalRange < 0.05) {
    return {
      key: "strategy",
      label: "策略收益（持仓归一）",
      type: "strategy",
      points: positionPoints,
      totalReturn: positionPoints[positionPoints.length - 1]?.value ?? 0,
      basis: "position"
    };
  }
  if (capitalPoints.length > 0) {
    return {
      key: "strategy",
      label: "策略收益率",
      type: "strategy",
      points: capitalPoints,
      totalReturn: capitalPoints[capitalPoints.length - 1]?.value ?? 0,
      basis: "capital"
    };
  }
  return null;
}

function buildNormalizedCurveSeries(rows: any[]): NormalizedCurveSeries[] {
  const balanceBase = firstFinite(rows, ["balance", "net_value", "equity"]);
  const closeBase = firstFinite(rows, ["close_price", "close", "price"]);
  const strategyCurve = buildStrategyCurve(rows, balanceBase, closeBase);
  const buyHoldPoints = normalizeSeries(rows, ["close_price", "close", "price"], closeBase);
  const series: NormalizedCurveSeries[] = [];
  if (strategyCurve) series.push(strategyCurve);
  if (buyHoldPoints.length > 1) {
    series.push({
      key: "buy_hold",
      label: "Buy & Hold",
      type: "benchmark",
      points: buyHoldPoints,
      totalReturn: buyHoldPoints[buyHoldPoints.length - 1]?.value ?? 0
    });
  }
  return series;
}

function curveSummary(rows: any[]) {
  const series = buildNormalizedCurveSeries(rows);
  const strategy = series.find((item) => item.key === "strategy");
  const buyHold = series.find((item) => item.key === "buy_hold");
  const excess = strategy && buyHold ? strategy.totalReturn - buyHold.totalReturn : null;
  return { strategy, buyHold, excess };
}

function CurveChart({ rows, height = 340 }: { rows: any[]; height?: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const series = useMemo(() => buildNormalizedCurveSeries(rows), [rows]);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const activePoints = series.flatMap((item) => item.points);
    const yValues = activePoints.map((point) => point.value).filter((value) => Number.isFinite(value));
    const rawMin = Math.min(...yValues, 0);
    const rawMax = Math.max(...yValues, 0);
    const padding = Math.max(0.02, (rawMax - rawMin) * 0.12 || 0.05);
    chart.setOption({
      animation: false,
      color: ["#17b8b1", "#64748b"],
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.92)",
        borderWidth: 0,
        textStyle: { color: "#f8fafc" },
        valueFormatter: (value: number | string) => `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`
      },
      grid: { left: 56, right: 18, top: 20, bottom: 42 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: rows.map(rowDate),
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "value",
        min: rawMin - padding,
        max: rawMax + padding,
        axisLabel: {
          color: "#64748b",
          formatter: (value: number) => `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%`
        },
        splitLine: { lineStyle: { color: "rgba(203,213,225,0.6)" } }
      },
      series: series.map((item) => ({
          name: item.label,
          type: "line",
          smooth: false,
          showSymbol: false,
          emphasis: { focus: "series" },
          lineStyle: {
            width: item.type === "benchmark" ? 2 : 3,
            type: item.type === "benchmark" ? "dashed" : "solid"
          },
          areaStyle: item.type === "strategy" ? { color: "rgba(23, 184, 177, 0.08)" } : undefined,
          data: item.points.map((point) => point.value)
        }))
    }, true);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [rows, series]);
  return (
    <div className="curve-chart-shell">
      <div ref={ref} className="curve-canvas" style={{ height }} />
      {series.length > 0 && (
        <div className="curve-legend">
          {series.map((item) => (
            <div className={`curve-series-card ${item.totalReturn >= 0 ? "positive" : "negative"}`} key={item.key}>
              <div className="curve-series-head">
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} />
                <strong>{item.label}</strong>
              </div>
              <div className="curve-series-metrics">
                {item.basis === "position" ? "持仓归一" : "总收益"} {formatReturnPct(item.totalReturn, 2)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function buildComparisonSeries(
  curves: Record<string, any[]>,
  visibleKeys: string[],
  labels: Record<string, string> = {},
  benchmark?: NormalizedCurveSeries | null
): NormalizedCurveSeries[] {
  const series: NormalizedCurveSeries[] = [];
  const variantKeys = visibleKeys.filter((key) => key !== "buy_hold");
  for (const variantName of variantKeys) {
    const strategySeries = buildNormalizedCurveSeries(curves[variantName] || []).find((item) => item.key === "strategy");
    if (strategySeries) {
      series.push({
        ...strategySeries,
        key: `variant:${variantName}`,
        label: labels[variantName] || variantName
      });
    }
  }

  if (visibleKeys.includes("buy_hold")) {
    if (benchmark) {
      series.push(benchmark);
    } else {
      const benchmarkSource = curves.baseline || curves[variantKeys[0]] || Object.values(curves)[0] || [];
      const generatedBenchmark = buildNormalizedCurveSeries(benchmarkSource).find((item) => item.key === "buy_hold");
      if (generatedBenchmark) series.push(generatedBenchmark);
    }
  }

  return series;
}

function MultiVariantCurveChart({
  curves,
  visibleKeys,
  labels = {},
  benchmark = null,
  height = 340
}: {
  curves: Record<string, any[]>;
  visibleKeys: string[];
  labels?: Record<string, string>;
  benchmark?: NormalizedCurveSeries | null;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const series = useMemo(() => buildComparisonSeries(curves, visibleKeys, labels, benchmark), [curves, visibleKeys, labels, benchmark]);
  const dates = useMemo(() => {
    const seen = new Set<string>();
    for (const item of series) {
      for (const point of item.points) {
        if (point.date) seen.add(point.date);
      }
    }
    return Array.from(seen).sort();
  }, [series]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const yValues = series.flatMap((item) => item.points.map((point) => point.value)).filter((value) => Number.isFinite(value));
    const rawMin = yValues.length ? Math.min(...yValues, 0) : 0;
    const rawMax = yValues.length ? Math.max(...yValues, 0) : 0;
    const padding = Math.max(0.02, (rawMax - rawMin) * 0.12 || 0.05);
    chart.setOption({
      animation: false,
      color: ["#17b8b1", "#2563eb", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"],
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.92)",
        borderWidth: 0,
        textStyle: { color: "#f8fafc" },
        valueFormatter: (value: number | string) => `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`
      },
      grid: { left: 56, right: 18, top: 20, bottom: 42 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: dates,
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "value",
        min: rawMin - padding,
        max: rawMax + padding,
        axisLabel: {
          color: "#64748b",
          formatter: (value: number) => `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%`
        },
        splitLine: { lineStyle: { color: "rgba(203,213,225,0.6)" } }
      },
      series: series.map((item) => {
        const byDate = new Map(item.points.map((point) => [point.date, point.value]));
        return {
          name: item.label,
          type: "line",
          smooth: false,
          showSymbol: false,
          emphasis: { focus: "series" },
          lineStyle: {
            width: item.type === "benchmark" ? 2 : 3,
            type: item.type === "benchmark" ? "dashed" : "solid"
          },
          data: dates.map((date) => byDate.get(date) ?? null)
        };
      })
    }, true);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dates, series]);

  return (
    <div className="curve-chart-shell">
      <div ref={ref} className="curve-canvas" style={{ height }} />
      {series.length > 0 && (
        <div className="curve-legend">
          {series.map((item) => (
            <div className={`curve-series-card ${item.totalReturn >= 0 ? "positive" : "negative"}`} key={item.key}>
              <div className="curve-series-head">
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} />
                <strong>{item.label}</strong>
              </div>
              <div className="curve-series-metrics">
                {item.basis === "position" ? "持仓归一" : "总收益"} {formatReturnPct(item.totalReturn, 2)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Sidebar({
  page,
  onPageChange,
  tasks,
  onRefreshTasks
}: {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  tasks: any[];
  onRefreshTasks: () => Promise<void>;
}) {
  const [hiddenTasks, setHiddenTasks] = useState(false);
  const visibleTasks = hiddenTasks ? [] : tasks.slice(0, 6);
  const latest = tasks[0];
  return (
    <aside className="sidebar">
      <div className="brand-block">
        <p className="eyebrow">GYRO_NICERT</p>
        <h1>{zh.workbench}</h1>
        <p className="sidebar-copy">{zh.subtitle}</p>
      </div>

      <section className="sidebar-section nav-section">
        {[
          ["launch", zh.launchFlow],
          ["generate", zh.generate],
          ["optimize", zh.optimize],
          ["pool", zh.pool]
        ].map(([key, label]) => (
          <button key={key} type="button" className={`nav-button ${page === key ? "is-active" : ""}`} onClick={() => onPageChange(key as PageKey)}>
            {label}
          </button>
        ))}
      </section>

      <section className="sidebar-section status-section">
        <div className="section-head status-head">
          <h2>{zh.status}</h2>
          <button className="mini-button" type="button" onClick={() => onRefreshTasks().catch((error) => message.error(String(error)))}>
            {zh.refresh}
          </button>
        </div>
        <div className="status-card-shell">
          <span className={statusClass(latest?.status)}>{latest?.status || "ready"}</span>
          <strong className="status-main">{latest?.task_type || zh.waiting}</strong>
          <span className="status-sub">{latest ? formatDate(latest.updated_at) : "API ready"}</span>
        </div>
      </section>

      <section className="sidebar-section jobs-section">
        <div className="section-head">
          <h2>{zh.recentTasks}</h2>
          <div className="jobs-head-actions">
            <span>{visibleTasks.length}</span>
            <button className="mini-button" type="button" onClick={() => setHiddenTasks(true)}>
              {zh.clearAll}
            </button>
          </div>
        </div>
        <div className="jobs-rail">
          {visibleTasks.length ? (
            visibleTasks.map((task) => (
              <div className="rail-job" key={task.task_id}>
                <div className="rail-job-head">
                  <strong>{task.task_type}</strong>
                  <span className={statusClass(task.status)}>{task.status}</span>
                </div>
                <div className="mini-progress">
                  <span style={{ width: `${Math.max(0, Math.min(100, Number(task.progress || 0) * 100))}%` }} />
                </div>
                <span className="rail-job-meta">{task.message || task.task_id}</span>
              </div>
            ))
          ) : (
            <div className="rail-job muted-card">
              <span className="rail-job-meta">No visible tasks.</span>
            </div>
          )}
        </div>
      </section>
    </aside>
  );
}

function HeroMetrics({ lastRun, poolCount, taskCount }: { lastRun: any; poolCount: number; taskCount: number }) {
  return (
    <div className="hero-metrics">
      <div className="metric-tile"><div className="metric-value">{taskCount}</div><div className="metric-label">\u81ea\u7136\u8bed\u8a00\u8f93\u5165</div></div>
      <div className="metric-tile"><div className="metric-value">1</div><div className="metric-label">\u6807\u7684\u6c60</div></div>
      <div className="metric-tile"><div className="metric-value">{poolCount}</div><div className="metric-label">Raw Assets</div></div>
      <div className="metric-tile"><div className="metric-value">{lastRun?.baseline?.run?.run_id ? "1" : "0"}</div><div className="metric-label">\u6700\u8fd1\u56de\u6d4b</div></div>
    </div>
  );
}

function LaunchFlowPage({
  tasks,
  poolCount,
  lastResearch,
  onResearchCreated,
  onGenerated,
  onOpenGenerated,
  onGoOptimize,
  refreshPool,
  refreshTasks
}: {
  tasks: any[];
  poolCount: number;
  lastResearch: any;
  onResearchCreated: (payload: any) => void;
  onGenerated: (payload: any) => void;
  onOpenGenerated: () => void;
  onGoOptimize: () => void;
  refreshPool: () => Promise<void>;
  refreshTasks: () => Promise<void>;
}) {
  const fallbackSourceFiles = SOURCE_FILES.map((name) => ({ name }));
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>(fallbackSourceFiles);
  const [selectedFiles, setSelectedFiles] = useState<string[]>(SOURCE_FILES.slice(0, 2));
  const [sourceText, setSourceText] = useState("\u7528 20 \u65e5\u5747\u7ebf\u548c 60 \u65e5\u5747\u7ebf\u505a\u8d8b\u52bf\u8ddf\u8e2a\uff0c\u91d1\u53c9\u5f00\u591a\uff0c\u6b7b\u53c9\u5e73\u4ed3\uff0c\u52a0\u5165 ATR \u6b62\u635f\u3002");
  const [symbol, setSymbol] = useState("510300");
  const [exchange, setExchange] = useState("SSE");
  const [interval, setInterval] = useState("1m");
  const [startDate, setStartDate] = useState("2024-01-02");
  const [endDate, setEndDate] = useState("2024-01-31");
  const [rate, setRate] = useState<number | null>(0.000045);
  const [slippage, setSlippage] = useState<number | null>(0.001);
  const [loadingGenerate, setLoadingGenerate] = useState(false);
  const [loadingResearch, setLoadingResearch] = useState(false);
  const [loadingPool, setLoadingPool] = useState(false);
  const [loadingSources, setLoadingSources] = useState(false);
  const [loadingCoverage, setLoadingCoverage] = useState(false);
  const [loadingDownload, setLoadingDownload] = useState(false);
  const [coverage, setCoverage] = useState<any>(null);
  const [researchError, setResearchError] = useState<any>(null);
  const [generationResult, setGenerationResult] = useState<any>(null);
  const latestTask = tasks[0];
  const coverageMissingRanges = extractMissingRanges(coverage);
  const researchMissingRanges = extractMissingRanges(researchError?.backtest);
  const missingRanges = coverageMissingRanges.length > 0 ? coverageMissingRanges : researchMissingRanges;
  const generationDone = Boolean(generationResult?.strategy || lastResearch?.generation?.strategy);
  const baselineDone = Boolean(lastResearch?.baseline?.run?.run_id);
  const baselineFailed = Boolean(researchError || lastResearch?.error);
  const pipelineStages = PIPELINE_STAGES.map((stage) => {
    if (stage.key === "generation") {
      const status = generationDone ? "completed" : (loadingGenerate || loadingResearch ? "running" : "pending");
      return { ...stage, status };
    }
    const status = baselineDone ? "completed" : (baselineFailed ? "failed" : (loadingResearch ? "running" : "pending"));
    return { ...stage, status };
  });
  const completedStageCount = pipelineStages.filter((stage) => stage.status === "completed").length;
  const workflowProgress = pipelineStages.length > 0 ? completedStageCount / pipelineStages.length : 0;

  useEffect(() => {
    let active = true;
    setLoadingSources(true);
    listNaturalLanguageSources()
      .then((payload) => {
        if (!active) return;
        const files = Array.isArray(payload.files) ? payload.files : [];
        if (files.length > 0) {
          setSourceFiles(files);
          setSelectedFiles(files.slice(0, 2).map((file: SourceFile) => file.name));
        }
      })
      .catch(() => {
        if (active) message.warning("natural language source list unavailable");
      })
      .finally(() => {
        if (active) setLoadingSources(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function loadSourceText(filename?: string) {
    const selectedName = filename || selectedFiles[0];
    if (!selectedName) {
      message.warning("select a source txt first");
      return;
    }
    setLoadingSources(true);
    try {
      const payload = await getNaturalLanguageSource(selectedName);
      setSourceText(String(payload.text || ""));
      setSelectedFiles((current) => current.includes(selectedName) ? current : [selectedName, ...current]);
      message.success(`loaded ${selectedName}`);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingSources(false);
    }
  }

  function updateSelectedFiles(values: string[]) {
    const next = values.map(String);
    const newlySelected = next.find((item) => !selectedFiles.includes(item));
    setSelectedFiles(next);
    if (newlySelected) void loadSourceText(newlySelected);
  }

  async function runGenerateOnly() {
    setLoadingGenerate(true);
    try {
      const payload = await generateStrategy(sourceText);
      setGenerationResult(payload);
      onGenerated(payload);
      await refreshTasks();
      message.success("strategy.py generated");
      onOpenGenerated();
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingGenerate(false);
    }
  }

  async function checkCoverage() {
    setLoadingCoverage(true);
    try {
      const payload = await getDataCoverage(symbol, exchange, interval, startDate || undefined, endDate || undefined);
      setCoverage(payload);
      if (String(payload.status || "").toLowerCase() === "covered") {
        message.success("market data is covered");
      } else {
        message.warning(`coverage: ${payload.status || "unchecked"}`);
      }
      return payload;
    } catch (error) {
      message.error(String(error));
      return null;
    } finally {
      setLoadingCoverage(false);
    }
  }

  async function downloadCurrentData() {
    if (!startDate || !endDate) {
      message.warning("start_date and end_date are required");
      return;
    }
    setLoadingDownload(true);
    try {
      await downloadData({ symbol, exchange, interval, start_date: startDate, end_date: endDate });
      await checkCoverage();
      await refreshTasks();
      message.success("market data downloaded");
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingDownload(false);
    }
  }

  async function runResearch() {
    setLoadingResearch(true);
    setResearchError(null);
    try {
      const payload = await createResearch({
        source_text: sourceText,
        symbol,
        exchange,
        interval,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        rate: rate ?? 0.000045,
        slippage: slippage ?? 0.001,
        mode: "real"
      });
      onResearchCreated(payload);
      await refreshTasks();
      if (payload?.error || payload?.backtest?.success === false) {
        setResearchError(payload);
        if (String(payload.error || "").includes("market data coverage")) {
          await checkCoverage();
        }
        message.warning(String(payload.error || "backtest failed"));
      } else {
        message.success("research run created");
        onOpenGenerated();
      }
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingResearch(false);
    }
  }

  async function admitBaseline() {
    const runId = lastResearch?.baseline?.run?.run_id;
    if (!runId) return;
    setLoadingPool(true);
    try {
      const payload = await addToPool(runId, "baseline", `${symbol}.${exchange}`);
      await refreshPool();
      message.success(`pool item: ${payload.pool_item_id}`);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingPool(false);
    }
  }

  return (
    <section className="view is-active">
      <div className="hero-band">
        <div>
          <p className="eyebrow">G&amp;N</p>
          <h2>{zh.launchFlow}</h2>
          <p className="hero-copy">API first research workflow. Current baseline is marked as temporary fallback.</p>
        </div>
        <HeroMetrics lastRun={lastResearch} poolCount={poolCount} taskCount={tasks.length} />
      </div>

      <div className="pipeline-grid">
        <section className="band setup-band">
          <div className="band-head">
            <div>
              <h3>{zh.startConfig}</h3>
              <p className="band-note">File list is placeholder UI; execution uses the text input and FastAPI.</p>
            </div>
          </div>
          <div className="form-grid">
            <section className="field span-2">
              <div className="field-head">
                <span>{zh.sourceFiles}</span>
                <div className="field-actions">
                  <button className="mini-button" type="button" onClick={() => setSelectedFiles(sourceFiles.map((file) => file.name))}>{zh.selectAll}</button>
                  <button className="mini-button" type="button" onClick={() => setSelectedFiles([])}>{zh.clear}</button>
                  <button className="mini-button" type="button" onClick={() => loadSourceText()}>{zh.loadSource}</button>
                </div>
              </div>
              <Checkbox.Group value={selectedFiles} onChange={(values) => updateSelectedFiles(values.map(String))} className="source-checklist" disabled={loadingSources}>
                {sourceFiles.map((file) => (
                  <Checkbox value={file.name} key={file.name}>
                    <strong>{file.name}</strong>
                    <small>{file.size ? `${file.size} bytes` : "imported txt"}</small>
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </section>

            <label className="field span-2">
              <span>{zh.sourceText}</span>
              <Input.TextArea rows={7} value={sourceText} onChange={(event) => setSourceText(event.target.value)} />
            </label>

            <section className="pipeline-config-strip span-2">
              <div className="field-head pipeline-config-head">
                <span>{zh.backtestConfig}</span>
                <span className="meta-inline">Reserved for the real backtest boundary.</span>
              </div>
              <div className="pipeline-config-grid">
                <label className="field span-3">
                  <span>{zh.symbolPoolFile}</span>
                  <Select value={`${symbol}.${exchange}`} options={[{ value: "510300.SSE", label: "ready_etf_12_1m_2023_2024.txt / 510300.SSE" }]} />
                </label>
                <label className="field"><span>{zh.symbol}</span><Input value={symbol} onChange={(event) => setSymbol(event.target.value)} /></label>
                <label className="field"><span>{zh.exchange}</span><Input value={exchange} onChange={(event) => setExchange(event.target.value)} /></label>
                <label className="field"><span>{zh.interval}</span><Input value={interval} onChange={(event) => setInterval(event.target.value)} /></label>
                <label className="field"><span>{zh.rate}</span><InputNumber min={0} step={0.000001} value={rate} onChange={(value) => setRate(typeof value === "number" ? value : null)} /></label>
                <label className="field"><span>{zh.startDate}</span><Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                <label className="field"><span>{zh.endDate}</span><Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
                <label className="field"><span>{zh.slippage}</span><InputNumber min={0} step={0.0001} value={slippage} onChange={(value) => setSlippage(typeof value === "number" ? value : null)} /></label>
              </div>
            </section>

            <section className="coverage-card span-2">
              <div className="coverage-head">
                <div>
                  <span className="summary-label">{zh.dataCoverage}</span>
                  <strong>{symbol}.{exchange} / {interval}</strong>
                </div>
                <span className={coverageStatusClass(coverage?.status)}>{coverage?.status || "unchecked"}</span>
              </div>
              <div className="coverage-grid">
                <div><span>{zh.localRange}</span><strong>{coverage?.local_start || "-"} - {coverage?.local_end || "-"}</strong></div>
                <div><span>{zh.barCount}</span><strong>{coverage?.bar_count ?? "-"}</strong></div>
                <div><span>{zh.missingRanges}</span><strong>{missingRanges.length}</strong></div>
              </div>
              {missingRanges.length > 0 && (
                <div className="coverage-ranges">
                  {missingRanges.slice(0, 3).map((range: any, index: number) => (
                    <span key={`${missingRangeLabel(range)}-${index}`}>{missingRangeLabel(range)}</span>
                  ))}
                </div>
              )}
              <p className="band-note">{zh.dataMissingHint}</p>
              <div className="action-row">
                <Button loading={loadingCoverage} onClick={checkCoverage}>{zh.checkCoverage}</Button>
                <Button loading={loadingDownload} onClick={downloadCurrentData}>{zh.downloadMarketData}</Button>
              </div>
            </section>

            <div className="action-row span-2">
              <Button className="primary-button" loading={loadingResearch} onClick={runResearch}>{zh.startResearch}</Button>
              <Button loading={loadingGenerate} onClick={runGenerateOnly}>{zh.generateOnly}</Button>
            </div>
          </div>
        </section>

        <div className="right-rail">
          <section className="band progress-band">
            <div className="band-head">
              <div><h3>{zh.currentProgress}</h3><p className="band-note">{latestTask?.message || "No active task."}</p></div>
              <span className={statusClass(latestTask?.status)}>{latestTask?.status || "pending"}</span>
            </div>
            <div className="progress-shell">
              <div className="progress-caption">
                <div className="progress-stage-block"><span className="progress-caption-label">stage</span><strong>{latestTask?.task_type || zh.waiting}</strong></div>
                <div className="progress-percent-block"><strong>{Math.round(workflowProgress * 100)}%</strong><span>{completedStageCount} / {pipelineStages.length}</span></div>
              </div>
              <div className="progress-track"><div className="progress-fill" style={{ width: `${Math.round(workflowProgress * 100)}%` }} /></div>
              <div className="job-meta"><span>started_at {formatDate(latestTask?.created_at)}</span><span>duration -</span></div>
            </div>
          </section>

          <section className="stage-grid">
            {pipelineStages.map((stage, index) => (
              <div className={`stage-card ${stage.status}`} key={stage.title}>
                <div className="stage-card-head">
                  <div><p className="stage-index">0{index + 1}</p><h3>{stage.title}</h3></div>
                  <span className={statusClass(stage.status)}>{stage.status}</span>
                </div>
                <p className="stage-copy">{stage.note}</p>
              </div>
            ))}
          </section>

          {researchError && (
            <section className="band error-band">
              <div className="band-head compact">
                <div><h3>{zh.researchFailed}</h3><p className="band-note">{researchError.error || "backtest failed"}</p></div>
                <span className="status-pill status-failed">failed</span>
              </div>
              {missingRanges.length > 0 && (
                <div className="coverage-ranges prominent">
                  {missingRanges.slice(0, 4).map((range: any, index: number) => (
                    <span key={`${missingRangeLabel(range)}-${index}`}>{missingRangeLabel(range)}</span>
                  ))}
                </div>
              )}
              <div className="action-row">
                <Button loading={loadingCoverage} onClick={checkCoverage}>{zh.checkCoverage}</Button>
                <Button loading={loadingDownload} onClick={downloadCurrentData}>{zh.downloadMarketData}</Button>
              </div>
            </section>
          )}

          <section className="band result-band">
            <div className="band-head compact">
              <div><h3>{zh.resultHub}</h3><p className="band-note">Use the latest run or strategy for parameter research.</p></div>
              <div className="action-row">
                <Button onClick={onGoOptimize}>{zh.goOptimize}</Button>
                <Button onClick={onOpenGenerated}>{zh.generate}</Button>
                <Button disabled={!lastResearch?.baseline?.run?.run_id} loading={loadingPool} onClick={admitBaseline}>admit baseline</Button>
              </div>
            </div>
            <div className="viewer-summary-card">
              <div><span className="summary-label">{zh.latestRun}</span><strong>{lastResearch?.baseline?.run?.run_id || "-"}</strong></div>
              <div><span className="summary-label">{zh.latestStrategy}</span><strong>{lastResearch?.generation?.strategy?.strategy_id || generationResult?.strategy?.strategy_id || "-"}</strong></div>
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}

function StrategyGenerationPage({
  lastGenerated,
  lastResearch,
  onBackLaunch,
  onGoOptimize
}: {
  lastGenerated: any;
  lastResearch: any;
  onBackLaunch: () => void;
  onGoOptimize: () => void;
}) {
  const [curveRows, setCurveRows] = useState<any[]>([]);
  const runId = lastResearch?.baseline?.run?.run_id;
  const generationPayload = lastResearch?.generation || lastGenerated;
  const generation = generationPayload?.generation || {};
  const strategy = generationPayload?.strategy || {};
  const metrics = lastResearch?.backtest?.metrics || lastResearch?.baseline?.result?.metrics || lastResearch?.baseline?.variant?.metrics || {};
  const diagnostics = [
    ...(Array.isArray(generation?.diagnostics) ? generation.diagnostics : []),
    ...(Array.isArray(lastResearch?.backtest?.diagnostics) ? lastResearch.backtest.diagnostics : [])
  ];
  const code = generation?.strategy_code || "";
  const normalizedSummary = useMemo(() => curveSummary(curveRows), [curveRows]);

  useEffect(() => {
    let active = true;
    if (!runId) {
      setCurveRows(lastResearch?.backtest?.daily_results || []);
      return;
    }
    getVariantCurve(runId, "baseline")
      .then((payload) => {
        if (active) setCurveRows(payload.data || []);
      })
      .catch((error) => {
        if (active) {
          setCurveRows(lastResearch?.backtest?.daily_results || []);
          message.warning(String(error));
        }
      });
    return () => {
      active = false;
    };
  }, [runId, lastResearch]);

  if (!generationPayload && !lastResearch) {
    return (
      <section className="view is-active">
        <div className="hero-band compact-hero">
          <div><p className="eyebrow">Strategy Generation</p><h2>{zh.generate}</h2><p className="hero-copy">No generated strategy yet.</p></div>
          <div className="action-row"><Button className="primary-button" onClick={onBackLaunch}>{zh.launchFlow}</Button></div>
        </div>
        <section className="band empty-state">Start a workflow first, then generated code and result diagnostics will appear here.</section>
      </section>
    );
  }

  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div>
          <p className="eyebrow">Strategy Generation</p>
          <h2>{zh.generate}</h2>
          <p className="hero-copy">Generated strategy code, diagnostics and baseline result preview.</p>
        </div>
        <div className="action-row">
          <Button onClick={onBackLaunch}>{zh.launchFlow}</Button>
          <Button disabled={!runId} onClick={onGoOptimize}>{zh.goOptimize}</Button>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div><h3>{strategy.strategy_name || generation.strategy_name || generation.class_name || "-"}</h3><p>{strategy.strategy_id || runId || "-"}</p></div>
          <span className={statusClass(lastResearch?.error ? "failed" : generationPayload?.task?.status || "completed")}>{lastResearch?.error ? "failed" : generationPayload?.task?.status || "completed"}</span>
        </div>
        <div className="library-metric-grid">
          <div className="library-metric-card"><span>Sharpe</span><strong>{formatNumber(metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
          <div className="library-metric-card positive"><span>策略收益</span><strong>{normalizedSummary.strategy ? formatReturnPct(normalizedSummary.strategy.totalReturn, 2) : formatPercent(metrics.annual_return ?? metrics.total_return)}</strong></div>
          <div className="library-metric-card"><span>Buy & Hold</span><strong>{normalizedSummary.buyHold ? formatReturnPct(normalizedSummary.buyHold.totalReturn, 2) : "-"}</strong></div>
          <div className={`library-metric-card ${Number(normalizedSummary.excess) >= 0 ? "positive" : "negative"}`}><span>超额收益</span><strong>{normalizedSummary.excess === null ? "-" : formatReturnPct(normalizedSummary.excess, 2)}</strong></div>
          <div className="library-metric-card negative"><span>{zh.drawdown}</span><strong>{formatPercent(metrics.max_drawdown ?? metrics.max_ddpercent)}</strong></div>
          <div className="library-metric-card"><span>run</span><strong>{runId || "-"}</strong></div>
        </div>
      </section>

      {curveRows.length > 0 && (
        <section className="band library-shell">
          <div className="library-section-head"><div><h3>权益曲线对比</h3><p>归一化收益率，策略实线，Buy & Hold 虚线</p></div></div>
          <div className="library-curve-panel"><CurveChart rows={curveRows} /></div>
        </section>
      )}

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>diagnostics</h3><p>{diagnostics.length} records</p></div></div>
        {diagnostics.length ? (
          <div className="diagnostic-list">
            {diagnostics.map((item: any, index: number) => (
              <div className="diagnostic-item" key={`${item.message || "diag"}-${index}`}>
                <span className={statusClass(item.level === "error" ? "failed" : "completed")}>{item.level || "info"}</span>
                <p>{item.message || JSON.stringify(item)}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">No diagnostics returned.</div>
        )}
      </section>

      <section className="band code-band">
        <div className="band-head compact">
          <div><h3>strategy.py</h3><p className="band-note">Returned by strategy generation API.</p></div>
          <span className={statusClass(code ? "completed" : "pending")}>{code ? "completed" : "pending"}</span>
        </div>
        <pre className="code-block">{code || ""}</pre>
      </section>
    </section>
  );
}

function ParameterOptimizationPage({
  lastResearch,
  refreshPool,
  onOpenPool
}: {
  lastResearch: any;
  refreshPool: () => Promise<void>;
  onOpenPool: () => void;
}) {
  const [runs, setRuns] = useState<any[]>([]);
  const [methods, setMethods] = useState<any[]>([]);
  const [runId, setRunId] = useState(lastResearch?.baseline?.run?.run_id || "");
  const [method, setMethod] = useState("manual_grid");
  const [selectedVariant, setSelectedVariant] = useState("baseline");
  const [searchSpace, setSearchSpace] = useState<any>(null);
  const [selectedParams, setSelectedParams] = useState<string[]>([]);
  const [ranges, setRanges] = useState<Record<string, any>>({});
  const [runDetail, setRunDetail] = useState<any>(null);
  const [curveRows, setCurveRows] = useState<any[]>([]);
  const [variantCurves, setVariantCurves] = useState<Record<string, any[]>>({});
  const [visibleCurveKeys, setVisibleCurveKeys] = useState<string[]>([]);
  const [optimizationResult, setOptimizationResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  async function refreshRuns(defaultRunId?: string) {
    const payload = await listRuns();
    const nextRuns = payload.runs || [];
    setRuns(nextRuns);
    const preferred = defaultRunId || runId || lastResearch?.baseline?.run?.run_id || nextRuns[0]?.run_id || "";
    if (preferred && preferred !== runId) setRunId(preferred);
  }

  async function loadRunContext(nextRunId: string, variant = selectedVariant) {
    if (!nextRunId) return;
    const [detail, space] = await Promise.all([
      getRun(nextRunId),
      getOptimizationSearchSpace(nextRunId, "baseline")
    ]);
    const availableVariants = detail.variants?.length ? detail.variants.map((item: any) => item.variant_name) : ["baseline"];
    const curvePayloads = await Promise.all(
      availableVariants.map((name: string) => getVariantCurve(nextRunId, name).then((payload) => [name, payload.data || []] as const).catch(() => [name, []] as const))
    );
    const nextCurves = Object.fromEntries(curvePayloads);
    setRunDetail(detail);
    setSearchSpace(space);
    setVariantCurves(nextCurves);
    setCurveRows(nextCurves[variant] || nextCurves.baseline || []);
    setVisibleCurveKeys([...availableVariants, "buy_hold"]);
    const initialRanges: Record<string, any> = {};
    for (const item of space.parameters || []) {
      initialRanges[item.name] = { low: item.low, high: item.high, step: item.step, type: item.type };
    }
    setRanges(initialRanges);
    setSelectedParams([]);
  }

  useEffect(() => {
    getOptimizationMethods().then((payload) => setMethods(payload.methods || [])).catch((error) => message.error(String(error)));
    refreshRuns(lastResearch?.baseline?.run?.run_id).catch((error) => message.error(String(error)));
  }, [lastResearch?.baseline?.run?.run_id]);

  useEffect(() => {
    if (!runId) return;
    loadRunContext(runId, selectedVariant).catch((error) => message.error(String(error)));
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    const cached = variantCurves[selectedVariant];
    if (cached) {
      setCurveRows(cached);
      return;
    }
    getVariantCurve(runId, selectedVariant)
      .then((payload) => {
        setCurveRows(payload.data || []);
        setVariantCurves((current) => ({ ...current, [selectedVariant]: payload.data || [] }));
      })
      .catch(() => setCurveRows([]));
  }, [selectedVariant, runId, variantCurves]);

  const currentRun = runs.find((item) => item.run_id === runId);
  const variants = runDetail?.variants || [];
  const curveVariantNames = useMemo(() => Object.keys(variantCurves), [variantCurves]);
  const activeMethod = methods.find((item) => item.method === method);
  const variantMetrics = useMemo(() => curveSummary(curveRows), [curveRows]);
  const totalGridCount = useMemo(() => {
    if (!selectedParams.length) return 0;
    return selectedParams.reduce((product, name) => {
      const spec = ranges[name] || {};
      const low = Number(spec.low);
      const high = Number(spec.high);
      const step = Number(spec.step);
      if (!Number.isFinite(low) || !Number.isFinite(high) || !Number.isFinite(step) || step <= 0 || high < low) return 0;
      return product * Math.max(1, Math.floor((high - low) / step + 1.0000001));
    }, 1);
  }, [ranges, selectedParams]);

  function updateRange(name: string, key: string, value: number | null) {
    setRanges((current) => ({ ...current, [name]: { ...(current[name] || {}), [key]: value } }));
  }

  async function submitOptimization() {
    if (!runId) {
      message.error("请先选择 run。");
      return;
    }
    const selected = method === "auto" && selectedParams.length === 0
      ? (searchSpace?.parameters || []).map((item: any) => item.name)
      : selectedParams;
    if (!selected.length) {
      message.error("请至少选择一个参数。");
      return;
    }
    setLoading(true);
    try {
      const payload = await runOptimization({
        run_id: runId,
        variant_name: "baseline",
        method,
        selected_parameters: selected,
        parameter_ranges: Object.fromEntries(selected.map((name: string) => [name, ranges[name]])),
        objective: "sharpe",
        max_trials: 200
      });
      if (payload.error) {
        message.error(payload.error);
      } else {
        message.success("参数优化完成");
        setOptimizationResult(payload);
        setSelectedVariant(payload.selected_variant || activeMethod?.variant_name || "manual_grid");
        await loadRunContext(runId, payload.selected_variant || "manual_grid");
      }
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoading(false);
    }
  }

  async function addSelectedVariantToPool() {
    if (!runId) return;
    try {
      await addToPool(runId, selectedVariant, currentRun?.vt_symbol);
      await refreshPool();
      message.success("已加入策略池");
      onOpenPool();
    } catch (error) {
      message.error(String(error));
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
    { title: zh.paramName, dataIndex: "name", render: (value, record) => <div className="param-name-cell"><strong>{value}</strong><span>{record.role}</span></div> },
    { title: zh.currentValue, dataIndex: "current", render: (value) => String(value) },
    { title: "low", dataIndex: "low", render: (_, record) => <InputNumber value={ranges[record.name]?.low} step="any" onChange={(value) => updateRange(record.name, "low", value)} /> },
    { title: "high", dataIndex: "high", render: (_, record) => <InputNumber value={ranges[record.name]?.high} step="any" onChange={(value) => updateRange(record.name, "high", value)} /> },
    { title: "step", dataIndex: "step", render: (_, record) => <InputNumber value={ranges[record.name]?.step} step="any" onChange={(value) => updateRange(record.name, "step", value)} /> },
    { title: "type", dataIndex: "type" }
  ];

  const resultColumns: ColumnsType<any> = [
    { title: "rank", dataIndex: "rank", width: 72 },
    { title: "label", dataIndex: "label" },
    { title: "score", dataIndex: "score", render: (value) => formatNumber(value, 4) },
    { title: "success", dataIndex: "success", render: (value) => <span className={statusClass(value ? "completed" : "failed")}>{String(value)}</span> },
    { title: "parameters", dataIndex: "parameters", render: (value) => <code>{JSON.stringify(value || {})}</code> }
  ];

  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div><p className="eyebrow">Parameter Lab</p><h2>{zh.optimize}</h2><p className="hero-copy">先选择已经生成的 run 和标的，再选择人工调参或自动优化。</p></div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{runs.length}</div><div className="metric-label">runs</div></div>
          <div className="metric-tile"><div className="metric-value">{searchSpace?.parameters?.length || 0}</div><div className="metric-label">params</div></div>
          <div className="metric-tile"><div className="metric-value">{variants.length}</div><div className="metric-label">variants</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>{zh.currentSelection}</h3><p>选择 run、标的和优化模式。</p></div><span className={statusClass(runId ? "completed" : "pending")}>{runId ? "ready" : "pending"}</span></div>
        <div className="form-grid optimization-form-grid">
          <label className="field">
            <span>运行版本</span>
            <Select value={runId || undefined} onChange={(value) => { setRunId(value); setSelectedVariant("baseline"); }} options={runs.map((item) => ({ value: item.run_id, label: `${item.strategy_name || item.strategy_id} | ${item.vt_symbol || "-"} | ${formatDate(item.created_at)}` }))} />
          </label>
          <label className="field">
            <span>标的</span>
            <Select value={currentRun?.vt_symbol || searchSpace?.vt_symbol || undefined} options={[{ value: currentRun?.vt_symbol || searchSpace?.vt_symbol || "", label: currentRun?.vt_symbol || searchSpace?.vt_symbol || "-" }]} />
          </label>
          <label className="field">
            <span>优化模式</span>
            <Select value={method} onChange={setMethod} options={methods.map((item) => ({ value: item.method, label: item.label }))} />
          </label>
          <label className="field">
            <span>查看版本</span>
            <Select value={selectedVariant} onChange={setSelectedVariant} options={(variants.length ? variants : [{ variant_name: "baseline" }]).map((item: any) => ({ value: item.variant_name, label: item.variant_name }))} />
          </label>
        </div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>权益曲线对比</h3><p>勾选当前 run 下的 variant 和 Buy & Hold，同时查看归一化收益率。</p></div></div>
        <Checkbox.Group
          className="curve-toggle-group"
          value={visibleCurveKeys}
          onChange={(values) => setVisibleCurveKeys(values.map(String))}
          options={[
            ...curveVariantNames.map((name) => ({ label: name, value: name })),
            { label: "Buy & Hold", value: "buy_hold" }
          ]}
        />
        {visibleCurveKeys.length > 0 && curveVariantNames.length > 0 ? <div className="library-curve-panel"><MultiVariantCurveChart curves={variantCurves} visibleKeys={visibleCurveKeys} /></div> : <div className="empty-state">当前 run 暂无可展示曲线。</div>}
        <div className="library-metric-grid parameter-metric-grid">
          <div className="library-metric-card"><span>策略收益</span><strong>{variantMetrics.strategy ? formatReturnPct(variantMetrics.strategy.totalReturn, 2) : "-"}</strong></div>
          <div className="library-metric-card"><span>Buy & Hold</span><strong>{variantMetrics.buyHold ? formatReturnPct(variantMetrics.buyHold.totalReturn, 2) : "-"}</strong></div>
          <div className={`library-metric-card ${Number(variantMetrics.excess) >= 0 ? "positive" : "negative"}`}><span>超额收益</span><strong>{variantMetrics.excess === null ? "-" : formatReturnPct(variantMetrics.excess, 2)}</strong></div>
        </div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>{method === "auto" ? "自动优化" : "人工调参"}</h3><p>{activeMethod?.description || "按参数范围运行优化。"}</p></div><span className="status-pill status-running">Grid {totalGridCount}</span></div>
        {method === "auto" && <div className="detail-grid optimizer-preview">{(searchSpace?.parameters || []).map((item: any) => <div key={item.name}><div className="summary-label">{item.name}</div><div className="summary-value">{item.type}</div><div className="meta-inline">{item.low} {"->"} {item.high} step {item.step}</div></div>)}</div>}
        <Table rowKey="name" columns={parameterColumns} dataSource={searchSpace?.parameters || []} pagination={false} className="workbench-table parameter-table" />
        <div className="action-row"><Button type="primary" loading={loading} disabled={!runId || (method === "manual_grid" && !selectedParams.length)} onClick={submitOptimization}>{method === "auto" ? "运行自动优化" : "运行人工参数对比"}</Button></div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>绩效明细</h3><p>参数列展示相对 baseline 发生变化的项。</p></div></div>
        <Table rowKey={(record) => `${record.rank}-${record.label}`} columns={resultColumns} dataSource={optimizationResult?.grid_summary || []} pagination={{ pageSize: 8 }} className="workbench-table" />
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>确认入池</h3><p>确认后的 variant 会进入策略池。</p></div><Button type="primary" disabled={!runId || selectedVariant === "baseline"} onClick={addSelectedVariantToPool}>确认入池</Button></div>
        <div className="summary-compact-grid">
          <div className="viewer-summary-card"><span className="summary-label">run</span><strong>{runId || "-"}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">variant</span><strong>{selectedVariant}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">optimizer</span><strong>{optimizationResult?.optimization?.optimizer_name || "-"}</strong></div>
        </div>
      </section>
    </section>
  );
}

function PoolPage({ poolItems, refreshPool }: { poolItems: any[]; refreshPool: () => Promise<void> }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [searchText, setSearchText] = useState("");
  const [selectionMode, setSelectionMode] = useState("all");
  const [selectedDetailId, setSelectedDetailId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [comparison, setComparison] = useState<any>({ items: [], benchmark: { curve: [] }, diagnostics: [] });
  const [loading, setLoading] = useState(false);

  function itemTags(item: any): string[] {
    try {
      const parsed = JSON.parse(item?.tags || "[]");
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch {
      return [];
    }
  }

  function poolItemLabel(item: any) {
    return String(item?.strategy_name || item?.strategy_id || "strategy");
  }

  function compareItemLabel(item: any) {
    return `${item.strategy_name || item.strategy_id || "strategy"} | ${item.variant_name || "-"} | ${item.vt_symbol || "-"}`;
  }

  function metricValue(metrics: any, ...names: string[]) {
    for (const name of names) {
      const value = Number(metrics?.[name]);
      if (Number.isFinite(value)) return value;
    }
    return null;
  }

  function excessReturn(item: any) {
    const strategy = metricValue(item?.metrics || {}, "total_return", "annual_return");
    const benchmark = comparison?.benchmark?.curve?.length ? Number(comparison.benchmark.curve[comparison.benchmark.curve.length - 1]?.value) : NaN;
    if (strategy === null || !Number.isFinite(benchmark)) return null;
    return strategy - benchmark;
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
          item.strategy_name,
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
      return records.slice().sort((a, b) => Number(b.annual_return ?? -Infinity) - Number(a.annual_return ?? -Infinity)).slice(0, 5);
    }
    if (mode === "recent") {
      return records.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 5);
    }
    return records;
  }

  function applyPreset(mode: string) {
    setSelectionMode(mode);
    setSelectedIds(presetItems(mode).map((item) => String(item.pool_item_id)));
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
    if (!kept.length && candidateItems.length) {
      setSelectedIds(presetItems(selectionMode, candidateItems).map((item) => String(item.pool_item_id)));
    }
  }, [candidateItems, selectedIds, selectionMode]);

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

  const compareItems = comparison?.items || [];
  const compareCurves = useMemo(() => Object.fromEntries(compareItems.map((item: any) => [item.pool_item_id, item.curve || []])), [compareItems]);
  const compareLabels = useMemo(() => Object.fromEntries(compareItems.map((item: any) => [item.pool_item_id, compareItemLabel(item)])), [compareItems]);
  const benchmarkSeries = useMemo<NormalizedCurveSeries | null>(() => {
    const points = (comparison?.benchmark?.curve || [])
      .map((point: any) => ({ date: String(point.date || ""), value: Number(point.value) }))
      .filter((point: NormalizedCurvePoint) => point.date && Number.isFinite(point.value));
    if (!points.length) return null;
    return {
      key: "buy_hold",
      label: comparison?.benchmark?.label || "Buy & Hold",
      type: "benchmark",
      points,
      totalReturn: points[points.length - 1]?.value ?? 0
    };
  }, [comparison]);

  const comparisonColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "策略",
        dataIndex: "strategy_name",
        render: (value, record) => (
          <button className="link-cell strategy-pool-name-cell" type="button" onClick={() => openItem(record)}>
            <strong>{value || record.strategy_id}</strong>
            <span>{record.source_run_id || record.pool_item_id}</span>
          </button>
        )
      },
      { title: "入池版本", dataIndex: "variant_name", render: (value) => value || "-" },
      { title: "总收益", render: (_, record) => formatPercent(metricValue(record.metrics, "total_return", "annual_return")) },
      { title: "年化", render: (_, record) => formatPercent(metricValue(record.metrics, "annual_return", "total_return")) },
      { title: "Sharpe", render: (_, record) => formatNumber(metricValue(record.metrics, "sharpe", "sharpe_ratio")) },
      { title: "最大回撤", render: (_, record) => formatPercent(metricValue(record.metrics, "max_drawdown", "max_ddpercent")) },
      { title: "B&H", render: () => formatReturnPct(benchmarkSeries?.totalReturn) },
      { title: "超额", render: (_, record) => formatReturnPct(excessReturn(record)) }
    ],
    [benchmarkSeries, comparison]
  );

  const metrics = detail?.result?.metrics || detail?.result || {};
  const params = detail?.config?.parameters || detail?.manifest?.parameters || detail?.result?.params || {};
  const trades = detail?.trades?.data || [];
  const tradeColumns = (detail?.trades?.columns || Object.keys(trades[0] || {})).slice(0, 8).map((column: string) => ({ title: column, dataIndex: column }));

  return (
    <section className="view is-active">
      <div className="hero-band library-hero-band">
        <div><p className="eyebrow">Strategy Pool</p><h2>{zh.pool}</h2><p className="hero-copy">确认入池后的策略快照，在这里做筛选、曲线对比和绩效回看。</p></div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{poolItems.length}</div><div className="metric-label">\u5165\u6c60\u7ed3\u679c</div></div>
          <div className="metric-tile"><div className="metric-value">{new Set(poolItems.map((item) => item.vt_symbol).filter(Boolean)).size}</div><div className="metric-label">\u6807\u7684\u6570\u91cf</div></div>
          <div className="metric-tile"><div className="metric-value">{latestCreatedAt ? formatDate(latestCreatedAt).slice(5, 16) : "-"}</div><div className="metric-label">最近入池</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div><h3>策略池筛选</h3><p>选择标的、搜索策略，并勾选要对比的入池版本。</p></div>
          <Button onClick={() => refreshPool().catch((error) => message.error(String(error)))}>{zh.refresh}</Button>
        </div>
        <div className="strategy-pool-filter-grid">
          <label className="field library-folder-field">
            <span>标的</span>
            <Select value={selectedSymbol || undefined} onChange={(value) => { setSelectedSymbol(value); setSelectedIds([]); }} options={symbols.map((item) => ({ value: item, label: item }))} />
          </label>
          <label className="field library-folder-field">
            <span>策略搜索</span>
            <Input value={searchText} onChange={(event) => { setSearchText(event.target.value); setSelectedIds([]); }} placeholder="输入策略 / run / variant / tag" />
          </label>
          <div className="field library-folder-field strategy-pool-preset-field">
            <span>快捷选择</span>
            <div className="strategy-pool-preset-buttons">
              {[
                ["all", "全部策略"],
                ["top_sharpe", "夏普前 5"],
                ["top_excess", "超额前 5"],
                ["recent", "最近入池"]
              ].map(([key, label]) => <button type="button" key={key} className={selectionMode === key ? "is-active" : ""} onClick={() => applyPreset(key)}>{label}</button>)}
            </div>
          </div>
        </div>
        <div className="strategy-pool-date-action">
          <Button type="primary" disabled>回测到今天</Button>
          <span>重新回测尚未接入，当前展示入池快照曲线。</span>
        </div>
        <div className="strategy-pool-check-grid">
          {candidateItems.length ? candidateItems.map((item) => {
            const id = String(item.pool_item_id);
            return (
              <label className="strategy-pool-check" key={id}>
                <Checkbox checked={selectedIds.includes(id)} onChange={(event) => setSelectedIds((current) => event.target.checked ? Array.from(new Set([...current, id])) : current.filter((value) => value !== id))} />
                <span>
                  <strong>{poolItemLabel(item)}</strong>
                  <small>{item.vt_symbol || "-"} | {formatPercent(item.annual_return)} | Sharpe {formatNumber(item.sharpe)}</small>
                </span>
              </label>
            );
          }) : <div className="empty-state strategy-pool-empty">当前筛选没有可展示的入池策略。</div>}
        </div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>策略对比曲线</h3><p>已选择 {selectedIds.length} 条策略，展示归一化曲线和 Buy & Hold。</p></div><span className={statusClass(compareItems.length ? "completed" : "pending")}>{compareItems.length ? "ready" : "empty"}</span></div>
        {compareItems.length ? <div className="library-curve-panel"><MultiVariantCurveChart curves={compareCurves} visibleKeys={[...selectedIds, "buy_hold"]} labels={compareLabels} benchmark={benchmarkSeries} /></div> : <div className="empty-state">请先勾选策略。</div>}
        {(comparison?.diagnostics || []).length > 0 && <div className="diagnostic-list">{comparison.diagnostics.map((item: any, index: number) => <Tag color="orange" key={`${item.message}-${index}`}>{item.message}</Tag>)}</div>}
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>绩效明细</h3><p>对比当前勾选策略的核心绩效。</p></div></div>
        <div className="library-table-wrap">
          <Table rowKey="pool_item_id" columns={comparisonColumns} dataSource={compareItems} pagination={{ pageSize: 8 }} loading={loading} className="workbench-table strategy-pool-detail-table" rowClassName={(record) => (record.pool_item_id === selectedDetailId ? "is-selected" : "")} />
        </div>
      </section>

      {detail && (
        <section className="band library-shell">
          <div className="library-section-head"><div><h3>{detail.pool_item?.strategy_name || zh.strategyName}</h3><p>{detail.pool_item?.pool_item_id}</p></div><span className="status-pill status-completed">completed</span></div>
          <div className="library-metric-grid">
            <div className="library-metric-card"><span>Sharpe</span><strong>{formatNumber(detail.pool_item?.sharpe ?? metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card positive"><span>{zh.return}</span><strong>{formatPercent(detail.pool_item?.annual_return ?? metrics.annual_return ?? metrics.total_return)}</strong></div>
            <div className="library-metric-card negative"><span>{zh.drawdown}</span><strong>{formatPercent(detail.pool_item?.max_drawdown ?? metrics.max_drawdown ?? metrics.max_ddpercent)}</strong></div>
            <div className="library-metric-card"><span>Calmar</span><strong>{formatNumber(detail.pool_item?.calmar ?? metrics.calmar)}</strong></div>
          </div>
          <div className="detail-grid">
            <div className="viewer-summary-card"><span className="summary-label">params</span><pre className="mini-code">{JSON.stringify(params, null, 2)}</pre></div>
            <div className="viewer-summary-card"><span className="summary-label">{zh.notes}</span><p className="notes-text">{detail.notes || "-"}</p></div>
          </div>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.trades}</h3></div></div><Table rowKey={(_, index) => String(index)} dataSource={trades} pagination={{ pageSize: 6 }} className="workbench-table" columns={tradeColumns} /></section>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.code}</h3></div></div><pre className="code-block">{detail.strategy_code || ""}</pre></section>
        </section>
      )}
    </section>
  );
}

function App() {
  const [page, setPage] = useState<PageKey>("launch");
  const [tasks, setTasks] = useState<any[]>([]);
  const [poolItems, setPoolItems] = useState<any[]>([]);
  const [lastResearch, setLastResearch] = useState<any>(null);
  const [lastGenerated, setLastGenerated] = useState<any>(null);

  async function refreshTasks() {
    const payload = await listTasks();
    setTasks(payload.tasks || []);
  }

  async function refreshPool() {
    const payload = await listPool();
    setPoolItems(payload.items || []);
  }

  useEffect(() => {
    refreshTasks().catch((error) => message.error(String(error)));
    refreshPool().catch((error) => message.error(String(error)));
  }, []);

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#17b8b1", borderRadius: 8, fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" } }}>
      <div className="shell">
        <Sidebar page={page} onPageChange={setPage} tasks={tasks} onRefreshTasks={refreshTasks} />
        <main className="workspace">
          {page === "launch" && (
            <LaunchFlowPage
              tasks={tasks}
              poolCount={poolItems.length}
              lastResearch={lastResearch}
              onResearchCreated={(payload) => {
                setLastResearch(payload);
                refreshPool().catch((error) => message.error(String(error)));
              }}
              onGenerated={setLastGenerated}
              onOpenGenerated={() => setPage("generate")}
              onGoOptimize={() => setPage("optimize")}
              refreshPool={refreshPool}
              refreshTasks={refreshTasks}
            />
          )}
          {page === "generate" && <StrategyGenerationPage lastGenerated={lastGenerated} lastResearch={lastResearch} onBackLaunch={() => setPage("launch")} onGoOptimize={() => setPage("optimize")} />}
          {page === "optimize" && <ParameterOptimizationPage lastResearch={lastResearch} refreshPool={refreshPool} onOpenPool={() => setPage("pool")} />}
          {page === "pool" && <PoolPage poolItems={poolItems} refreshPool={refreshPool} />}
        </main>
      </div>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
