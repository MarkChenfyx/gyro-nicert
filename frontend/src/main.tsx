import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { Button, Checkbox, ConfigProvider, Drawer, Input, InputNumber, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import * as echarts from "echarts";
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
  rerunPool,
  runOptimization,
  updateNaturalLanguageSource
} from "./api";
import "./styles.css";

type PageKey = "launch" | "generate" | "optimize" | "pool";
const PAGE_STORAGE_KEY = "gyro_nicert.active_page";
const OPTIMIZE_DRAFT_STORAGE_KEY = "gyro_nicert.optimize_draft";
const BENCHMARK_CURVE_COLOR = "#64748b";

type TaskStatusValue = "queued" | "running" | "completed" | "failed" | "cancelled";
type TaskView = "all" | "active" | "failed" | "completed" | "archived";

type WorkbenchTask = {
  task_id: string;
  task_type: string;
  status: TaskStatusValue | string;
  progress: number;
  message?: string;
  error?: string;
  related_strategy_id?: string;
  related_run_id?: string;
  related_pool_item_id?: string;
  source_filename?: string;
  archived_at?: string;
  created_at: string;
  updated_at: string;
};

const TASK_TYPE_LABELS: Record<string, string> = {
  strategy_generation: "策略生成",
  backtest: "基线回测",
  optimization: "参数优化",
  data_download: "行情下载",
  pool_add: "加入策略池",
  pool_rebuild: "策略池重跑"
};

const TASK_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  ready: "就绪"
};

function taskTypeLabel(taskType?: string) {
  return TASK_TYPE_LABELS[String(taskType || "")] || String(taskType || "未知任务");
}

function taskDisplayLabel(task: WorkbenchTask) {
  const relatedSourceName = String(task.source_filename || "").trim();
  if (relatedSourceName && task.task_type === "backtest") return `${relatedSourceName} · 基线回测`;
  if (relatedSourceName && task.task_type === "strategy_generation") return `${relatedSourceName} · 策略生成`;
  if (task.task_type !== "strategy_generation") return taskTypeLabel(task.task_type);
  const message = String(task.message || "");
  const separator = message.indexOf(" · ");
  const sourceName = separator > 0 ? message.slice(0, separator).trim() : "";
  return sourceName ? `${sourceName} · 策略生成` : taskTypeLabel(task.task_type);
}

function taskSummary(task: WorkbenchTask) {
  const status = String(task.status || "").toLowerCase();
  if (status === "failed") return task.error || task.message || task.task_id;
  if (["running", "queued"].includes(status)) return task.message || task.task_id;
  return "任务已完成";
}

function taskStatusLabel(status?: string) {
  return TASK_STATUS_LABELS[String(status || "").toLowerCase()] || String(status || "未知");
}

function taskProgress(task?: WorkbenchTask | null) {
  return Math.max(0, Math.min(100, Number(task?.progress || 0) * 100));
}

function taskTargetPage(task: WorkbenchTask): PageKey {
  if (task.related_pool_item_id || task.task_type === "pool_add" || task.task_type === "pool_rebuild") return "pool";
  if (task.task_type === "optimization") return "optimize";
  if (task.related_run_id && task.status !== "failed") return "generate";
  return "launch";
}

function elapsedLabel(task: WorkbenchTask) {
  const start = new Date(task.created_at).getTime();
  const end = ["running", "queued"].includes(String(task.status)) ? Date.now() : new Date(task.updated_at).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "-";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分 ${seconds % 60} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

function taskDateGroup(task: WorkbenchTask) {
  const value = new Date(task.created_at);
  if (Number.isNaN(value.getTime())) return "更早";
  const now = new Date();
  const dateKey = value.toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
  const todayKey = now.toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
  const yesterday = new Date(now.getTime() - 86400000).toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
  if (dateKey === todayKey) return "今天";
  if (dateKey === yesterday) return "昨天";
  return "更早";
}

function isPageKey(value: string): value is PageKey {
  return value === "launch" || value === "generate" || value === "optimize" || value === "pool";
}

function loadInitialPage(): PageKey {
  if (typeof window === "undefined") return "launch";
  const stored = window.localStorage.getItem(PAGE_STORAGE_KEY);
  return stored && isPageKey(stored) ? stored : "launch";
}

function loadOptimizeDraft(): Record<string, any> {
  if (typeof window === "undefined") return {};
  try {
    const stored = window.localStorage.getItem(OPTIMIZE_DRAFT_STORAGE_KEY);
    if (!stored) return {};
    const parsed = JSON.parse(stored);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

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
  inputMode: "\u8f93\u5165\u65b9\u5f0f",
  naturalLanguageMode: "\u81ea\u7136\u8bed\u8a00\u751f\u6210",
  manualCodeMode: "\u76f4\u63a5\u7c98\u8d34\u7b56\u7565\u4ee3\u7801",
  localCodeMode: "\u4ece\u672c\u5730\u4e0a\u4f20\u7b56\u7565\u4ee3\u7801",
  backtestConfig: "\u53c2\u6570\u8bbe\u7f6e",
  symbol: "\u6807\u7684 / \u4ea4\u6613\u6240",
  interval: "\u5468\u671f",
  rate: "\u624b\u7eed\u8d39\u7387",
  startDate: "\u5f00\u59cb\u65e5\u671f",
  endDate: "\u7ed3\u675f\u65e5\u671f",
  slippage: "\u6ed1\u70b9",
  researchFailed: "\u56de\u6d4b\u672a\u5b8c\u6210",
  newSource: "\u65b0\u5efa",
  save: "\u4fdd\u5b58",
  cancel: "\u53d6\u6d88",
  sourceFilename: "\u6587\u4ef6\u540d",
  strategyNameInput: "\u7b56\u7565\u540d\u79f0",
  strategyCodeInput: "strategy.py \u4ee3\u7801",
  launchErrorTitle: "\u542f\u52a8\u5931\u8d25",
  startResearch: "\u542f\u52a8\u7814\u7a76\u6d41\u7a0b",
  goOptimize: "\u53bb\u53c2\u6570\u4f18\u5316",
  parameterEngineNotConnected: "\u53c2\u6570\u4f18\u5316\u5f15\u64ce\u5c1a\u672a\u63a5\u5165\u3002\u6b64\u5904\u4e0d\u4f7f\u7528 mock \u5047\u88c5\u771f\u5b9e\u4f18\u5316\u3002",
  currentSelection: "\u5f53\u524d\u9009\u62e9",
  paramName: "\u53c2\u6570\u540d",
  currentValue: "\u5f53\u524d\u503c",
  startOptimization: "\u542f\u52a8\u4f18\u5316",
  poolList: "\u7b56\u7565\u6c60\u5217\u8868",
  strategyName: "\u7b56\u7565\u540d",
  sharpe: "夏普比率",
  return: "\u6536\u76ca",
  drawdown: "\u6700\u5927\u56de\u64a4",
  createdAt: "\u521b\u5efa\u65f6\u95f4",
  tags: "标签",
  action: "\u64cd\u4f5c",
  open: "\u67e5\u770b",
  notes: "备注",
  curve: "曲线图",
  trades: "成交记录",
  code: "策略代码"
};

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

type LocalStrategyFile = {
  name: string;
  relativePath: string;
  code: string;
};

type WorkflowUiState = {
  stageKey: "idle" | "generation" | "download" | "backtest";
  message: string;
  startedAt: string;
  isRunning: boolean;
  downloadDiagnostics: any;
  error: any;
};

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

function strategyFamily(item: any) {
  const family = String(item?.strategy_family || "").trim();
  if (family) return family;
  const sourceFilename = String(item?.source_filename || "").trim();
  if (sourceFilename.endsWith(".txt")) return sourceFilename.slice(0, -4);
  return "";
}

function strategyVersion(item: any) {
  return String(item?.strategy_version || "").trim();
}

function strategyLabel(item: any) {
  const family = strategyFamily(item);
  const version = strategyVersion(item);
  if (family && version) return `${family} | ${version}`;
  return String(item?.strategy_name || item?.strategy_id || "-");
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

function formatParameterValue(value: unknown) {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6)));
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value === null || value === undefined) return "-";
  return String(value);
}

function summarizeParameters(parameters: unknown) {
  if (parameters && typeof parameters === "object" && !Array.isArray(parameters)) {
    const entries = Object.entries(parameters as Record<string, unknown>);
    if (!entries.length) return "-";
    return entries.map(([key, value]) => `${key}=${formatParameterValue(value)}`).join(" · ");
  }
  const text = String(parameters || "").trim();
  return text || "-";
}

function statusClass(status?: string) {
  const normalized = String(status || "pending").toLowerCase();
  if (["succeeded", "completed", "optimized"].includes(normalized)) return "status-pill status-completed";
  if (["running", "queued"].includes(normalized)) return "status-pill status-running";
  if (normalized === "failed") return "status-pill status-failed";
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

function parseLaunchVtSymbol(value: string) {
  const normalized = String(value || "").trim().toUpperCase().replace(/\s+/g, "");
  const parts = normalized.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  return {
    vtSymbol: `${parts[0]}.${parts[1]}`,
    symbol: parts[0],
    exchange: parts[1],
  };
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
  drawdownPoints: NormalizedCurvePoint[];
  totalReturn: number;
  maxDrawdown: number;
  basis?: "pnl" | "price";
};

function buildDrawdownSeries(points: NormalizedCurvePoint[]): NormalizedCurvePoint[] {
  let peak = 0;
  return points.map((point) => {
    peak = Math.max(peak, point.value);
    return { date: point.date, value: Math.min(0, point.value - peak) };
  });
}

function finiteNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function drawdownMetricValue(metrics: any): number | null {
  return finiteNumber(metrics?.max_drawdown_pct)
    ?? finiteNumber(metrics?.max_ddpercent)
    ?? finiteNumber(metrics?.max_drawdown);
}

function rowDate(row: any): string {
  return String(row?.date || row?.datetime || row?.trading_day || "");
}

function normalizeDateKey(value?: string): string {
  const text = String(value || "").trim();
  if (!text) return "";
  const matched = text.match(/\d{4}[-/]\d{2}[-/]\d{2}/);
  if (matched) return matched[0].replace(/\//g, "-");
  return text.includes("T") ? text.slice(0, 10) : text.slice(0, 10);
}

function clampDateRange(rows: any[], startDate: string, endDate: string) {
  const normalizedStart = normalizeDateKey(startDate);
  const normalizedEnd = normalizeDateKey(endDate);
  if (!normalizedStart && !normalizedEnd) return rows;
  return rows.filter((row) => {
    const current = normalizeDateKey(rowDate(row));
    if (!current) return false;
    if (normalizedStart && current < normalizedStart) return false;
    if (normalizedEnd && current > normalizedEnd) return false;
    return true;
  });
}

function shiftDate(value: string, months = 0, years = 0): string {
  const normalized = normalizeDateKey(value);
  if (!normalized) return "";
  const next = new Date(`${normalized}T00:00:00`);
  if (Number.isNaN(next.getTime())) return normalized;
  if (months) next.setMonth(next.getMonth() + months);
  if (years) next.setFullYear(next.getFullYear() + years);
  return next.toISOString().slice(0, 10);
}

function curveDateBoundsForRows(rows: any[]): { min: string; max: string } {
  const dates = rows.map((row) => normalizeDateKey(rowDate(row))).filter(Boolean).sort();
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
  const dataMax = dates[dates.length - 1] || "";
  return { min: dates[0] || "", max: dataMax > today ? dataMax : today };
}

function shortcutDateRange(bounds: { min: string; max: string }, range: "3m" | "6m" | "1y" | "all") {
  if (!bounds.min || !bounds.max) return { start: "", end: "" };
  if (range === "all") return { start: bounds.min, end: bounds.max };
  const requestedStart = range === "3m"
    ? shiftDate(bounds.max, -3)
    : range === "6m"
      ? shiftDate(bounds.max, -6)
      : shiftDate(bounds.max, 0, -1);
  return { start: requestedStart < bounds.min ? bounds.min : requestedStart, end: bounds.max };
}

function valueFromKeys(row: any, keys: string[]): number | null {
  for (const key of keys) {
    const value = finiteNumber(row?.[key]);
    if (value !== null) return value;
  }
  return null;
}

function closeValue(row: any): number | null {
  return valueFromKeys(row, ["close_price", "close", "price"]);
}

function referenceClose(row: any, previousClose: number | null): number | null {
  if (previousClose !== null && previousClose > 0) return previousClose;
  const currentClose = closeValue(row);
  const preClose = valueFromKeys(row, ["pre_close", "prev_close", "previous_close"]);
  if (preClose !== null && preClose > 0 && currentClose !== null && currentClose > 0) {
    const ratio = preClose / currentClose;
    if (ratio > 0.5 && ratio < 1.5) return preClose;
  }
  return currentClose !== null && currentClose > 0 ? currentClose : null;
}

function cumulativeStrategySeries(rows: any[]): NormalizedCurvePoint[] {
  let previousClose: number | null = null;
  let cumulativeReturn = 0;
  return rows
    .map((row) => {
      const currentClose = closeValue(row);
      const denominator = referenceClose(row, previousClose);
      const netPnl = finiteNumber(row?.net_pnl) ?? 0;
      if (currentClose !== null && currentClose > 0) previousClose = currentClose;
      if (denominator === null || denominator <= 0) return null;
      cumulativeReturn += (netPnl / denominator) * 100;
      return {
        date: rowDate(row),
        value: cumulativeReturn
      };
    })
    .filter((item): item is NormalizedCurvePoint => Boolean(item));
}

function cumulativeBuyHoldSeries(rows: any[]): NormalizedCurvePoint[] {
  let previousClose: number | null = null;
  let cumulativeReturn = 0;
  return rows
    .map((row) => {
      const currentClose = closeValue(row);
      const denominator = referenceClose(row, previousClose);
      if (currentClose !== null && currentClose > 0) previousClose = currentClose;
      if (currentClose === null || currentClose <= 0 || denominator === null || denominator <= 0) return null;
      cumulativeReturn += ((currentClose / denominator) - 1) * 100;
      return {
        date: rowDate(row),
        value: cumulativeReturn
      };
    })
    .filter((item): item is NormalizedCurvePoint => Boolean(item));
}

function buildStrategyCurve(rows: any[]): NormalizedCurveSeries | null {
  const points = cumulativeStrategySeries(rows);
  if (!points.length) return null;
  const drawdownPoints = buildDrawdownSeries(points);
  return {
    key: "strategy",
    label: "策略累计收益",
    type: "strategy",
    points,
    drawdownPoints,
    totalReturn: points[points.length - 1]?.value ?? 0,
    maxDrawdown: Math.min(...drawdownPoints.map((point) => point.value), 0),
    basis: "pnl"
  };
}

function buildNormalizedCurveSeries(rows: any[]): NormalizedCurveSeries[] {
  const strategyCurve = buildStrategyCurve(rows);
  const buyHoldPoints = cumulativeBuyHoldSeries(rows);
  const series: NormalizedCurveSeries[] = [];
  if (strategyCurve) series.push(strategyCurve);
  if (buyHoldPoints.length > 1) {
    series.push({
      key: "buy_hold",
      label: "buy & hold",
      type: "benchmark",
      points: buyHoldPoints,
      drawdownPoints: buildDrawdownSeries(buyHoldPoints),
      totalReturn: buyHoldPoints[buyHoldPoints.length - 1]?.value ?? 0,
      maxDrawdown: Math.min(...buildDrawdownSeries(buyHoldPoints).map((point) => point.value), 0),
      basis: "price"
    });
  }
  return series;
}

function variantDisplayLabel(variantName: string) {
  if (variantName === "baseline") return "Baseline";
  if (variantName === "manual_grid") return "Manual Grid Latest";
  if (variantName === "buy_hold") return "B&H";
  return variantName;
}

function curveSeriesColor(item: NormalizedCurveSeries, index = 0) {
  if (item.type === "benchmark") return BENCHMARK_CURVE_COLOR;
  const token = String(item.key || "").toLowerCase().replace(/^variant:/, "");
  if (token === "baseline" || token === "strategy") return "#4f6df5";
  if (token === "manual_grid") return "#de4b39";
  const palette = [
    "#0f766e",
    "#7c3aed",
    "#0284c7",
    "#ea580c",
    "#16a34a",
    "#db2777",
    "#4f46e5",
    "#ca8a04",
    "#0d9488",
    "#9333ea",
    "#dc2626",
    "#2563eb"
  ];
  const stableKey = String(item.key || item.label || index).replace(/^variant:/, "");
  const hash = Array.from(stableKey).reduce((value, character) => ((value * 31) + character.charCodeAt(0)) >>> 0, 0);
  return palette[hash % palette.length];
}

function curveColorForKey(
  key: string,
  label: string,
  type: "strategy" | "benchmark",
  orderedKeys: string[] = [],
  fallbackIndex = 0
) {
  const orderedIndex = orderedKeys.indexOf(key);
  return curveSeriesColor(
    { key, label, type, points: [], drawdownPoints: [], totalReturn: 0, maxDrawdown: 0 },
    orderedIndex >= 0 ? orderedIndex : fallbackIndex
  );
}

function buildCumulativeChartOption(series: NormalizedCurveSeries[], dates: string[]) {
  const yValues = series.flatMap((item) => item.points.map((point) => point.value)).filter((value) => Number.isFinite(value));
  const rawMin = yValues.length ? Math.min(...yValues, 0) : 0;
  const rawMax = yValues.length ? Math.max(...yValues, 0) : 0;
  const padding = Math.max(0.02, (rawMax - rawMin) * 0.12 || 0.05);
  return {
    animation: false,
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15,23,42,0.92)",
      borderWidth: 0,
      textStyle: { color: "#f8fafc" },
      valueFormatter: (value: number | string) => formatReturnPct(value),
      axisPointer: { type: "cross", lineStyle: { color: "#94a3b8", type: "dashed" } }
    },
    grid: [
      { left: 62, right: 22, top: 24, height: "58%" },
      { left: 62, right: 22, top: "74%", height: "16%" }
    ],
    xAxis: [
      {
        type: "category",
        boundaryGap: false,
        data: dates,
        gridIndex: 0,
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { show: false },
        axisTick: { show: false }
      },
      {
        type: "category",
        boundaryGap: false,
        data: dates,
        gridIndex: 1,
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b", hideOverlap: true },
        axisTick: { show: false }
      }
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        min: rawMin - padding,
        max: rawMax + padding,
        axisLabel: { color: "#64748b", formatter: (value: number) => formatReturnPct(value, 1) },
        splitLine: { lineStyle: { color: "rgba(203,213,225,0.52)" } }
      },
      {
        type: "value",
        gridIndex: 1,
        max: 0,
        axisLabel: { color: "#94a3b8", formatter: (value: number) => formatReturnPct(value, 1) },
        splitLine: { show: false }
      }
    ],
    series: [
      ...series.map((item, index) => ({
      color: curveSeriesColor(item, index),
      name: item.label,
      type: "line",
      xAxisIndex: 0,
      yAxisIndex: 0,
      smooth: false,
      showSymbol: false,
      emphasis: { focus: "series" },
      lineStyle: {
        color: curveSeriesColor(item, index),
        width: item.type === "benchmark" ? 2 : 3,
        type: item.type === "benchmark" ? "dashed" : "solid"
      },
      markLine: index === 0 ? {
        silent: true,
        symbol: "none",
        label: { show: false },
        lineStyle: { color: "#94a3b8", width: 1 },
        data: [{ yAxis: 0 }]
      } : undefined,
      data: dates.map((date) => {
        const point = item.points.find((entry) => entry.date === date);
        return point ? point.value : null;
      })
      })),
      ...series.filter((item) => item.type === "strategy").map((item, index) => ({
        name: `${item.label} 回撤`,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        smooth: false,
        lineStyle: { color: curveSeriesColor(item, index), width: 1.5, opacity: 0.7 },
        areaStyle: { color: "rgba(220,38,38,0.14)" },
        data: dates.map((date) => {
          const point = item.drawdownPoints.find((entry) => entry.date === date);
          return point ? point.value : null;
        })
      }))
    ]
  };
}

function curveSummary(rows: any[]) {
  const series = buildNormalizedCurveSeries(rows);
  const strategy = series.find((item) => item.key === "strategy");
  const buyHold = series.find((item) => item.key === "buy_hold");
  const excess = strategy && buyHold ? strategy.totalReturn - buyHold.totalReturn : null;
  return { strategy, buyHold, excess };
}

function CurveChart({ rows, height = 340, showLegend = true }: { rows: any[]; height?: number; showLegend?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const series = useMemo(() => buildNormalizedCurveSeries(rows), [rows]);
  const dates = useMemo(() => rows.map(rowDate), [rows]);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(buildCumulativeChartOption(series, dates), true);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dates, series]);
  return (
    <div className="curve-chart-shell">
      <div className="curve-chart-heading">
        <div><strong>单位仓位累计收益</strong><span>固定数量 · 非复利</span></div>
        <span>下方为策略回撤</span>
      </div>
      <div ref={ref} className="curve-canvas" style={{ height }} />
      {showLegend && series.length > 0 && (
        <div className="curve-legend">
          {series.map((item, index) => (
            <div className={`curve-series-card ${item.totalReturn >= 0 ? "positive" : "negative"}`} key={item.key}>
              <div className="curve-series-head">
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: curveSeriesColor(item, index) } : { background: curveSeriesColor(item, index) }} />
                <strong>{item.label}</strong>
              </div>
              <div className="curve-series-metrics">
                <span>累计 {formatReturnPct(item.totalReturn, 2)}</span>
                <span>回撤 {formatReturnPct(item.maxDrawdown, 2)}</span>
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
  height = 340,
  showLegend = true
}: {
  curves: Record<string, any[]>;
  visibleKeys: string[];
  labels?: Record<string, string>;
  benchmark?: NormalizedCurveSeries | null;
  height?: number;
  showLegend?: boolean;
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
    chart.setOption(buildCumulativeChartOption(series, dates), true);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dates, series]);

  return (
    <div className="curve-chart-shell">
      <div className="curve-chart-heading">
        <div><strong>单位仓位累计收益</strong><span>固定数量 · 非复利</span></div>
        <span>下方为策略回撤</span>
      </div>
      <div ref={ref} className="curve-canvas" style={{ height }} />
      {showLegend && series.length > 0 && (
        <div className="curve-legend">
          {series.map((item, index) => (
            <div className={`curve-series-card ${item.totalReturn >= 0 ? "positive" : "negative"}`} key={item.key}>
              <div className="curve-series-head">
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: curveSeriesColor(item, index) } : { background: curveSeriesColor(item, index) }} />
                <strong>{item.label}</strong>
              </div>
              <div className="curve-series-metrics">
                <span>累计 {formatReturnPct(item.totalReturn, 2)}</span>
                <span>回撤 {formatReturnPct(item.maxDrawdown, 2)}</span>
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
  onRefreshTasks,
  taskConnectionError
}: {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  tasks: WorkbenchTask[];
  onRefreshTasks: () => Promise<void>;
  taskConnectionError: boolean;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTasks, setDrawerTasks] = useState<WorkbenchTask[]>([]);
  const [taskFilter, setTaskFilter] = useState<TaskView>("all");
  const [selectedTask, setSelectedTask] = useState<WorkbenchTask | null>(null);
  const [loadingDrawer, setLoadingDrawer] = useState(false);
  const visibleTasks = tasks.slice(0, 3);
  const runningTask = tasks.find((task) => String(task.status).toLowerCase() === "running");
  const queuedTask = tasks.find((task) => String(task.status).toLowerCase() === "queued");
  const recentFailure = tasks.find((task) => {
    if (String(task.status).toLowerCase() !== "failed") return false;
    const updatedAt = new Date(task.updated_at).getTime();
    return Number.isFinite(updatedAt) && Date.now() - updatedAt <= 86400000;
  });
  const activeTask = runningTask || queuedTask || null;
  const counts = {
    running: tasks.filter((task) => task.status === "running").length,
    queued: tasks.filter((task) => task.status === "queued").length,
    failed: tasks.filter((task) => task.status === "failed").length
  };

  async function loadDrawerTasks(filter: TaskView = taskFilter) {
    setLoadingDrawer(true);
    try {
      const view = filter === "archived" ? "archived" : "all";
      const payload = await listTasks({ view, limit: 300 });
      const rows = (payload.tasks || []) as WorkbenchTask[];
      const filtered = filter === "active"
        ? rows.filter((task) => ["running", "queued"].includes(String(task.status)) && !task.archived_at)
        : filter === "failed"
          ? rows.filter((task) => task.status === "failed" && !task.archived_at)
          : filter === "completed"
            ? rows.filter((task) => ["completed", "cancelled"].includes(String(task.status)) && !task.archived_at)
            : filter === "archived"
              ? rows.filter((task) => Boolean(task.archived_at))
              : rows.filter((task) => !task.archived_at);
      setDrawerTasks(filtered);
      setSelectedTask((current) => filtered.find((task) => task.task_id === current?.task_id) || filtered[0] || null);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingDrawer(false);
    }
  }

  function openTaskDrawer(task?: WorkbenchTask) {
    setSelectedTask(task || null);
    setDrawerOpen(true);
    void loadDrawerTasks(taskFilter);
  }

  async function archiveEndedTasks() {
    try {
      const payload = await archiveTerminalTasks();
      await onRefreshTasks();
      await loadDrawerTasks(taskFilter);
      message.success(`已归档 ${Number(payload.archived_count || 0)} 条结束任务`);
    } catch (error) {
      message.error(String(error));
    }
  }

  function navigateFromTask(task: WorkbenchTask) {
    onPageChange(taskTargetPage(task));
    setDrawerOpen(false);
  }

  const groupedTasks = ["今天", "昨天", "更早"].map((label) => ({
    label,
    tasks: drawerTasks.filter((task) => taskDateGroup(task) === label)
  })).filter((group) => group.tasks.length);

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
          {taskConnectionError ? (
            <>
              <span className="status-pill status-failed">连接异常</span>
              <strong className="status-main">无法获取工作台状态</strong>
              <span className="status-sub">请检查后端服务后刷新。</span>
            </>
          ) : activeTask ? (
            <>
              <span className={statusClass(activeTask.status)}>{taskStatusLabel(activeTask.status)}</span>
              <strong className="status-main">{taskDisplayLabel(activeTask)}</strong>
              <div className="mini-progress status-progress"><span style={{ width: `${taskProgress(activeTask)}%` }} /></div>
              <span className="status-sub">{Math.round(taskProgress(activeTask))}% · {activeTask.message || activeTask.task_id}</span>
              <span className="status-sub">已运行 {elapsedLabel(activeTask)} · {formatDate(activeTask.updated_at)}</span>
            </>
          ) : recentFailure ? (
            <>
              <span className="status-pill status-failed">最近任务失败</span>
              <strong className="status-main">{taskDisplayLabel(recentFailure)}</strong>
              <span className="status-sub">{recentFailure.error || recentFailure.message || recentFailure.task_id}</span>
              <button className="mini-button status-detail-button" type="button" onClick={() => openTaskDrawer(recentFailure)}>查看失败详情</button>
            </>
          ) : (
            <>
              <span className="status-pill status-ready">就绪</span>
              <strong className="status-main">工作台空闲</strong>
              <span className="status-sub">接口已就绪，当前没有活动任务。</span>
            </>
          )}
          <div className="task-count-row">
            <span>运行 {counts.running}</span><span>排队 {counts.queued}</span><span className={counts.failed ? "is-danger" : ""}>失败 {counts.failed}</span>
          </div>
        </div>
      </section>

      <section className="sidebar-section jobs-section">
        <div className="section-head">
          <h2>{zh.recentTasks}</h2>
          <div className="jobs-head-actions">
            <span>{tasks.length}</span>
            <button className="mini-button" type="button" onClick={() => openTaskDrawer()}>查看全部</button>
          </div>
        </div>
        <div className="jobs-rail">
          {visibleTasks.length ? (
            visibleTasks.map((task) => (
              <button className="rail-job task-row-button" type="button" key={task.task_id} onClick={() => openTaskDrawer(task)}>
                <div className="rail-job-head">
                  <strong>{taskDisplayLabel(task)}</strong>
                  <span className={statusClass(task.status)}>{taskStatusLabel(task.status)}</span>
                </div>
                <div className="mini-progress">
                  <span style={{ width: `${taskProgress(task)}%` }} />
                </div>
                <span className="rail-job-meta">{taskSummary(task)}</span>
                <span className="rail-job-time">{formatDate(task.updated_at)}</span>
              </button>
            ))
          ) : (
            <div className="rail-job muted-card">
              <span className="rail-job-meta">当前没有可见任务。</span>
            </div>
          )}
        </div>
      </section>

      <Drawer
        title="任务中心"
        placement="right"
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={<Button size="small" onClick={archiveEndedTasks}>归档已结束</Button>}
      >
        <div className="task-drawer-layout" aria-busy={loadingDrawer}>
          <div className="task-filter-row">
            {([
              ["all", "全部"], ["active", "进行中"], ["failed", "失败"], ["completed", "已完成"], ["archived", "已归档"]
            ] as Array<[TaskView, string]>).map(([key, label]) => (
              <button
                type="button"
                key={key}
                className={`mini-button ${taskFilter === key ? "is-active" : ""}`}
                onClick={() => { setTaskFilter(key); void loadDrawerTasks(key); }}
              >{label}</button>
            ))}
          </div>
          <div className="task-drawer-body">
            <div className="task-history-list">
              {groupedTasks.length ? groupedTasks.map((group) => (
                <section className="task-history-group" key={group.label}>
                  <h3>{group.label}</h3>
                  {group.tasks.map((task) => (
                    <button type="button" className={`task-history-item ${selectedTask?.task_id === task.task_id ? "is-active" : ""}`} key={task.task_id} onClick={() => setSelectedTask(task)}>
                      <span><strong>{taskDisplayLabel(task)}</strong><small>{formatDate(task.created_at)}</small></span>
                      <span className={statusClass(task.status)}>{taskStatusLabel(task.status)}</span>
                    </button>
                  ))}
                </section>
              )) : <div className="empty-state">当前筛选下没有任务。</div>}
            </div>
            <div className="task-detail-panel">
              {selectedTask ? (
                <>
                  <div className="task-detail-head"><div><span className="summary-label">任务详情</span><h3>{taskDisplayLabel(selectedTask)}</h3></div><span className={statusClass(selectedTask.status)}>{taskStatusLabel(selectedTask.status)}</span></div>
                  <div className="mini-progress"><span style={{ width: `${taskProgress(selectedTask)}%` }} /></div>
                  <dl className="task-detail-grid">
                    <div><dt>进度</dt><dd>{Math.round(taskProgress(selectedTask))}%</dd></div>
                    <div><dt>耗时</dt><dd>{elapsedLabel(selectedTask)}</dd></div>
                    <div><dt>创建时间</dt><dd>{formatDate(selectedTask.created_at)}</dd></div>
                    <div><dt>更新时间</dt><dd>{formatDate(selectedTask.updated_at)}</dd></div>
                    {(["running", "queued", "failed"].includes(String(selectedTask.status)) || selectedTask.error) && <div className="span-2"><dt>{selectedTask.error ? "错误信息" : "当前阶段"}</dt><dd>{selectedTask.error || selectedTask.message || "-"}</dd></div>}
                    {selectedTask.related_run_id && <div className="span-2"><dt>关联 Run</dt><dd>{selectedTask.related_run_id}</dd></div>}
                    {selectedTask.related_strategy_id && <div className="span-2"><dt>关联策略</dt><dd>{selectedTask.related_strategy_id}</dd></div>}
                    {selectedTask.related_pool_item_id && <div className="span-2"><dt>关联策略池</dt><dd>{selectedTask.related_pool_item_id}</dd></div>}
                  </dl>
                  {(selectedTask.status === "failed" || selectedTask.related_run_id || selectedTask.related_pool_item_id) && (
                    <Button type="primary" onClick={() => navigateFromTask(selectedTask)}>
                      {selectedTask.status === "failed" ? "返回对应页面重新配置" : "查看关联结果"}
                    </Button>
                  )}
                </>
              ) : <div className="empty-state">请选择一个任务查看详情。</div>}
            </div>
          </div>
        </div>
      </Drawer>
    </aside>
  );
}

function LaunchFlowPage({
  onResearchCreated,
  onGenerated,
  onOpenGenerated,
  onWorkflowChange,
  refreshTasks
}: {
  onResearchCreated: (payload: any) => void;
  onGenerated: (payload: any) => void;
  onOpenGenerated: () => void;
  onWorkflowChange: (patch: Partial<WorkflowUiState>) => void;
  refreshTasks: () => Promise<void>;
}) {
  const fallbackSourceFiles = SOURCE_FILES.map((name) => ({ name }));
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>(fallbackSourceFiles);
  const [inputMode, setInputMode] = useState<"natural_language" | "manual_code" | "local_code">("natural_language");
  const [selectedFile, setSelectedFile] = useState(SOURCE_FILES[0] || "");
  const [sourceText, setSourceText] = useState("");
  const [savedSourceText, setSavedSourceText] = useState("");
  const [isCreatingSource, setIsCreatingSource] = useState(false);
  const [newSourceFilename, setNewSourceFilename] = useState("");
  const [manualStrategyName, setManualStrategyName] = useState("");
  const [manualStrategyCode, setManualStrategyCode] = useState("");
  const [localStrategyFiles, setLocalStrategyFiles] = useState<LocalStrategyFile[]>([]);
  const [selectedLocalPath, setSelectedLocalPath] = useState("");
  const localFolderInputRef = useRef<HTMLInputElement>(null);
  const [vtSymbolInput, setVtSymbolInput] = useState("511380.SSE");
  const [interval, setInterval] = useState("1m");
  const [startDate, setStartDate] = useState("2023-01-01");
  const [endDate, setEndDate] = useState(() => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" }));
  const [rate, setRate] = useState<number | null>(0.000045);
  const [slippage, setSlippage] = useState<number | null>(0.002);
  const [loadingResearch, setLoadingResearch] = useState(false);
  const [loadingSources, setLoadingSources] = useState(false);
  const [savingSource, setSavingSource] = useState(false);
  const [launchError, setLaunchError] = useState<any>(null);
  const isSourceDirty = !isCreatingSource && Boolean(selectedFile) && sourceText !== savedSourceText;
  const canRunNaturalLanguage = Boolean(selectedFile && sourceText.trim()) && !isCreatingSource && !isSourceDirty;
  const canRunManualCode = Boolean(manualStrategyName.trim() && manualStrategyCode.trim());
  const selectedLocalFile = localStrategyFiles.find((file) => file.relativePath === selectedLocalPath);
  const canRunLocalCode = Boolean(manualStrategyName.trim() && selectedLocalFile?.code.trim());
  const canRunSource = inputMode === "natural_language"
    ? canRunNaturalLanguage
    : inputMode === "local_code" ? canRunLocalCode : canRunManualCode;
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function refreshSourceFiles(preferredSelection?: string) {
    setLoadingSources(true);
    try {
      const payload = await listNaturalLanguageSources();
      const files = Array.isArray(payload.files) ? payload.files : [];
      if (files.length > 0) {
        setSourceFiles(files);
        const desiredSelection = [preferredSelection || selectedFile].find((name) =>
          name && files.some((file: SourceFile) => file.name === name)
        );
        setSelectedFile(desiredSelection || files[0]?.name || "");
      } else {
        setSourceFiles([]);
        setSelectedFile("");
      }
      return files;
    } catch (error) {
      message.warning("自然语言文本列表暂时不可用");
      return [];
    } finally {
      setLoadingSources(false);
    }
  }

  useEffect(() => {
    let active = true;
    refreshSourceFiles()
      .then((files) => {
        if (!active || files.length === 0) return;
        const nextName = files.some((file: SourceFile) => file.name === selectedFile) ? selectedFile : files[0]?.name || "";
        if (nextName) {
          void loadSourceText(nextName, true);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  async function loadSourceText(filename?: string, silent = false) {
    const selectedName = filename || selectedFile;
    if (!selectedName) {
      message.warning("请先选择一个文本文件");
      return;
    }
    setLoadingSources(true);
    try {
      const payload = await getNaturalLanguageSource(selectedName);
      const text = String(payload.text || "");
      setSourceText(text);
      setSavedSourceText(text);
      setIsCreatingSource(false);
      setNewSourceFilename("");
      setSelectedFile(selectedName);
      if (!silent) message.success(`已加载 ${selectedName}`);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoadingSources(false);
    }
  }

  function selectSourceFile(filename: string) {
    if (isCreatingSource) {
      message.warning("切换前请先保存或取消当前新建文本");
      return;
    }
    if (isSourceDirty) {
      message.warning("切换前请先保存当前文本");
      return;
    }
    if (!filename || filename === selectedFile) return;
    void loadSourceText(filename);
  }

  function startCreateSource() {
    if (isSourceDirty) {
      message.warning("新建前请先保存当前文本");
      return;
    }
    setIsCreatingSource(true);
    setNewSourceFilename("");
    setSourceText("");
    setSavedSourceText("");
  }

  function cancelCreateSource() {
    setIsCreatingSource(false);
    setNewSourceFilename("");
    if (selectedFile) {
      void loadSourceText(selectedFile, true);
      return;
    }
    setSourceText(savedSourceText);
  }

  async function saveSourceFile() {
    const filename = (isCreatingSource ? newSourceFilename : selectedFile).trim();
    const text = sourceText.trim();
    if (!filename) {
      message.warning("请先输入文件名");
      return;
    }
    if (!text) {
      message.warning("请先输入文本内容");
      return;
    }
    setSavingSource(true);
    try {
      const payload = isCreatingSource
        ? await createNaturalLanguageSource(filename, sourceText)
        : await updateNaturalLanguageSource(filename, sourceText);
      const savedName = String(payload.name || "");
      await refreshSourceFiles(savedName);
      setSelectedFile(savedName);
      setIsCreatingSource(false);
      setNewSourceFilename("");
      setSavedSourceText(String(payload.text || ""));
      message.success(`已保存 ${payload.name}`);
    } catch (error) {
      message.error(String(error));
    } finally {
      setSavingSource(false);
    }
  }

  async function loadLocalStrategyFile(event: React.ChangeEvent<HTMLInputElement>) {
    const inputFiles = Array.from(event.target.files || []);
    const file = inputFiles[0];
    if (!file || !file.name.toLowerCase().endsWith(".py")) {
      setLocalStrategyFiles([]);
      setSelectedLocalPath("");
      message.warning("请选择 .py 策略文件");
      event.target.value = "";
      return;
    }
    try {
      const loaded: LocalStrategyFile[] = [{
        name: file.name,
        relativePath: file.name,
        code: await file.text()
      }];
      setLocalStrategyFiles(loaded);
      setSelectedLocalPath(loaded[0].relativePath);
      setManualStrategyName(loaded[0].name.replace(/\.py$/i, ""));
      message.success(`已读取策略文件：${file.name}`);
    } catch (error) {
      message.error(`读取本地策略失败：${String(error)}`);
    } finally {
      event.target.value = "";
    }
  }

  async function runResearch() {
    const parsedVtSymbol = parseLaunchVtSymbol(vtSymbolInput);
    if (!parsedVtSymbol) {
      message.warning("请输入 SYMBOL.EXCHANGE 格式，例如 510300.SSE");
      return;
    }
    const { symbol, exchange } = parsedVtSymbol;
    const isCodeMode = inputMode === "manual_code" || inputMode === "local_code";
    const strategyCode = inputMode === "local_code" ? selectedLocalFile?.code || "" : manualStrategyCode;
    if (isCodeMode && !manualStrategyName.trim()) {
      message.warning("请先填写策略名称");
      return;
    }
    if (isCodeMode && !strategyCode.trim()) {
      message.warning(inputMode === "local_code" ? "请先选择包含 .py 策略的本地文件夹" : "请先粘贴完整 strategy.py 代码");
      return;
    }
    if (!isCodeMode && !canRunNaturalLanguage) {
      message.warning("启动前请先保存当前文本");
      return;
    }

    setLaunchError(null);
    setLoadingResearch(true);
    const startedAt = new Date().toISOString();
    onWorkflowChange({
      stageKey: "generation",
      message: isCodeMode ? "正在登记策略代码并创建 strategy.py。" : "正在根据自然语言生成 strategy.py。",
      startedAt,
      isRunning: true,
      error: null,
      downloadDiagnostics: null
    });
    onOpenGenerated();

    try {
      let autoDownloaded = false;
      let generationPayload: any = null;
      let strategyId = "";

      if (!isCodeMode) {
        generationPayload = await generateStrategy(selectedFile);
        onGenerated(generationPayload);
        await refreshTasks();
        strategyId = String(generationPayload?.strategy?.strategy_id || "");
        if (!strategyId) {
          throw new Error(generationPayload?.error || "策略生成失败");
        }
      }

      const coverage = await getDataCoverage(symbol, exchange, interval, startDate || undefined, endDate || undefined);
      const coverageStatus = String(coverage?.status || "").toLowerCase();
      if (["missing", "partial", "failed"].includes(coverageStatus)) {
        onWorkflowChange({
          stageKey: "download",
          message: "检测到缺失行情，系统正在自动下载。",
          downloadDiagnostics: coverage
        });
        const downloadPayload = await downloadData({
          symbol,
          exchange,
          interval,
          start_date: startDate,
          end_date: endDate
        });
        if (!downloadPayload?.success) {
          throw new Error(String(downloadPayload?.error || "行情下载失败"));
        }
        onWorkflowChange({ downloadDiagnostics: downloadPayload?.coverage || downloadPayload });
        const refreshedCoverage = await getDataCoverage(symbol, exchange, interval, startDate || undefined, endDate || undefined);
        const refreshedStatus = String(refreshedCoverage?.status || "").toLowerCase();
        if (!["covered", "available"].includes(refreshedStatus)) {
          throw new Error("下载后行情仍然不完整");
        }
        autoDownloaded = true;
      }

      onWorkflowChange({
        stageKey: "backtest",
        message: isCodeMode ? "策略代码已登记，正在运行 baseline 回测。" : "策略已生成，正在运行 baseline 回测。"
      });

      const payload = isCodeMode
        ? await createResearchBaselineFromCode({
            strategy_name: manualStrategyName.trim(),
            strategy_code: strategyCode,
            symbol,
            exchange,
            interval,
            start_date: startDate || undefined,
            end_date: endDate || undefined,
            rate: rate ?? 0.000045,
            slippage: slippage ?? 0.001,
            mode: "real"
          })
        : {
            generation: generationPayload,
            ...(await createResearchBaseline({
              strategy_id: strategyId,
              symbol,
              exchange,
              interval,
              start_date: startDate || undefined,
              end_date: endDate || undefined,
              rate: rate ?? 0.000045,
              slippage: slippage ?? 0.001,
              mode: "real"
            }))
          };

      if (payload?.generation) onGenerated(payload.generation);
      if (isCodeMode && payload?.generation?.strategy?.fixed_size_normalized) {
        message.info("检测到策略 fixed_size 不为 1，平台已自动标准化为 fixed_size = 1。");
      }
      onResearchCreated(payload);
      await refreshTasks();

      if (payload?.error || payload?.backtest?.success === false) {
        setLaunchError(payload);
        onWorkflowChange({
          stageKey: "idle",
          message: String(payload.error || "回测失败"),
          isRunning: false,
          error: payload
        });
        message.warning(String(payload.error || "回测失败"));
        return;
      }

      onWorkflowChange({
        stageKey: "idle",
        message: autoDownloaded ? "研究流程已完成，缺失行情已自动补齐。" : "研究流程已创建。",
        isRunning: false,
        error: null
      });
      message.success(autoDownloaded ? "缺失行情已下载，研究流程已创建" : "研究流程已创建");
    } catch (error) {
      setLaunchError({ error: String(error) });
      onWorkflowChange({
        stageKey: "idle",
        message: String(error),
        isRunning: false,
        error
      });
      message.error(String(error));
    } finally {
      if (mountedRef.current) setLoadingResearch(false);
    }
  }

  return (
    <section className="view is-active">
      <div className="hero-band">
        <div>
          <p className="eyebrow">G&amp;N</p>
          <h2>{zh.launchFlow}</h2>
          <p className="hero-copy">在这里配置回测参数，并从自然语言或直接粘贴代码启动完整研究流程。</p>
        </div>
      </div>

      <div className="pipeline-grid launch-config-grid">
        <section className="band setup-band">
          <div className="band-head">
            <div>
              <h3>{zh.startConfig}</h3>
              <p className="band-note">两种输入方式共用同一套回测配置，成功后都会进入同一条 baseline / 参数优化链路。</p>
            </div>
          </div>
          <div className="form-grid">
            <section className="field span-2">
              <div className="field-head">
                <span>{zh.inputMode}</span>
              </div>
              <div className="field-actions">
                <button className={`mini-button ${inputMode === "natural_language" ? "is-active" : ""}`} type="button" onClick={() => setInputMode("natural_language")}>{zh.naturalLanguageMode}</button>
                <button className={`mini-button ${inputMode === "manual_code" ? "is-active" : ""}`} type="button" onClick={() => setInputMode("manual_code")}>{zh.manualCodeMode}</button>
                <button className={`mini-button ${inputMode === "local_code" ? "is-active" : ""}`} type="button" onClick={() => setInputMode("local_code")}>{zh.localCodeMode}</button>
              </div>
            </section>

            {inputMode === "natural_language" && (
              <>
                <section className="field span-2">
                  <div className="field-head">
                    <span>{zh.sourceFiles}</span>
                    <div className="field-actions">
                      <button className="mini-button" type="button" onClick={startCreateSource}>{zh.newSource}</button>
                    </div>
                  </div>
                  <div className="source-checklist" aria-busy={loadingSources}>
                    {sourceFiles.map((file) => (
                      <button
                        type="button"
                        key={file.name}
                        className={`source-strip ${selectedFile === file.name ? "is-active" : ""}`}
                        onClick={() => selectSourceFile(file.name)}
                        disabled={loadingSources}
                      >
                        <strong>{file.name}</strong>
                        <small>{file.size ? `${file.size} 字节` : "本地 txt"}</small>
                      </button>
                    ))}
                  </div>
                </section>

                <section className="field span-2">
                  <div className="field-head">
                    <span>{zh.sourceText}</span>
                    {(isCreatingSource || isSourceDirty) && <span className="meta-inline">继续前请先保存为本地 txt</span>}
                  </div>
                  {(isCreatingSource || isSourceDirty) && (
                    <div className="inline-input-row">
                      <Input
                        value={newSourceFilename}
                        disabled={!isCreatingSource}
                        onChange={(event) => setNewSourceFilename(event.target.value)}
                        placeholder={`${zh.sourceFilename} / example_strategy.txt`}
                      />
                      <Button type="primary" loading={savingSource} onClick={saveSourceFile}>{zh.save}</Button>
                      <Button onClick={cancelCreateSource}>{zh.cancel}</Button>
                    </div>
                  )}
                  <Input.TextArea rows={7} value={sourceText} onChange={(event) => setSourceText(event.target.value)} />
                </section>
              </>
            )}

            {inputMode === "manual_code" && (
              <>
                <label className="field span-2">
                  <span>{zh.strategyNameInput}</span>
                  <Input value={manualStrategyName} onChange={(event) => setManualStrategyName(event.target.value)} placeholder="例如：线性回归斜率量化策略" />
                </label>
                <section className="field span-2">
                  <div className="field-head">
                    <span>{zh.strategyCodeInput}</span>
                    <span className="meta-inline">直接粘贴完整 strategy.py</span>
                  </div>
                  <Input.TextArea rows={12} value={manualStrategyCode} onChange={(event) => setManualStrategyCode(event.target.value)} placeholder="from vnpy_ctastrategy import CtaTemplate ..." />
                </section>
              </>
            )}

            {inputMode === "local_code" && (
              <>
                <section className="field span-2">
                  <div className="field-head">
                    <span>本地策略文件</span>
                    <span className="meta-inline">直接选择一个 .py 策略文件</span>
                  </div>
                  <input
                    ref={localFolderInputRef}
                    type="file"
                    accept=".py,text/x-python"
                    onChange={loadLocalStrategyFile}
                    style={{ display: "none" }}
                  />
                  <div className="inline-input-row">
                    <Button onClick={() => localFolderInputRef.current?.click()}>选择 .py 文件</Button>
                    <span className="meta-inline">
                      {selectedLocalFile ? `已选择：${selectedLocalFile.name}` : "尚未选择策略文件"}
                    </span>
                  </div>
                </section>
                <label className="field span-2">
                  <span>{zh.strategyNameInput}</span>
                  <Input value={manualStrategyName} onChange={(event) => setManualStrategyName(event.target.value)} placeholder="选择文件后自动使用文件名" />
                </label>
                {selectedLocalFile && (
                  <section className="field span-2">
                    <div className="field-head">
                      <span>代码预览</span>
                      <span className="meta-inline">{selectedLocalFile.relativePath}</span>
                    </div>
                    <Input.TextArea rows={12} value={selectedLocalFile.code} readOnly />
                  </section>
                )}
              </>
            )}

            <section className="pipeline-config-strip span-2">
              <div className="field-head pipeline-config-head">
                <span>{zh.backtestConfig}</span>
                <span className="meta-inline">仅支持单一标的</span>
              </div>
              <div className="pipeline-config-grid">
                <label className="field"><span>{zh.symbol}</span><Input value={vtSymbolInput} onChange={(event) => setVtSymbolInput(event.target.value)} placeholder="510300.SSE" /></label>
                <label className="field"><span>{zh.interval}</span><Input value={interval} onChange={(event) => setInterval(event.target.value)} /></label>
                <label className="field"><span>{zh.rate}</span><InputNumber min={0} step={0.000001} value={rate} onChange={(value) => setRate(typeof value === "number" ? value : null)} /></label>
                <label className="field"><span>{zh.startDate}</span><Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                <label className="field"><span>{zh.endDate}</span><Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
                <label className="field"><span>{zh.slippage}</span><InputNumber min={0} step={0.001} value={slippage} onChange={(value) => setSlippage(typeof value === "number" ? value : null)} /></label>
              </div>
            </section>

            {launchError && (
              <section className="band error-band span-2">
                <div className="band-head compact">
                  <div>
                    <h3>{zh.launchErrorTitle}</h3>
                    <p className="band-note">{launchError?.error || launchError?.generation?.error || launchError?.backtest?.error || "启动失败"}</p>
                  </div>
                  <span className="status-pill status-failed">failed</span>
                </div>
              </section>
            )}

            <div className="action-row span-2 launch-submit-row">
              <Button className="primary-button launch-submit-button" loading={loadingResearch} disabled={!canRunSource} onClick={runResearch}>{zh.startResearch}</Button>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}

type CurveControlItem = {
  key: string;
  label: string;
  type: "strategy" | "benchmark";
  value?: number | null;
  detail?: string;
};

function CurveControls({
  items,
  visibleKeys,
  startDate,
  endDate,
  bounds,
  onToggle,
  onSelectAll,
  onClear,
  onStartDateChange,
  onEndDateChange,
  onShortcut
}: {
  items: CurveControlItem[];
  visibleKeys: string[];
  startDate: string;
  endDate: string;
  bounds: { min: string; max: string };
  onToggle: (key: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onShortcut: (range: "3m" | "6m" | "1y" | "all") => void;
}) {
  return (
    <div className="curve-toolbar">
      <div className="curve-toolbar-meta">
        <span>已显示 {visibleKeys.length} / {items.length} 条</span>
        <button type="button" className="curve-toolbar-button" onClick={onSelectAll}>全选</button>
        <button type="button" className="curve-toolbar-button" onClick={onClear}>清空</button>
      </div>
      <div className="curve-pill-row">
        {items.map((item, index) => {
          const active = visibleKeys.includes(item.key);
          const previewSeries: NormalizedCurveSeries = {
            key: item.key,
            label: item.label,
            type: item.type,
            points: [],
            drawdownPoints: [],
            totalReturn: item.value ?? 0,
            maxDrawdown: 0
          };
          const color = curveSeriesColor(previewSeries, index);
          return (
            <button type="button" key={item.key} className={`curve-pill ${active ? "is-active" : ""}`} onClick={() => onToggle(item.key)} aria-pressed={active}>
              <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: color } : { background: color }} />
              <span className="curve-pill-copy">
                <strong>{item.label}</strong>
                <small>{item.detail || formatReturnPct(item.value, 2)}</small>
              </span>
            </button>
          );
        })}
      </div>
      <div className="curve-date-bar">
        <label className="curve-date-field">
          <span>开始</span>
          <Input type="date" value={startDate} min={bounds.min || undefined} max={endDate || bounds.max || undefined} onChange={(event) => onStartDateChange(event.target.value)} />
        </label>
        <label className="curve-date-field">
          <span>结束</span>
          <Input type="date" value={endDate} min={startDate || bounds.min || undefined} max={bounds.max || undefined} onChange={(event) => onEndDateChange(event.target.value)} />
        </label>
        <div className="curve-shortcuts">
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("3m")}>近3月</button>
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("6m")}>近6月</button>
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("1y")}>近1年</button>
          <button type="button" className="curve-shortcut-button" onClick={() => onShortcut("all")}>全部</button>
        </div>
      </div>
    </div>
  );
}

function StrategyGenerationPage({
  lastGenerated,
  lastResearch,
  workflowUi,
  tasks,
  onBackLaunch,
  onGoOptimize
}: {
  lastGenerated: any;
  lastResearch: any;
  workflowUi: WorkflowUiState;
  tasks: any[];
  onBackLaunch: () => void;
  onGoOptimize: () => void;
}) {
  const [runs, setRuns] = useState<any[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedRunDetail, setSelectedRunDetail] = useState<any>(null);
  const [curveRows, setCurveRows] = useState<any[]>([]);
  const [visibleCurveKeys, setVisibleCurveKeys] = useState<string[]>(["baseline", "buy_hold"]);
  const [curveStartDate, setCurveStartDate] = useState("");
  const [curveEndDate, setCurveEndDate] = useState("");
  const latestTask = tasks[0];
  const workflowRunId = lastResearch?.baseline?.run?.run_id || "";
  const generationPayload = lastResearch?.generation || lastGenerated;
  const generation = generationPayload?.generation || {};
  const strategy = generationPayload?.strategy || {};
  const fallbackMetrics = lastResearch?.backtest?.metrics || lastResearch?.baseline?.result?.metrics || lastResearch?.baseline?.variant?.metrics || {};
  const diagnostics = [
    ...(Array.isArray(generation?.diagnostics) ? generation.diagnostics : []),
    ...(Array.isArray(lastResearch?.backtest?.diagnostics) ? lastResearch.backtest.diagnostics : [])
  ];
  const selectedStrategy = selectedRunDetail?.strategy || strategy;
  const selectedMetrics = selectedRunDetail?.baseline_result?.metrics || fallbackMetrics;
  const code = selectedRunDetail?.strategy_code || generation?.strategy_code || "";
  const tradeCount = Number(
    selectedRunDetail?.baseline_trades_count
    ?? (Array.isArray(lastResearch?.backtest?.trades) ? lastResearch.backtest.trades.length : NaN)
  );
  const curveDateBounds = useMemo(() => curveDateBoundsForRows(curveRows), [curveRows]);
  const filteredCurveRows = useMemo(() => clampDateRange(curveRows, curveStartDate, curveEndDate), [curveEndDate, curveRows, curveStartDate]);
  const normalizedSummary = useMemo(() => curveSummary(filteredCurveRows), [filteredCurveRows]);
  const curveControlItems = useMemo<CurveControlItem[]>(() => [
    { key: "baseline", label: "Baseline", type: "strategy", value: normalizedSummary.strategy?.totalReturn },
    { key: "buy_hold", label: "Buy & Hold", type: "benchmark", value: normalizedSummary.buyHold?.totalReturn }
  ], [normalizedSummary]);

  function applyGenerationCurveShortcut(range: "3m" | "6m" | "1y" | "all") {
    const next = shortcutDateRange(curveDateBounds, range);
    setCurveStartDate(next.start);
    setCurveEndDate(next.end);
  }
  const researchError = workflowUi.error || (lastResearch?.error ? lastResearch : null);
  const researchMissingRanges = extractMissingRanges(researchError?.backtest);
  const downloadMissingRanges = extractMissingRanges(workflowUi.downloadDiagnostics);
  const missingRanges = researchMissingRanges.length > 0 ? researchMissingRanges : downloadMissingRanges;
  const generationDone = Boolean(generationPayload?.strategy);
  const baselineDone = Boolean(workflowRunId);
  const baselineFailed = Boolean(researchError);
  const workflowStartMs = new Date(workflowUi.startedAt || "").getTime();
  const flowTasks = tasks
    .filter((task: any) => {
      const createdAt = new Date(String(task.created_at || "")).getTime();
      return !Number.isFinite(workflowStartMs) || (Number.isFinite(createdAt) && createdAt >= workflowStartMs - 5000);
    })
    .sort((a: any, b: any) => new Date(String(b.updated_at || "")).getTime() - new Date(String(a.updated_at || "")).getTime());
  const stageTaskType = workflowUi.stageKey === "generation"
    ? "strategy_generation"
    : workflowUi.stageKey === "download"
      ? "data_download"
      : workflowUi.stageKey === "backtest" ? "backtest" : "";
  const stageTask = flowTasks.find((task: any) => task.task_type === stageTaskType);
  const stageTaskProgress = taskProgress(stageTask);
  const workflowProgress = baselineFailed
    ? Math.max(0, stageTaskProgress / 100)
    : baselineDone
      ? 1
      : workflowUi.stageKey === "generation"
        ? 0.05 + stageTaskProgress * 0.35 / 100
        : workflowUi.stageKey === "download"
          ? 0.4 + stageTaskProgress * 0.2 / 100
          : workflowUi.stageKey === "backtest"
            ? 0.65 + stageTaskProgress * 0.35 / 100
            : generationDone ? 0.4 : 0;
  const [displayWorkflowProgress, setDisplayWorkflowProgress] = useState(0);

  useEffect(() => {
    if (!workflowUi.startedAt) {
      setDisplayWorkflowProgress(0);
      return;
    }
    const timer = window.setInterval(() => {
      setDisplayWorkflowProgress((current) => {
        const target = Math.max(0, Math.min(1, workflowProgress));
        const distance = target - current;
        if (Math.abs(distance) < 0.003) return target;
        const step = Math.max(0.0025, Math.min(0.025, Math.abs(distance) * 0.14));
        return Math.max(0, Math.min(1, current + Math.sign(distance) * step));
      });
    }, 50);
    return () => window.clearInterval(timer);
  }, [workflowProgress, workflowUi.startedAt]);

  useEffect(() => {
    if (workflowUi.startedAt && !workflowUi.isRunning && !generationDone && !baselineDone) {
      setDisplayWorkflowProgress(0);
    }
  }, [baselineDone, generationDone, workflowUi.isRunning, workflowUi.startedAt]);
  const stageLabel = workflowUi.stageKey === "generation"
    ? "策略生成"
    : workflowUi.stageKey === "download"
      ? "行情下载"
      : workflowUi.stageKey === "backtest"
        ? "基线回测"
        : (latestTask?.task_type || zh.waiting);
  const statusLabel = workflowUi.isRunning ? "running" : (baselineFailed ? "failed" : (baselineDone ? "completed" : "pending"));
  const selectedStatus = selectedRunDetail?.run?.status || (lastResearch?.error ? "failed" : generationPayload?.task?.status || "completed");
  const showDiagnostics = Boolean(generationPayload && (!selectedRunId || selectedRunId === workflowRunId));

  useEffect(() => {
    let active = true;
    listRuns()
      .then((payload) => {
        if (!active) return;
        const nextRuns = payload.runs || [];
        setRuns(nextRuns);
        const preferredRunId = workflowRunId || nextRuns[0]?.run_id || "";
        setSelectedRunId((current) => workflowRunId || current || preferredRunId);
      })
      .catch((error) => {
        if (active) message.warning(String(error));
      });
    return () => {
      active = false;
    };
  }, [workflowRunId]);

  useEffect(() => {
    let active = true;
    if (!selectedRunId) {
      setSelectedRunDetail(null);
      setCurveRows(lastResearch?.backtest?.daily_results || []);
      return () => {
        active = false;
      };
    }
    Promise.all([
      getRun(selectedRunId),
      getVariantCurve(selectedRunId, "baseline")
    ])
      .then(([detail, curvePayload]) => {
        if (!active) return;
        setSelectedRunDetail(detail);
        setCurveRows(curvePayload.data || []);
      })
      .catch((error) => {
        if (!active) return;
        setSelectedRunDetail(null);
        setCurveRows(lastResearch?.backtest?.daily_results || []);
        message.warning(String(error));
      });
    return () => {
      active = false;
    };
  }, [selectedRunId, lastResearch]);

  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div>
          <p className="eyebrow">策略生成</p>
          <h2>{zh.generate}</h2>
          <p className="hero-copy">这个页面会实时显示策略生成、行情下载、基线回测，以及首轮结果预览。</p>
        </div>
        <div className="action-row">
          <Button onClick={onBackLaunch}>{zh.launchFlow}</Button>
          <Button disabled={!selectedRunId} onClick={onGoOptimize}>{zh.goOptimize}</Button>
        </div>
      </div>

      <section className="band progress-band compact-progress-band">
        <div className="compact-progress-row">
          <span className="compact-progress-label">{zh.currentProgress}</span>
          <span className="compact-progress-stage">{stageLabel}</span>
          <div className="progress-track compact-progress-track">
          <div className="progress-fill" style={{ width: `${Math.round(displayWorkflowProgress * 100)}%` }} />
          </div>
          <span className="compact-progress-percent">{Math.round(displayWorkflowProgress * 100)}%</span>
          <span className={statusClass(statusLabel)}>{statusLabel}</span>
        </div>
        <div className="compact-progress-note">{workflowUi.message || latestTask?.message || "当前没有活动任务。"}</div>
        <div className="job-meta compact-job-meta">
          <span>开始时间 {formatDate(workflowUi.startedAt || latestTask?.created_at)}</span>
          <span>{workflowRunId ? `运行 ${workflowRunId}` : "运行待创建"}</span>
          <span>{workflowUi.isRunning ? "流程进行中" : baselineDone ? "流程已完成" : "等待启动"}</span>
        </div>
      </section>

      {researchError && (
        <section className="band error-band">
          <div className="band-head compact">
            <div>
              <h3>{zh.researchFailed}</h3>
              <p className="band-note">{researchError.error || "回测失败"}</p>
            </div>
            <span className="status-pill status-failed">失败</span>
          </div>
          {missingRanges.length > 0 && (
            <div className="coverage-ranges prominent">
              {missingRanges.slice(0, 4).map((range: any, index: number) => (
                <span key={`${missingRangeLabel(range)}-${index}`}>{missingRangeLabel(range)}</span>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>运行版本</h3>
            <p>默认显示最新一版，也可以切换查看任意一个 run。</p>
          </div>
        </div>
        <div className="form-grid optimization-form-grid">
          <label className="field span-2">
            <span>选择 run</span>
            <Select
              value={selectedRunId || undefined}
              onChange={setSelectedRunId}
              options={runs.map((item) => ({ value: item.run_id, label: `${strategyLabel(item)} | ${item.vt_symbol || "-"} | ${formatDate(item.created_at)}` }))}
            />
          </label>
        </div>
      </section>

      {!selectedRunDetail && !generationPayload && !lastResearch && (
        <section className="band empty-state">从启动流程开始后，这里会显示实时进度和结果预览。</section>
      )}

      {curveRows.length > 0 && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>累计收益曲线</h3>
              <p>展示 fixed size = 1 下，按当日 net_pnl / 昨收计算并逐日累加后的收益走势。</p>
            </div>
          </div>
          <CurveControls
            items={curveControlItems}
            visibleKeys={visibleCurveKeys}
            startDate={curveStartDate}
            endDate={curveEndDate}
            bounds={curveDateBounds}
            onToggle={(key) => setVisibleCurveKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])}
            onSelectAll={() => setVisibleCurveKeys(curveControlItems.map((item) => item.key))}
            onClear={() => setVisibleCurveKeys([])}
            onStartDateChange={setCurveStartDate}
            onEndDateChange={setCurveEndDate}
            onShortcut={applyGenerationCurveShortcut}
          />
          {visibleCurveKeys.length > 0
            ? <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={{ baseline: filteredCurveRows }} visibleKeys={visibleCurveKeys} labels={{ baseline: "Baseline" }} showLegend={false} height={420} /></div>
            : <div className="empty-state">请选择至少一条曲线。</div>}
        </section>
      )}

      {(selectedRunDetail || generationPayload) && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>明细</h3>
              <p>{strategyLabel(selectedStrategy)}</p>
            </div>
            <span className={statusClass(selectedStatus)}>{selectedStatus}</span>
          </div>
          <div className="library-metric-grid">
            <div className="library-metric-card"><span>{zh.sharpe}</span><strong>{formatNumber(selectedMetrics.sharpe ?? selectedMetrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card positive"><span>策略累计收益</span><strong>{normalizedSummary.strategy ? formatReturnPct(normalizedSummary.strategy.totalReturn, 2) : "-"}</strong></div>
            <div className="library-metric-card"><span>buy & hold</span><strong>{normalizedSummary.buyHold ? formatReturnPct(normalizedSummary.buyHold.totalReturn, 2) : "-"}</strong></div>
            <div className={`library-metric-card ${Number(normalizedSummary.excess) >= 0 ? "positive" : "negative"}`}><span>超额收益</span><strong>{normalizedSummary.excess === null ? "-" : formatReturnPct(normalizedSummary.excess, 2)}</strong></div>
            <div className="library-metric-card negative"><span>{zh.drawdown}</span><strong>{normalizedSummary.strategy ? formatReturnPct(normalizedSummary.strategy.maxDrawdown, 2) : "-"}</strong></div>
            <div className="library-metric-card"><span>交易次数</span><strong>{Number.isFinite(tradeCount) ? String(tradeCount) : "-"}</strong></div>
            <div className="library-metric-card"><span>运行版本</span><strong>{selectedRunId || "-"}</strong></div>
            <div className="library-metric-card"><span>文本来源</span><strong>{selectedStrategy.source_filename || selectedStrategy.strategy_id || "-"}</strong></div>
          </div>
        </section>
      )}

      {showDiagnostics && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>诊断信息</h3>
              <p>{diagnostics.length} 条记录</p>
            </div>
          </div>
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
            <div className="empty-state">没有返回诊断信息。</div>
          )}
        </section>
      )}

      {code && (
        <section className="band code-band">
          <div className="band-head compact">
            <div>
              <h3>strategy.py</h3>
              <p className="band-note">显示当前所选 run 对应的策略代码。</p>
            </div>
            <span className={statusClass(code ? "completed" : "pending")}>{code ? "completed" : "pending"}</span>
          </div>
          <pre className="code-block">{code || ""}</pre>
        </section>
      )}
    </section>
  );
}

function ParameterOptimizationPage({
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
  const [spaceSuggestion, setSpaceSuggestion] = useState<any>(null);

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

  async function loadRunContext(nextRunId: string) {
    if (!nextRunId) return;
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
    const defaultPoolVariant = availableVariants.find((name: string) => name !== "baseline") || "baseline";
    const storedDraft = loadOptimizeDraft();
    const shouldReuseDraft = String(storedDraft.runId || "") === nextRunId;
    const parameterNames = (space.parameters || []).map((item: any) => String(item.name));
    setRunDetail(detail);
    setSearchSpace(space);
    setSpaceSuggestion(null);
    setVariantCurves(nextCurves);
    setVisibleCurveKeys(() => {
      if (shouldReuseDraft && Array.isArray(storedDraft.visibleCurveKeys)) {
        const allowed = new Set([...availableVariants, "buy_hold"]);
        const kept = storedDraft.visibleCurveKeys.map(String).filter((key: string) => allowed.has(key));
        if (kept.length) return kept;
      }
      return Array.from(new Set([...availableVariants, "buy_hold"]));
    });
    setPoolVariant((current) => {
      const preferred = shouldReuseDraft ? String(storedDraft.poolVariant || current || defaultPoolVariant) : current;
      return availableVariants.includes(preferred) ? preferred : defaultPoolVariant;
    });
    const nextRanges: Record<string, any> = {};
    for (const item of space.parameters || []) {
      nextRanges[item.name] = { low: item.low, high: item.high, step: item.step, type: item.type };
    }
    if (shouldReuseDraft && storedDraft.ranges && typeof storedDraft.ranges === "object") {
      for (const name of parameterNames) {
        if (storedDraft.ranges[name] && typeof storedDraft.ranges[name] === "object") {
          nextRanges[name] = { ...nextRanges[name], ...storedDraft.ranges[name] };
        }
      }
    }
    setRanges(nextRanges);
    setSelectedParams(shouldReuseDraft && Array.isArray(storedDraft.selectedParams) ? storedDraft.selectedParams.map(String).filter((name: string) => parameterNames.includes(name)) : []);
    if (!shouldReuseDraft) {
      setCurveStartDate("");
      setCurveEndDate("");
    }
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
  const optimizationRunId = String(optimizationResult?.run?.run_id || "");
  const optimizationObjective = String(optimizationResult?.objective || optimizationResult?.optimization?.objective || "");
  const optimizationMatchesRun = Boolean(optimizationResult) && optimizationRunId === runId;
  const optimizationMatchesObjective = !optimizationObjective || optimizationObjective === objective;
  const variants = useMemo(
    () => Array.from(new Set((runDetail?.variants || []).map((item: any) => String(item.variant_name || "")).filter(Boolean))),
    [runDetail]
  );
  const curveVariantNames = useMemo(() => Object.keys(variantCurves), [variantCurves]);
  const curveDateBounds = useMemo(() => {
    const dates = Object.values(variantCurves)
      .flatMap((rows) => rows.map((row) => normalizeDateKey(rowDate(row))))
      .filter(Boolean)
      .sort();
    const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
    const dataMax = dates[dates.length - 1] || "";
    return { min: dates[0] || "", max: dataMax > today ? dataMax : today };
  }, [variantCurves]);
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
    setRanges((current) => ({ ...current, [name]: { ...(current[name] || {}), [key]: value } }));
  }

  async function generateSpaceSuggestion() {
    if (!runId) return;
    setSuggestionLoading(true);
    try {
      const payload = await suggestOptimizationSearchSpace(runId, "baseline");
      const editableRows = [
        ...(payload.parameters || []),
        ...(payload.excluded_parameters || []).filter((item: any) => item.low !== undefined && item.high !== undefined)
      ];
      setSpaceSuggestion(payload);
      setMethod("optuna");
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
    } catch (error) {
      message.error(String(error));
    } finally {
      setSuggestionLoading(false);
    }
  }

  async function restoreStaticSpace() {
    if (!runId) return;
    await loadRunContext(runId);
    setSelectedParams([]);
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
    try {
      await addToPool(runId, poolVariant, currentRun?.vt_symbol);
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
    { title: zh.paramName, dataIndex: "name", render: (value, record) => <div className="param-name-cell"><strong>{value}</strong><span>{record.category || record.role}</span>{record.reason && <small>{record.reason}</small>}</div> },
    { title: zh.currentValue, dataIndex: "current", render: (value) => String(value) },
    { title: "下限", dataIndex: "low", render: (_, record) => <InputNumber value={ranges[record.name]?.low} step="any" onChange={(value) => updateRange(record.name, "low", value)} /> },
    { title: "上限", dataIndex: "high", render: (_, record) => <InputNumber value={ranges[record.name]?.high} step="any" onChange={(value) => updateRange(record.name, "high", value)} /> },
    { title: "步长", dataIndex: "step", render: (_, record) => <InputNumber value={ranges[record.name]?.step} step="any" onChange={(value) => updateRange(record.name, "step", value)} /> },
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
            <p>`manual_grid` 只展示最新一条同名结果，界面布局对齐 test1，先看曲线，再看表现。</p>
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
          <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={filteredVariantCurves} visibleKeys={visibleCurveKeys} showLegend={false} height={420} /></div>
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
          <div>
            <h3>{method === "optuna" ? "Optuna 智能优化" : method === "auto" ? "自动优化" : "手动网格"}</h3>
            <p>{method === "optuna" ? "使用 TPE 在限定试验次数内搜索更有希望的参数组合。" : method === "auto" ? "在选定参数范围内自动搜索最优组合。" : "在选定参数范围内做手动网格比较。"}</p>
          </div>
          <div className="optimization-mode-inline">
            <span>优化模式</span>
            <Select value={method} onChange={setMethod} options={methods.map((item) => ({ value: item.method, label: item.method === "auto" ? "自动优化" : item.method === "manual_grid" ? "手动网格" : item.label }))} />
            <span>Score 评分方式</span>
            <Select
              value={objective}
              onChange={setObjective}
              options={[
                { value: "sharpe", label: "Sharpe" },
                { value: "excess_return", label: "超额收益" }
              ]}
            />
            <span className="status-pill status-running">{method === "optuna" ? "Trials 200" : `网格 ${totalGridCount}`}</span>
          </div>
        </div>
        {["auto", "optuna"].includes(method) && (
          <div className="detail-grid optimizer-preview">
            {(searchSpace?.parameters || []).map((item: any) => (
              <div key={item.name}>
                <div className="summary-label">{item.name}</div>
                <div className="summary-value">{item.type}</div>
                <div className="meta-inline">{item.low} {"->"} {item.high} step {item.step}</div>
              </div>
            ))}
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
        <div className="action-row">
          <Button loading={suggestionLoading} disabled={!runId} onClick={generateSpaceSuggestion}>AI 生成优化建议</Button>
          <Button disabled={!runId || suggestionLoading} onClick={restoreStaticSpace}>恢复默认建议</Button>
          <Button type="primary" loading={loading} disabled={!runId || (method === "manual_grid" && !selectedParams.length)} onClick={submitOptimization}>
            {method === "optuna" ? "运行 Optuna 优化" : method === "auto" ? "运行自动优化" : "运行手动比较"}
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
          <Button type="primary" disabled={!runId || !poolVariant || poolVariant === "baseline"} onClick={addSelectedVariantToPool}>加入策略池</Button>
        </div>
        <div className="summary-compact-grid">
          <div className="viewer-summary-card"><span className="summary-label">运行版本</span><strong>{runId || "-"}</strong></div>
          <div className="viewer-summary-card">
            <span className="summary-label">入池版本</span>
            <Select
              value={poolVariant || undefined}
              onChange={setPoolVariant}
              options={curveVariantNames
                .filter((name) => name !== "baseline")
                .map((name) => ({
                  value: name,
                  label: name === "manual_grid" ? "Manual Grid Latest" : name
                }))}
            />
          </div>
          <div className="viewer-summary-card"><span className="summary-label">版本 Sharpe</span><strong>{formatNumber(poolVariantMetrics.sharpe ?? poolVariantMetrics.sharpe_ratio)}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">版本交易数</span><strong>{Number.isFinite(Number(poolVariantTradeCount)) ? String(poolVariantTradeCount) : "-"}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">优化器</span><strong>{optimizationResult?.optimization?.optimizer_name || "-"}</strong></div>
        </div>
      </section>
    </section>
  );
}


function PoolPage({
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
  const [selectedDetailId, setSelectedDetailId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [comparison, setComparison] = useState<any>({ items: [], benchmark: { curve: [] }, diagnostics: [] });
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [rerunProgress, setRerunProgress] = useState(0);
  const [rerunMessage, setRerunMessage] = useState("");
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [curveStartDate, setCurveStartDate] = useState("");
  const [curveEndDate, setCurveEndDate] = useState("");

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
      const payload = await rerunPool(selectedIds, today);
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
  const poolCurveDateBounds = useMemo(
    () => curveDateBoundsForRows(Object.values(compareCurves).flatMap((rows: any) => rows)),
    [compareCurves]
  );
  const filteredCompareCurves = useMemo(
    () => Object.fromEntries(Object.entries(compareCurves).map(([key, rows]) => [key, clampDateRange(rows as any[], curveStartDate, curveEndDate)])),
    [compareCurves, curveEndDate, curveStartDate]
  );
  const compareLabels = useMemo(() => Object.fromEntries(compareItems.map((item: any) => [item.pool_item_id, compareItemLabel(item)])), [compareItems]);
  const poolVisibleKeys = useMemo(() => [...selectedIds, ...(showBenchmark ? ["buy_hold"] : [])], [selectedIds, showBenchmark]);
  const poolCurveControlItems = useMemo<CurveControlItem[]>(() => [
    ...candidateItems.map((item) => ({
      key: String(item.pool_item_id),
      label: poolItemLabel(item),
      type: "strategy" as const,
      value: curveSummary(item?.curve || []).strategy?.totalReturn,
      detail: `${item.vt_symbol || "-"} · ${formatReturnPct(curveSummary(item?.curve || []).strategy?.totalReturn, 2)}`
    })),
    { key: "buy_hold", label: "Buy & Hold", type: "benchmark" as const, value: curveSummary(candidateItems[0]?.curve || []).buyHold?.totalReturn }
  ], [candidateItems]);

  function applyPoolCurveShortcut(range: "3m" | "6m" | "1y" | "all") {
    const next = shortcutDateRange(poolCurveDateBounds, range);
    setCurveStartDate(next.start);
    setCurveEndDate(next.end);
  }
  const comparisonColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "策略",
        dataIndex: "strategy_name",
        render: (value, record) => (
          <button className="link-cell strategy-pool-name-cell" type="button" onClick={() => openItem(record)}>
            <strong>{strategyLabel(record)}</strong>
            <span>{record.source_run_id || record.pool_item_id}</span>
          </button>
        )
      },
      { title: "变体", dataIndex: "variant_name", render: (value) => value || "-" },
      { title: "收益", render: (_, record) => formatPercent(metricValue(record.metrics, "total_return", "annual_return")) },
      { title: "年化", render: (_, record) => formatPercent(metricValue(record.metrics, "annual_return", "total_return")) },
      { title: zh.sharpe, render: (_, record) => formatNumber(metricValue(record.metrics, "sharpe", "sharpe_ratio")) },
      { title: "最大回撤", render: (_, record) => formatReturnPct(curveSummary(record?.curve || []).strategy?.maxDrawdown) },
      { title: "buy & hold", render: (_, record) => formatReturnPct(curveSummary(record?.curve || []).buyHold?.totalReturn) },
      { title: "超额收益", render: (_, record) => formatReturnPct(excessReturn(record)) }
    ],
    [comparison]
  );

  const metrics = detail?.result?.metrics || detail?.result || {};
  const detailCurveSummary = curveSummary(detail?.daily_results?.data || []);
  const params = detail?.config?.parameters || detail?.manifest?.parameters || detail?.result?.params || {};
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
            <Select value={selectedSymbol || undefined} onChange={(value) => { setSelectedSymbol(value); setSelectedIds([]); }} options={symbols.map((item) => ({ value: item, label: item }))} />
          </label>
          <label className="field library-folder-field">
            <span>策略搜索</span>
            <Input value={searchText} onChange={(event) => { setSearchText(event.target.value); setSelectedIds([]); }} placeholder="策略 / run / 变体 / 标签" />
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
          <Button type="primary" disabled={!selectedIds.length} loading={rerunning} onClick={rerunSelectedToToday}>重跑到今天</Button>
          <span>
            {comparison?.rerun_end
              ? `当前对比结果已重跑到 ${formatDate(comparison.rerun_end)}。`
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
          visibleKeys={poolVisibleKeys}
          startDate={curveStartDate}
          endDate={curveEndDate}
          bounds={poolCurveDateBounds}
          onToggle={(key) => key === "buy_hold" ? setShowBenchmark((current) => !current) : togglePoolItem(key)}
          onSelectAll={() => { setSelectedIds(candidateItems.map((item) => String(item.pool_item_id))); setShowBenchmark(true); }}
          onClear={() => { setSelectedIds([]); setShowBenchmark(false); }}
          onStartDateChange={setCurveStartDate}
          onEndDateChange={setCurveEndDate}
          onShortcut={applyPoolCurveShortcut}
        />
        {compareItems.length ? <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={filteredCompareCurves} visibleKeys={poolVisibleKeys} labels={compareLabels} showLegend={false} height={420} /></div> : <div className="empty-state">请至少选择一个策略。</div>}
        {(comparison?.diagnostics || []).length > 0 && <div className="diagnostic-list">{comparison.diagnostics.map((item: any, index: number) => <Tag color="orange" key={`${item.message}-${index}`}>{item.message}</Tag>)}</div>}
      </section>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>表现明细</h3><p>这里展示当前参与对比策略的核心指标。</p></div></div>
        <div className="library-table-wrap">
          <Table rowKey="pool_item_id" columns={comparisonColumns} dataSource={compareItems} pagination={{ pageSize: 8 }} loading={loading} className="workbench-table strategy-pool-detail-table" rowClassName={(record) => (record.pool_item_id === selectedDetailId ? "is-selected" : "")} />
        </div>
      </section>

      {detail && (
        <section className="band library-shell">
          <div className="library-section-head"><div><h3>{strategyLabel(detail.pool_item)}</h3><p>{detail.pool_item?.pool_item_id}</p></div><span className="status-pill status-completed">completed</span></div>
          <div className="library-metric-grid">
            <div className="library-metric-card"><span>{zh.sharpe}</span><strong>{formatNumber(detail.pool_item?.sharpe ?? metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card positive"><span>{zh.return}</span><strong>{formatPercent(detail.pool_item?.annual_return ?? metrics.annual_return ?? metrics.total_return)}</strong></div>
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


function App() {
  const [page, setPage] = useState<PageKey>(() => loadInitialPage());
  const [tasks, setTasks] = useState<WorkbenchTask[]>([]);
  const [taskConnectionError, setTaskConnectionError] = useState(false);
  const [poolItems, setPoolItems] = useState<any[]>([]);
  const [lastResearch, setLastResearch] = useState<any>(null);
  const [lastGenerated, setLastGenerated] = useState<any>(null);
  const [workflowUi, setWorkflowUi] = useState<WorkflowUiState>({
    stageKey: "idle",
    message: "当前没有活动任务。",
    startedAt: "",
    isRunning: false,
    downloadDiagnostics: null,
    error: null
  });

  async function refreshTasks() {
    try {
      const payload = await listTasks({ view: "recent", limit: 100 });
      setTasks(payload.tasks || []);
      setTaskConnectionError(false);
    } catch (error) {
      setTaskConnectionError(true);
      throw error;
    }
  }

  async function refreshPool() {
    const payload = await listPool();
    setPoolItems(payload.items || []);
  }

  useEffect(() => {
    refreshTasks().catch((error) => message.error(String(error)));
    refreshPool().catch((error) => message.error(String(error)));
  }, []);

  const hasActiveTasks = tasks.some((task) => ["running", "queued"].includes(String(task.status).toLowerCase()));

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    const delay = hasActiveTasks ? 1000 : 10000;

    const schedule = () => {
      if (disposed || document.hidden) return;
      timer = window.setTimeout(async () => {
        try {
          await refreshTasks();
        } catch {
          // The status card exposes connection failures without repeated toast noise.
        }
        schedule();
      }, delay);
    };

    const handleVisibility = () => {
      if (timer) window.clearTimeout(timer);
      if (!document.hidden) {
        void refreshTasks().catch(() => undefined);
        schedule();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    schedule();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [hasActiveTasks]);

  useEffect(() => {
    window.localStorage.setItem(PAGE_STORAGE_KEY, page);
  }, [page]);

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#17b8b1", borderRadius: 8, fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" } }}>
      <div className="shell">
        <Sidebar page={page} onPageChange={setPage} tasks={tasks} onRefreshTasks={refreshTasks} taskConnectionError={taskConnectionError} />
        <main className="workspace">
          {page === "launch" && (
            <LaunchFlowPage
              onResearchCreated={(payload) => {
                setLastResearch(payload);
                refreshPool().catch((error) => message.error(String(error)));
              }}
              onGenerated={(payload) => {
                setLastGenerated(payload);
                setLastResearch(null);
              }}
              onOpenGenerated={() => setPage("generate")}
              onWorkflowChange={(patch) => setWorkflowUi((current) => ({ ...current, ...patch }))}
              refreshTasks={refreshTasks}
            />
          )}
          {page === "generate" && (
            <StrategyGenerationPage
              lastGenerated={lastGenerated}
              lastResearch={lastResearch}
              workflowUi={workflowUi}
              tasks={tasks}
              onBackLaunch={() => setPage("launch")}
              onGoOptimize={() => setPage("optimize")}
            />
          )}
          {page === "optimize" && <ParameterOptimizationPage lastResearch={lastResearch} refreshPool={refreshPool} refreshTasks={refreshTasks} onOpenPool={() => setPage("pool")} />}
          {page === "pool" && <PoolPage poolItems={poolItems} refreshPool={refreshPool} refreshTasks={refreshTasks} />}
        </main>
      </div>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
