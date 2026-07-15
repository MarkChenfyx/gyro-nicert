import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Checkbox, ConfigProvider, Drawer, Input, InputNumber, Modal, Progress, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  MarkLineComponent,
  TooltipComponent
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
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
  repairStrategyCode,
  rerunPool,
  runOptimization,
  updateNaturalLanguageSource
} from "../api";

export type PageKey = "launch" | "generate" | "optimize" | "pool";
export type TaskRunNavigation = { runId: string; requestId: number };
export const PAGE_STORAGE_KEY = "gyro_nicert.active_page";
export const OPTIMIZE_DRAFT_STORAGE_KEY = "gyro_nicert.optimize_draft";
export const BENCHMARK_CURVE_COLOR = "#475569";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  CanvasRenderer
]);

export type TaskStatusValue = "queued" | "running" | "completed" | "failed" | "cancelled";
export type TaskView = "all" | "active" | "failed" | "completed" | "archived";

export type WorkbenchTask = {
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

export const TASK_TYPE_LABELS: Record<string, string> = {
  research_workflow: "研究流程",
  strategy_generation: "策略生成",
  backtest: "基线回测",
  optimization: "参数优化",
  data_download: "行情下载",
  pool_add: "加入策略池",
  pool_rebuild: "策略池重跑"
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  ready: "就绪"
};

export function taskTypeLabel(taskType?: string) {
  return TASK_TYPE_LABELS[String(taskType || "")] || String(taskType || "未知任务");
}

export function taskDisplayLabel(task: WorkbenchTask) {
  const relatedSourceName = String(task.source_filename || "").trim();
  if (task.task_type === "research_workflow") {
    return relatedSourceName ? `${relatedSourceName} · 研究流程` : "研究流程";
  }
  if (relatedSourceName && task.task_type === "backtest") return `${relatedSourceName} · 基线回测`;
  if (relatedSourceName && task.task_type === "strategy_generation") return `${relatedSourceName} · 策略生成`;
  if (task.task_type !== "strategy_generation") return taskTypeLabel(task.task_type);
  const message = String(task.message || "");
  const separator = message.indexOf(" · ");
  const sourceName = separator > 0 ? message.slice(0, separator).trim() : "";
  return sourceName ? `${sourceName} · 策略生成` : taskTypeLabel(task.task_type);
}

export function taskSummary(task: WorkbenchTask) {
  const status = String(task.status || "").toLowerCase();
  if (status === "failed") return task.error || task.message || task.task_id;
  if (["running", "queued"].includes(status)) return task.message || task.task_id;
  if (task.task_type === "research_workflow") return "研究流程已完成";
  return "任务已完成";
}

export function taskStatusLabel(status?: string) {
  return TASK_STATUS_LABELS[String(status || "").toLowerCase()] || String(status || "未知");
}

export function taskProgress(task?: WorkbenchTask | null) {
  return Math.max(0, Math.min(100, Number(task?.progress || 0) * 100));
}

export function taskTargetPage(task: WorkbenchTask): PageKey {
  if (task.related_pool_item_id || task.task_type === "pool_add" || task.task_type === "pool_rebuild") return "pool";
  if (task.task_type === "optimization") return "optimize";
  if (task.task_type === "research_workflow") return task.status === "failed" ? "launch" : "generate";
  if (task.related_run_id && task.status !== "failed") return "generate";
  return "launch";
}

export function taskSourceIdentity(task: WorkbenchTask) {
  const explicit = String(task.source_filename || "").trim();
  if (explicit) return explicit;
  const message = String(task.message || "");
  const separator = message.indexOf(" · ");
  return separator > 0 ? message.slice(0, separator).trim() : "";
}

export function mergeRecentResearchTasks(tasks: WorkbenchTask[]) {
  const consumed = new Set<string>();
  const merged: WorkbenchTask[] = [];
  const pairingWindowMs = 30 * 60 * 1000;

  for (const task of tasks) {
    if (consumed.has(task.task_id)) continue;
    if (task.task_type === "backtest") {
      const backtestTime = new Date(task.created_at).getTime();
      const sourceIdentity = taskSourceIdentity(task);
      const generationTask = tasks.find((candidate) => {
        if (consumed.has(candidate.task_id) || candidate.task_type !== "strategy_generation") return false;
        const generationTime = new Date(candidate.created_at).getTime();
        const sameStrategy = Boolean(task.related_strategy_id)
          && task.related_strategy_id === candidate.related_strategy_id;
        const sameSource = Boolean(sourceIdentity) && sourceIdentity === taskSourceIdentity(candidate);
        return (sameStrategy || sameSource)
          && Number.isFinite(backtestTime)
          && Number.isFinite(generationTime)
          && generationTime <= backtestTime
          && backtestTime - generationTime <= pairingWindowMs;
      });
      if (generationTask) {
        consumed.add(generationTask.task_id);
        consumed.add(task.task_id);
        const generationProgress = Math.max(0, Math.min(1, Number(generationTask.progress || 0)));
        const backtestProgress = Math.max(0, Math.min(1, Number(task.progress || 0)));
        merged.push({
          ...task,
          task_type: "research_workflow",
          progress: String(task.status).toLowerCase() === "completed"
            ? 1
            : generationProgress * 0.35 + backtestProgress * 0.65,
          source_filename: sourceIdentity || taskSourceIdentity(generationTask),
          created_at: generationTask.created_at,
          error: task.error || generationTask.error,
          message: ["running", "queued"].includes(String(task.status).toLowerCase())
            ? "正在运行 baseline 回测"
            : task.message
        });
        continue;
      }
    }

    consumed.add(task.task_id);
    if (task.task_type === "strategy_generation" && ["running", "queued"].includes(String(task.status).toLowerCase())) {
      merged.push({
        ...task,
        task_type: "research_workflow",
        progress: 0.05 + Math.max(0, Math.min(1, Number(task.progress || 0))) * 0.55,
        source_filename: taskSourceIdentity(task),
        message: ["running", "queued"].includes(String(task.status).toLowerCase())
          ? "正在生成策略代码"
          : task.message
      });
    } else {
      merged.push(task);
    }
  }
  return merged;
}

export function elapsedLabel(task: WorkbenchTask) {
  const start = new Date(task.created_at).getTime();
  const end = ["running", "queued"].includes(String(task.status)) ? Date.now() : new Date(task.updated_at).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "-";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分 ${seconds % 60} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

export function taskDateGroup(task: WorkbenchTask) {
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

export function isPageKey(value: string): value is PageKey {
  return value === "launch" || value === "generate" || value === "optimize" || value === "pool";
}

export function loadInitialPage(): PageKey {
  if (typeof window === "undefined") return "launch";
  const stored = window.localStorage.getItem(PAGE_STORAGE_KEY);
  return stored && isPageKey(stored) ? stored : "launch";
}

export function loadOptimizeDraft(): Record<string, any> {
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

export const zh = {
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

export const SOURCE_FILES = [
  "opening_range_breakout_intraday.txt",
  "bollinger_rsi_reversion_loose.txt",
  "dual_thrust_classic.txt",
  "turtle_trading_classic.txt"
];

export type SourceFile = {
  name: string;
  size?: number;
  modified_at?: string;
};

export type LocalStrategyFile = {
  name: string;
  relativePath: string;
  code: string;
  aiRepaired?: boolean;
  repairWarnings?: string[];
};

export type StrategyRepairUiStatus = "runnable" | "warning" | "failed";

export function normalizeStrategyRepairResponse(payload: any): {
  status: StrategyRepairUiStatus;
  detail: string;
  strategyCode: string;
} {
  const status = String(payload?.status || "").trim().toLowerCase();
  const strategyCode = typeof payload?.strategy_code === "string" ? payload.strategy_code : "";
  const changes = Array.isArray(payload?.changes) ? payload.changes.map(String).filter(Boolean) : [];
  const reasons = Array.isArray(payload?.reasons) ? payload.reasons.map(String).filter(Boolean) : [];
  if (status === "runnable" && strategyCode.trim()) {
    return {
      status: "runnable",
      detail: changes.length ? changes.slice(0, 2).join("；") : "修正后的代码已可在平台独立运行",
      strategyCode
    };
  }
  if (status === "warning") {
    return {
      status: "warning",
      detail: reasons.length ? reasons.join("；") : "AI 判断代码仍需人工处理",
      strategyCode: ""
    };
  }
  return {
    status: "failed",
    detail: String(payload?.error || reasons[0] || (status === "runnable" ? "AI 修正没有返回可用代码" : "AI 返回格式错误或修正失败")),
    strategyCode: ""
  };
}

export type WorkflowUiState = {
  stageKey: "idle" | "generation" | "download" | "backtest";
  message: string;
  startedAt: string;
  isRunning: boolean;
  progress: number;
  sourceFilename: string;
  downloadDiagnostics: any;
  error: any;
};

export function formatDate(value?: string) {
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

export function strategyFamily(item: any) {
  const family = String(item?.strategy_family || "").trim();
  if (family) return family;
  const sourceFilename = String(item?.source_filename || "").trim();
  if (sourceFilename.endsWith(".txt")) return sourceFilename.slice(0, -4);
  return "";
}

export function strategyVersion(item: any) {
  return String(item?.strategy_version || "").trim();
}

export function strategyLabel(item: any) {
  const explicitName = String(item?.pool_strategy_name || item?.strategy_name || "").trim();
  if (explicitName) return explicitName;
  const family = strategyFamily(item);
  const version = strategyVersion(item);
  if (family && version) return `${family} | ${version}`;
  return String(item?.strategy_id || "-");
}

export function formatNumber(value: unknown, digits = 2) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "-";
}

export function formatPercent(value: unknown, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "-";
  const normalized = Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
  return `${normalized.toFixed(digits)}%`;
}

export function formatReturnPct(value: unknown, digits = 2) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}%` : "-";
}

export function cleanOptimizationNumber(value: number | null): number | null {
  if (value === null || !Number.isFinite(Number(value))) return value;
  const cleaned = Number(Number(value).toFixed(10));
  return Math.abs(cleaned) < 1e-9 ? 0 : cleaned;
}

export function optimizationPrecision(step: unknown): number {
  const numeric = Math.abs(Number(step));
  if (!Number.isFinite(numeric) || numeric <= 0 || Number.isInteger(numeric)) return 0;
  const text = numeric.toFixed(10).replace(/0+$/, "");
  return Math.min(10, Math.max(0, text.length - text.indexOf(".") - 1));
}

export function formatParameterValue(value: unknown) {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6)));
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value === null || value === undefined) return "-";
  return String(value);
}

export function summarizeParameters(parameters: unknown) {
  if (parameters && typeof parameters === "object" && !Array.isArray(parameters)) {
    const entries = Object.entries(parameters as Record<string, unknown>);
    if (!entries.length) return "-";
    return entries.map(([key, value]) => `${key}=${formatParameterValue(value)}`).join(" · ");
  }
  const text = String(parameters || "").trim();
  return text || "-";
}

export function statusClass(status?: string) {
  const normalized = String(status || "pending").toLowerCase();
  if (["succeeded", "completed", "optimized"].includes(normalized)) return "status-pill status-completed";
  if (["running", "queued"].includes(normalized)) return "status-pill status-running";
  if (normalized === "failed") return "status-pill status-failed";
  return "status-pill status-pending";
}

export function extractMissingRanges(payload: any): any[] {
  const direct = Array.isArray(payload?.missing_ranges) ? payload.missing_ranges : [];
  if (direct.length > 0) return direct;
  if (!Array.isArray(payload?.diagnostics)) return [];
  return payload.diagnostics.flatMap((item: any) => Array.isArray(item?.missing_ranges) ? item.missing_ranges : []);
}

export function missingRangeLabel(range: any) {
  const start = range?.start_date || range?.start || "?";
  const end = range?.end_date || range?.end || "?";
  return `${start} - ${end}`;
}

export function parseLaunchVtSymbol(value: string) {
  const normalized = String(value || "").trim().toUpperCase().replace(/\s+/g, "");
  const parts = normalized.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  return {
    vtSymbol: `${parts[0]}.${parts[1]}`,
    symbol: parts[0],
    exchange: parts[1],
  };
}

export type NormalizedCurvePoint = {
  date: string;
  value: number;
};

export type NormalizedCurveSeries = {
  key: string;
  label: string;
  type: "strategy" | "benchmark";
  points: NormalizedCurvePoint[];
  drawdownPoints: NormalizedCurvePoint[];
  totalReturn: number;
  maxDrawdown: number;
  basis?: "pnl" | "price";
};

export function buildDrawdownSeries(points: NormalizedCurvePoint[]): NormalizedCurvePoint[] {
  let peak = 0;
  return points.map((point) => {
    peak = Math.max(peak, point.value);
    return { date: point.date, value: Math.min(0, point.value - peak) };
  });
}

export function finiteNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function drawdownMetricValue(metrics: any): number | null {
  return finiteNumber(metrics?.max_drawdown_pct)
    ?? finiteNumber(metrics?.max_ddpercent)
    ?? finiteNumber(metrics?.max_drawdown);
}

export function rowDate(row: any): string {
  return String(row?.date || row?.datetime || row?.trading_day || "");
}

export function normalizeDateKey(value?: string): string {
  const text = String(value || "").trim();
  if (!text) return "";
  const matched = text.match(/\d{4}[-/]\d{2}[-/]\d{2}/);
  if (matched) return matched[0].replace(/\//g, "-");
  return text.includes("T") ? text.slice(0, 10) : text.slice(0, 10);
}

export function clampDateRange(rows: any[], startDate: string, endDate: string) {
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

export function shiftDate(value: string, months = 0, years = 0): string {
  const normalized = normalizeDateKey(value);
  if (!normalized) return "";
  const next = new Date(`${normalized}T00:00:00`);
  if (Number.isNaN(next.getTime())) return normalized;
  if (months) next.setMonth(next.getMonth() + months);
  if (years) next.setFullYear(next.getFullYear() + years);
  return next.toISOString().slice(0, 10);
}

export function curveDateBoundsForRows(rows: any[]): { min: string; max: string } {
  const dates = rows.map((row) => normalizeDateKey(rowDate(row))).filter(Boolean).sort();
  return { min: dates[0] || "", max: dates[dates.length - 1] || "" };
}

export function shortcutDateRange(bounds: { min: string; max: string }, range: "3m" | "6m" | "1y" | "all") {
  if (!bounds.min || !bounds.max) return { start: "", end: "" };
  if (range === "all") return { start: bounds.min, end: bounds.max };
  const requestedStart = range === "3m"
    ? shiftDate(bounds.max, -3)
    : range === "6m"
      ? shiftDate(bounds.max, -6)
      : shiftDate(bounds.max, 0, -1);
  return { start: requestedStart < bounds.min ? bounds.min : requestedStart, end: bounds.max };
}

export function valueFromKeys(row: any, keys: string[]): number | null {
  for (const key of keys) {
    const value = finiteNumber(row?.[key]);
    if (value !== null) return value;
  }
  return null;
}

export function closeValue(row: any): number | null {
  return valueFromKeys(row, ["close_price", "close", "price"]);
}

export function referenceClose(row: any, previousClose: number | null): number | null {
  if (previousClose !== null && previousClose > 0) return previousClose;
  const currentClose = closeValue(row);
  const preClose = valueFromKeys(row, ["pre_close", "prev_close", "previous_close"]);
  if (preClose !== null && preClose > 0 && currentClose !== null && currentClose > 0) {
    const ratio = preClose / currentClose;
    if (ratio > 0.5 && ratio < 1.5) return preClose;
  }
  return currentClose !== null && currentClose > 0 ? currentClose : null;
}

export function cumulativeStrategySeries(rows: any[]): NormalizedCurvePoint[] {
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

export function cumulativeBuyHoldSeries(rows: any[]): NormalizedCurvePoint[] {
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

export function buildStrategyCurve(rows: any[]): NormalizedCurveSeries | null {
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

export function buildNormalizedCurveSeries(rows: any[]): NormalizedCurveSeries[] {
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

export function variantDisplayLabel(variantName: string) {
  if (variantName === "baseline") return "Baseline";
  if (variantName === "manual_grid") return "Manual Grid Latest";
  if (variantName === "buy_hold") return "B&H";
  return variantName;
}

export function curveSeriesColor(item: NormalizedCurveSeries, index = 0) {
  if (item.type === "benchmark") return BENCHMARK_CURVE_COLOR;
  const token = String(item.key || "").toLowerCase().replace(/^variant:/, "");
  if (token === "baseline" || token === "strategy") return "#2563eb";
  if (token === "manual_grid") return "#f97316";
  const palette = [
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#16a34a",
    "#ca8a04",
    "#0f766e",
    "#9333ea",
    "#0ea5e9",
    "#84cc16",
    "#c2410c",
    "#4f46e5",
    "#14b8a6"
  ];
  return palette[index % palette.length];
}

export function curveColorForKey(
  key: string,
  label: string,
  type: "strategy" | "benchmark",
  orderedKeys: string[] = [],
  fallbackIndex = 0
) {
  const normalizedKey = String(key || "").replace(/^variant:/, "");
  const orderedIndex = orderedKeys.findIndex((candidate) => String(candidate || "").replace(/^variant:/, "") === normalizedKey);
  return curveSeriesColor(
    { key, label, type, points: [], drawdownPoints: [], totalReturn: 0, maxDrawdown: 0 },
    orderedIndex >= 0 ? orderedIndex : fallbackIndex
  );
}

export function buildCumulativeChartOption(series: NormalizedCurveSeries[], dates: string[], orderedKeys: string[] = []) {
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
      color: curveColorForKey(item.key, item.label, item.type, orderedKeys, index),
      name: item.label,
      type: "line",
      xAxisIndex: 0,
      yAxisIndex: 0,
      smooth: false,
      showSymbol: false,
      emphasis: { focus: "series" },
      lineStyle: {
        color: curveColorForKey(item.key, item.label, item.type, orderedKeys, index),
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
        lineStyle: { color: curveColorForKey(item.key, item.label, item.type, orderedKeys, index), width: 1.5, opacity: 0.7 },
        areaStyle: { color: "rgba(220,38,38,0.14)" },
        data: dates.map((date) => {
          const point = item.drawdownPoints.find((entry) => entry.date === date);
          return point ? point.value : null;
        })
      }))
    ]
  };
}

export function curveSummary(rows: any[]) {
  const series = buildNormalizedCurveSeries(rows);
  const strategy = series.find((item) => item.key === "strategy");
  const buyHold = series.find((item) => item.key === "buy_hold");
  const excess = strategy && buyHold ? strategy.totalReturn - buyHold.totalReturn : null;
  return { strategy, buyHold, excess };
}

export function CurveChart({ rows, height = 340, showLegend = true }: { rows: any[]; height?: number; showLegend?: boolean }) {
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

export function buildComparisonSeries(
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

const EMPTY_CURVE_LABELS: Record<string, string> = {};
const EMPTY_ORDERED_CURVE_KEYS: string[] = [];

function MultiVariantCurveChartComponent({
  curves,
  visibleKeys,
  labels = EMPTY_CURVE_LABELS,
  benchmark = null,
  orderedKeys = EMPTY_ORDERED_CURVE_KEYS,
  height = 340,
  showLegend = true
}: {
  curves: Record<string, any[]>;
  visibleKeys: string[];
  labels?: Record<string, string>;
  benchmark?: NormalizedCurveSeries | null;
  orderedKeys?: string[];
  height?: number;
  showLegend?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
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
  const option = useMemo(() => buildCumulativeChartOption(series, dates, orderedKeys), [dates, orderedKeys, series]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

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
                <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: curveColorForKey(item.key, item.label, item.type, orderedKeys, index) } : { background: curveColorForKey(item.key, item.label, item.type, orderedKeys, index) }} />
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

export const MultiVariantCurveChart = React.memo(MultiVariantCurveChartComponent);
MultiVariantCurveChart.displayName = "MultiVariantCurveChart";

export function Sidebar({
  page,
  onPageChange,
  onTaskNavigate,
  tasks,
  onRefreshTasks,
  taskConnectionError,
  workflowUi,
  workflowProgress
}: {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  onTaskNavigate: (task: WorkbenchTask) => void;
  tasks: WorkbenchTask[];
  onRefreshTasks: () => Promise<void>;
  taskConnectionError: boolean;
  workflowUi: WorkflowUiState;
  workflowProgress: number;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTasks, setDrawerTasks] = useState<WorkbenchTask[]>([]);
  const [taskFilter, setTaskFilter] = useState<TaskView>("all");
  const [selectedTask, setSelectedTask] = useState<WorkbenchTask | null>(null);
  const [loadingDrawer, setLoadingDrawer] = useState(false);
  const mergedTasks = useMemo(() => mergeRecentResearchTasks(tasks), [tasks]);
  const liveWorkflowTask = useMemo<WorkbenchTask | null>(() => {
    if (!workflowUi.isRunning || !workflowUi.startedAt) return null;
    const sourceFilename = String(workflowUi.sourceFilename || "").trim();
    const matchingTask = tasks.find((task) => {
      if (task.task_type !== "strategy_generation") return false;
      if (sourceFilename && taskSourceIdentity(task) !== sourceFilename) return false;
      return new Date(task.created_at).getTime() >= new Date(workflowUi.startedAt).getTime() - 5000;
    });
    return {
      task_id: matchingTask?.task_id || `live-research-${workflowUi.startedAt}`,
      task_type: "research_workflow",
      status: "running",
      progress: workflowProgress,
      message: workflowUi.message,
      source_filename: sourceFilename,
      related_strategy_id: matchingTask?.related_strategy_id,
      created_at: workflowUi.startedAt,
      updated_at: matchingTask?.updated_at || workflowUi.startedAt
    };
  }, [tasks, workflowProgress, workflowUi.isRunning, workflowUi.message, workflowUi.sourceFilename, workflowUi.startedAt]);
  const displayTasks = useMemo(() => {
    if (!liveWorkflowTask) return mergedTasks;
    const liveSource = taskSourceIdentity(liveWorkflowTask);
    const liveStart = new Date(liveWorkflowTask.created_at).getTime();
    return [
      liveWorkflowTask,
      ...mergedTasks.filter((task) => {
        if (task.task_id === liveWorkflowTask.task_id) return false;
        if (!liveSource || taskSourceIdentity(task) !== liveSource) return true;
        const taskTime = new Date(task.created_at).getTime();
        return !Number.isFinite(taskTime) || taskTime < liveStart - 5000;
      })
    ];
  }, [liveWorkflowTask, mergedTasks]);
  const activeTasks = displayTasks.filter((task) => ["running", "queued"].includes(String(task.status).toLowerCase()));
  const activeTaskIds = new Set(activeTasks.map((task) => task.task_id));
  const visibleTasks = [
    ...activeTasks,
    ...displayTasks.filter((task) => !activeTaskIds.has(task.task_id))
  ].slice(0, 5);

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
    onTaskNavigate(task);
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

      <section className="sidebar-section jobs-section">
        <div className="section-head">
          <h2>{zh.recentTasks}</h2>
          <div className="jobs-head-actions">
            <span>{visibleTasks.length}</span>
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

export function LaunchFlowPage({
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
  const [startDate, setStartDate] = useState("2025-01-02");
  const [endDate, setEndDate] = useState("2026-06-25");
  const [rate, setRate] = useState<number | null>(0.000045);
  const [slippage, setSlippage] = useState<number | null>(0.002);
  const [loadingResearch, setLoadingResearch] = useState(false);
  const [loadingSources, setLoadingSources] = useState(false);
  const [savingSource, setSavingSource] = useState(false);
  const [repairingLocalCode, setRepairingLocalCode] = useState(false);
  const [localRepairProgress, setLocalRepairProgress] = useState(0);
  const [localRepairFeedback, setLocalRepairFeedback] = useState<{
    status: StrategyRepairUiStatus;
    detail: string;
  } | null>(null);
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

  useEffect(() => {
    if (!repairingLocalCode) return;
    const timer = window.setInterval(() => {
      setLocalRepairProgress((current) => current >= 100
        ? 100
        : Math.min(92, current + Math.max(1, Math.ceil((92 - current) * 0.12))));
    }, 500);
    return () => window.clearInterval(timer);
  }, [repairingLocalCode]);

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
      setLocalRepairProgress(0);
      setLocalRepairFeedback(null);
      message.success(`已读取策略文件：${file.name}`);
    } catch (error) {
      message.error(`读取本地策略失败：${String(error)}`);
    } finally {
      event.target.value = "";
    }
  }

  async function repairLocalStrategyCode() {
    if (!selectedLocalFile?.code.trim()) {
      message.warning("请先选择需要修正的 .py 策略文件");
      return;
    }
    const targetPath = selectedLocalFile.relativePath;
    setLocalRepairProgress(6);
    setLocalRepairFeedback(null);
    setRepairingLocalCode(true);
    try {
      const payload = await repairStrategyCode({
        strategy_name: manualStrategyName.trim() || selectedLocalFile.name.replace(/\.py$/i, ""),
        strategy_code: selectedLocalFile.code,
        vt_symbol: vtSymbolInput.trim(),
        interval
      });
      const feedback = normalizeStrategyRepairResponse(payload);
      setLocalRepairProgress(100);
      setLocalRepairFeedback({ status: feedback.status, detail: feedback.detail });
      if (feedback.status === "warning") {
        message.warning("AI 判断代码仍需人工处理，已保留原回测代码");
        return;
      }
      if (feedback.status === "failed") {
        message.error(`AI 修正失败：${feedback.detail}`);
        return;
      }
      setLocalStrategyFiles((files) => files.map((file) => file.relativePath === targetPath
        ? {
            ...file,
            code: feedback.strategyCode,
            aiRepaired: true,
            repairWarnings: []
          }
        : file));
      message.success("AI修正完成，启动回测时将使用修正后的代码");
    } catch (error) {
      const detail = "AI 修正请求失败，请检查接口配置或网络后重试";
      setLocalRepairProgress(100);
      setLocalRepairFeedback({ status: "failed", detail });
      message.error(detail);
    } finally {
      setRepairingLocalCode(false);
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
      progress: 0.05,
      sourceFilename: isCodeMode ? manualStrategyName.trim() : selectedFile,
      error: null,
      downloadDiagnostics: null
    });
    onOpenGenerated();

    try {
      let autoDownloaded = false;
      let generationPayload: any = null;
      let strategyId = "";

      if (!isCodeMode) {
        onWorkflowChange({
          progress: 0.25,
          message: "生成请求已提交，正在等待 API 返回。"
        });
        generationPayload = await generateStrategy(selectedFile);
        onWorkflowChange({
          progress: 0.55,
          message: "生成 API 已返回，正在校验并登记策略代码。"
        });
        onGenerated(generationPayload);
        await refreshTasks();
        strategyId = String(generationPayload?.strategy?.strategy_id || "");
        if (!strategyId) {
          throw new Error(generationPayload?.error || "策略生成失败");
        }
      } else {
        onWorkflowChange({
          progress: 0.55,
          message: "策略代码已读取，正在登记并检查回测条件。"
        });
      }

      onWorkflowChange({ progress: 0.6, message: "策略代码已就绪，正在检查行情覆盖。" });
      const coverage = await getDataCoverage(symbol, exchange, interval, startDate || undefined, endDate || undefined);
      const coverageStatus = String(coverage?.status || "").toLowerCase();
      if (["missing", "partial", "failed"].includes(coverageStatus)) {
        onWorkflowChange({
          stageKey: "download",
          message: "检测到缺失行情，系统正在自动下载。",
          progress: 0.62,
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
        message: isCodeMode ? "策略代码已登记，正在运行 baseline 回测。" : "策略已生成，正在运行 baseline 回测。",
        progress: 0.65
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
        progress: 1,
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
                    <Button disabled={!selectedLocalFile} loading={repairingLocalCode} onClick={repairLocalStrategyCode}>AI 修正代码</Button>
                    <span className="meta-inline">
                      {selectedLocalFile ? `已选择：${selectedLocalFile.name}` : "尚未选择策略文件"}
                    </span>
                  </div>
                  {(repairingLocalCode || localRepairFeedback) && (
                    <div className={`ai-repair-mini ${localRepairFeedback ? `is-${localRepairFeedback.status}` : ""}`}>
                      <span className="ai-repair-mini-label">
                        {repairingLocalCode
                          ? "AI 正在修正"
                          : localRepairFeedback?.status === "runnable"
                            ? "修正成功"
                            : localRepairFeedback?.status === "warning"
                              ? "需要人工处理"
                              : "修正失败"}
                      </span>
                      <Progress
                        percent={localRepairProgress}
                        status={localRepairFeedback?.status === "failed" ? "exception" : localRepairFeedback?.status === "runnable" ? "success" : "active"}
                        strokeColor={localRepairFeedback?.status === "warning" ? "#d97706" : undefined}
                        showInfo={false}
                        strokeWidth={3}
                      />
                      <span className="ai-repair-mini-result">
                        {repairingLocalCode ? `${localRepairProgress}%` : localRepairFeedback?.detail}
                      </span>
                    </div>
                  )}
                </section>
                <label className="field span-2">
                  <span>{zh.strategyNameInput}</span>
                  <Input value={manualStrategyName} onChange={(event) => setManualStrategyName(event.target.value)} placeholder="选择文件后自动使用文件名" />
                </label>
                {selectedLocalFile && (
                  <section className="field span-2">
                    <div className="field-head">
                      <span>代码预览</span>
                      <span className="meta-inline">{selectedLocalFile.aiRepaired ? "AI修正版 · 本地原文件未修改" : selectedLocalFile.relativePath}</span>
                    </div>
                    <Input.TextArea rows={12} value={selectedLocalFile.code} readOnly />
                    {selectedLocalFile.aiRepaired && selectedLocalFile.repairWarnings?.length ? (
                      <span className="meta-inline">{selectedLocalFile.repairWarnings.join("；")}</span>
                    ) : null}
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

export type CurveControlItem = {
  key: string;
  label: string;
  type: "strategy" | "benchmark";
  value?: number | null;
  detail?: string;
};

export function CurveControls({
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
          const detail = item.detail || formatReturnPct(item.value, 2);
          return (
            <button
              type="button"
              key={item.key}
              className={`curve-pill ${active ? "is-active" : ""}`}
              onClick={() => onToggle(item.key)}
              aria-pressed={active}
              title={`${item.label}\n${detail}`}
            >
              <span className={`curve-swatch ${item.type === "benchmark" ? "is-dashed" : ""}`} style={item.type === "benchmark" ? { borderLeftColor: color } : { background: color }} />
              <span className="curve-pill-copy">
                <strong>{item.label}</strong>
                <small>{detail}</small>
              </span>
              <span className="curve-pill-check" aria-hidden="true">✓</span>
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

export function StrategyGenerationPage({
  lastGenerated,
  lastResearch,
  workflowUi,
  workflowProgress,
  onBackLaunch,
  onGoOptimize
}: {
  lastGenerated: any;
  lastResearch: any;
  workflowUi: WorkflowUiState;
  workflowProgress: number;
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

  useEffect(() => {
    if (!curveDateBounds.min || !curveDateBounds.max) return;
    setCurveStartDate(curveDateBounds.min);
    setCurveEndDate(curveDateBounds.max);
  }, [curveDateBounds.max, curveDateBounds.min, selectedRunId]);

  const researchError = workflowUi.error || (lastResearch?.error ? lastResearch : null);
  const researchMissingRanges = extractMissingRanges(researchError?.backtest);
  const downloadMissingRanges = extractMissingRanges(workflowUi.downloadDiagnostics);
  const missingRanges = researchMissingRanges.length > 0 ? researchMissingRanges : downloadMissingRanges;
  const baselineDone = Boolean(workflowRunId);
  const baselineFailed = Boolean(researchError);
  const stageLabel = workflowUi.startedAt ? "研究流程" : zh.waiting;
  const statusLabel = !workflowUi.startedAt
    ? "ready"
    : workflowUi.isRunning
      ? "running"
      : (baselineFailed ? "failed" : (baselineDone ? "completed" : "pending"));
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
          <div className="progress-fill" style={{ width: `${Math.round(workflowProgress * 100)}%` }} />
          </div>
          <span className="compact-progress-percent">{Math.round(workflowProgress * 100)}%</span>
          <span className={statusClass(statusLabel)}>{statusLabel}</span>
        </div>
        <div className="compact-progress-note">{workflowUi.message || "当前没有活动任务。"}</div>
        <div className="job-meta compact-job-meta">
          <span>{workflowUi.startedAt ? `开始时间 ${formatDate(workflowUi.startedAt)}` : "尚未启动新流程"}</span>
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

const ParameterOptimizationPage = React.lazy(() => import("../pages/ParameterOptimizationPage"));
const PoolPage = React.lazy(() => import("../pages/PoolPage"));

export default function App() {
  const [page, setPage] = useState<PageKey>(() => loadInitialPage());
  const [taskRunNavigation, setTaskRunNavigation] = useState<TaskRunNavigation | null>(null);
  const taskNavigationSequenceRef = useRef(0);
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
    progress: 0,
    sourceFilename: "",
    downloadDiagnostics: null,
    error: null
  });
  const [displayWorkflowProgress, setDisplayWorkflowProgress] = useState(0);
  const displayWorkflowStartedAtRef = useRef("");

  useEffect(() => {
    if (!workflowUi.startedAt) {
      displayWorkflowStartedAtRef.current = "";
      setDisplayWorkflowProgress(0);
      return;
    }
    const target = Math.max(0, Math.min(1, Number(workflowUi.progress || 0)));
    if (displayWorkflowStartedAtRef.current !== workflowUi.startedAt) {
      displayWorkflowStartedAtRef.current = workflowUi.startedAt;
      setDisplayWorkflowProgress(Math.min(0.05, target));
    }
    if (workflowUi.stageKey === "backtest" && target >= 0.65) {
      setDisplayWorkflowProgress((current) => Math.max(0.65, current));
    }
    if (!workflowUi.isRunning || target >= 1) {
      setDisplayWorkflowProgress(target);
      return;
    }
    const isWaitingForGenerationApi = workflowUi.stageKey === "generation" && target === 0.25;
    const timer = window.setInterval(() => {
      setDisplayWorkflowProgress((current) => {
        if (isWaitingForGenerationApi && current >= target) {
          return Math.min(0.45, current + 0.0025);
        }
        const distance = target - current;
        if (Math.abs(distance) < 0.003) return target;
        const step = Math.max(0.0025, Math.min(0.018, Math.abs(distance) * 0.1));
        return Math.max(0, Math.min(1, current + Math.sign(distance) * step));
      });
    }, isWaitingForGenerationApi ? 250 : 60);
    return () => window.clearInterval(timer);
  }, [workflowUi.isRunning, workflowUi.progress, workflowUi.stageKey, workflowUi.startedAt]);

  async function refreshTasks() {
    try {
      const payload = await listTasks({ view: "recent", limit: 50 });
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

  function navigateToOptimizationRun(runId: string) {
    const resolvedRunId = String(runId || "").trim();
    if (!resolvedRunId) return;
    taskNavigationSequenceRef.current += 1;
    setTaskRunNavigation({ runId: resolvedRunId, requestId: taskNavigationSequenceRef.current });
    setPage("optimize");
  }

  function navigateFromTask(task: WorkbenchTask) {
    const targetPage = taskTargetPage(task);
    const relatedRunId = String(task.related_run_id || "").trim();
    if (targetPage === "optimize" && relatedRunId) {
      navigateToOptimizationRun(relatedRunId);
      return;
    }
    setPage(targetPage);
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
        <Sidebar
          page={page}
          onPageChange={setPage}
          onTaskNavigate={navigateFromTask}
          tasks={tasks}
          onRefreshTasks={refreshTasks}
          taskConnectionError={taskConnectionError}
          workflowUi={workflowUi}
          workflowProgress={displayWorkflowProgress}
        />
        <main className="workspace">
          <React.Suspense fallback={<section className="band empty-state">正在加载页面…</section>}>
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
              workflowProgress={displayWorkflowProgress}
              onBackLaunch={() => setPage("launch")}
              onGoOptimize={() => setPage("optimize")}
            />
          )}
          {page === "optimize" && (
            <ParameterOptimizationPage
              lastResearch={lastResearch}
              taskRunNavigation={taskRunNavigation}
              onTaskRunApplied={(requestId) => setTaskRunNavigation((current) => current?.requestId === requestId ? null : current)}
              refreshPool={refreshPool}
              refreshTasks={refreshTasks}
              onOpenPool={() => setPage("pool")}
            />
          )}
          {page === "pool" && <PoolPage poolItems={poolItems} refreshPool={refreshPool} refreshTasks={refreshTasks} onContinueOptimization={navigateToOptimizationRun} />}
          </React.Suspense>
        </main>
      </div>
    </ConfigProvider>
  );
}
