export type PageKey = "launch" | "generate" | "optimize" | "pool" | "research";
export type TaskRunNavigation = { runId: string; requestId: number };
export type PoolNavigation = { poolItemId: string; vtSymbol: string; requestId: number };
export type ResearchNavigation = { poolItemId: string; requestId: number };
export const PAGE_STORAGE_KEY = "gyro_nicert.active_page";
export const OPTIMIZE_DRAFT_STORAGE_KEY = "gyro_nicert.optimize_draft";
export const BENCHMARK_CURVE_COLOR = "#475569";
export const LAUNCH_SYMBOL_OPTIONS = [
  { value: "511380.SSE", slippage: 0.002 },
  { value: "510300.SSE", slippage: 0.001 },
  { value: "510500.SSE", slippage: 0.001 },
  { value: "512100.SSE", slippage: 0.001 }
] as const;

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
  pool_rebuild: "策略池重跑",
  strategy_research: "参数稳定性研究"
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
  if (task.task_type === "strategy_research") return "research";
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
            ? "正在运行基线回测"
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
  return value === "launch" || value === "generate" || value === "optimize" || value === "pool" || value === "research";
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
  research: "\u7b56\u7565\u7814\u7a76",
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
  currentSelection: "\u8fd0\u884c\u7248\u672c",
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

export const LAUNCH_DRAFT_STORAGE_KEY = "gyro_nicert.launch_draft.v1";
export const SOURCE_SORT_STORAGE_KEY = "gyro_nicert.source_sort.v1";
export type SourceSortMode = "name" | "modified";

const SOURCE_SEARCH_ALIASES: Array<[string[], string]> = [
  [["布林"], "bulin bulindai bollinger band"],
  [["流动性", "扫损"], "liudongxing saosun liquidity sweep turtle soup"],
  [["挤压"], "jiya squeeze ttm"],
  [["释放"], "shifang release"],
  [["混沌"], "hundun choppiness"],
  [["指数"], "zhishu index"],
  [["双状态"], "shuangzhuangtai dual regime"],
  [["母线"], "muxian mother bar inside bar"],
  [["压缩"], "yasuo compression"],
  [["放量"], "fangliang volume"],
  [["突破"], "tupo breakout"],
  [["极值"], "jizhi extreme"],
  [["弹射"], "tanshe bounce"],
  [["波动率"], "bodonglv volatility"],
  [["收敛"], "shoulian contraction squeeze"],
  [["线性回归"], "xianxinghuigui linear regression"],
  [["斜率"], "xielv slope"],
  [["均线"], "junxian moving average ma"],
  [["回踩"], "huicai pullback"],
  [["唐奇安"], "tangqian donchian"],
  [["趋势"], "qushi trend"],
  [["日线"], "rixian daily"],
  [["防守"], "fangshou defensive"],
  [["超跌"], "chaodie oversold"],
  [["反弹"], "fantan rebound"],
  [["择时"], "zeshi timing"],
  [["日内"], "rinei intraday"],
  [["九转"], "jiuzhuan td sequential"],
  [["两仪四象"], "liangyisixiang"],
  [["开盘区间"], "kaipan qujian opening range orb"],
  [["海龟"], "haigui turtle"]
];

export function sourceSearchCorpus(filename: string): string {
  const normalizedName = filename.toLocaleLowerCase();
  const aliases = SOURCE_SEARCH_ALIASES
    .filter(([terms]) => terms.some((term) => normalizedName.includes(term)))
    .map(([, value]) => value);
  return [normalizedName, ...aliases].join(" ");
}

export function loadSourceSortMode(): SourceSortMode {
  try {
    return window.localStorage.getItem(SOURCE_SORT_STORAGE_KEY) === "modified" ? "modified" : "name";
  } catch {
    return "name";
  }
}

export type LaunchDraft = {
  inputMode: "natural_language" | "manual_code" | "local_code";
  selectedFile: string;
  manualStrategyName: string;
  manualStrategyCode: string;
  localStrategyFiles: LocalStrategyFile[];
  selectedLocalPath: string;
  vtSymbolInput: string;
  interval: string;
  startDate: string;
  endDate: string;
  rate: number | null;
  slippage: number | null;
};

export function loadLaunchDraft(): Partial<LaunchDraft> {
  try {
    const payload = JSON.parse(window.localStorage.getItem(LAUNCH_DRAFT_STORAGE_KEY) || "{}");
    if (!payload || typeof payload !== "object") return {};
    const localStrategyFiles = Array.isArray(payload.localStrategyFiles)
      ? payload.localStrategyFiles.filter((file: any) =>
          file && typeof file.name === "string" && typeof file.relativePath === "string" && typeof file.code === "string"
        ).slice(0, 1)
      : [];
    return { ...payload, localStrategyFiles };
  } catch {
    return {};
  }
}

export function saveLaunchDraft(payload: LaunchDraft) {
  try {
    window.localStorage.setItem(LAUNCH_DRAFT_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Storage may be disabled or full. The launch page must remain usable.
  }
}

export type StrategyRepairUiStatus = "runnable" | "warning" | "failed";

export function normalizeStrategyRepairResponse(payload: any): {
  status: StrategyRepairUiStatus;
  detail: string;
  strategyCode: string;
} {
  const status = String(payload?.status || "").trim().toLowerCase();
  const strategyCode = typeof payload?.strategy_code === "string" ? payload.strategy_code : "";
  const uniqueItems = (...groups: any[]) => Array.from(new Set(
    groups.flatMap((group) => Array.isArray(group) ? group : []).map((item) => String(item).trim()).filter(Boolean)
  ));
  const changes = uniqueItems(payload?.changes);
  const reasons = uniqueItems(payload?.reasons, payload?.warnings, payload?.blocking_issues);
  const error = String(payload?.error || "").trim();
  const detailSections = (sections: Array<[string, string[]]>) => sections
    .filter(([, items]) => items.length)
    .map(([label, items]) => `${label}\n${items.map((item) => `• ${item}`).join("\n")}`)
    .join("\n");
  if (status === "runnable" && strategyCode.trim()) {
    return {
      status: "runnable",
      detail: changes.length
        ? detailSections([["已完成修改：", changes]])
        : "修正后的代码已可在平台独立运行",
      strategyCode
    };
  }
  if (status === "warning") {
    return {
      status: "warning",
      detail: detailSections([
        ["已尝试修改：", changes],
        ["仍需人工处理：", reasons.length ? reasons : ["AI 判断代码仍需人工处理"]]
      ]),
      strategyCode: ""
    };
  }
  const failureReasons = uniqueItems(reasons, error ? [error] : []);
  return {
    status: "failed",
    detail: detailSections([
      ["已尝试修改：", changes],
      ["失败原因：", failureReasons.length
        ? failureReasons
        : [status === "runnable" ? "AI 修正没有返回可用代码" : "AI 返回格式错误或修正失败"]]
    ]),
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
  const displayName = String(item?.display_name || "").trim();
  if (displayName) return displayName;
  const explicitName = String(item?.pool_strategy_name || item?.strategy_name || "").trim();
  const poolVersion = String(item?.pool_version || "").trim();
  if (explicitName && poolVersion) return `${explicitName} | ${poolVersion}`;
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
      label: "B&H",
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
      ...[...series]
        .sort((left, right) => Number(left.type === "strategy") - Number(right.type === "strategy"))
        .map((item, index) => ({
        name: `${item.label} 回撤`,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        smooth: false,
        z: item.type === "benchmark" ? 1 : 2,
        lineStyle: {
          color: curveColorForKey(item.key, item.label, item.type, orderedKeys, index),
          width: item.type === "benchmark" ? 1.2 : 1.5,
          type: item.type === "benchmark" ? "dashed" : "solid",
          opacity: 0.72
        },
        areaStyle: {
          color: item.type === "benchmark" ? "rgba(71,85,105,0.12)" : "rgba(220,38,38,0.14)"
        },
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
