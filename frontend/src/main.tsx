import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { Button, Checkbox, ConfigProvider, Input, InputNumber, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import * as echarts from "echarts";
import {
  addToPool,
  createResearch,
  downloadData,
  generateStrategy,
  getDataCoverage,
  getNaturalLanguageSource,
  getPoolCurve,
  getPoolItem,
  listNaturalLanguageSources,
  listPool,
  listTasks
} from "./api";
import "./styles.css";

type PageKey = "generate" | "optimize" | "pool";

const zh = {
  workbench: "\u7814\u7a76\u5de5\u4f5c\u53f0",
  subtitle: "\u81ea\u7136\u8bed\u8a00\u7b56\u7565\u751f\u6210\u3001\u53c2\u6570\u5b9e\u9a8c\u548c\u7b56\u7565\u6c60\u6c89\u6dc0\u7684\u7edf\u4e00\u5165\u53e3\u3002",
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
  return String(value || "-").replace("T", " ").replace("+00:00", "");
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

function CurveChart({ rows, height = 340 }: { rows: any[]; height?: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      color: ["#17b8b1"],
      tooltip: { trigger: "axis" },
      grid: { left: 54, right: 24, top: 28, bottom: 42 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: rows.map((row) => row.date || row.datetime || row.trading_day || "")
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#edf1f5" } } },
      series: [
        {
          type: "line",
          smooth: true,
          symbolSize: 5,
          lineStyle: { width: 3 },
          areaStyle: { color: "rgba(23, 184, 177, 0.10)" },
          data: rows.map((row) => Number(row.balance ?? row.close_price ?? row.net_value ?? row.equity ?? 0))
        }
      ]
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [rows]);
  return <div ref={ref} className="curve-canvas" style={{ height }} />;
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

function StrategyGeneratePage({
  tasks,
  poolCount,
  lastResearch,
  onResearchCreated,
  onGenerated,
  onGoOptimize,
  refreshPool,
  refreshTasks
}: {
  tasks: any[];
  poolCount: number;
  lastResearch: any;
  onResearchCreated: (payload: any) => void;
  onGenerated: (payload: any) => void;
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
          <h2>{zh.generate}</h2>
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

      {(generationResult || lastResearch) && (
        <section className="band code-band">
          <div className="band-head compact">
            <div><h3>strategy.py</h3><p className="band-note">Returned by strategy generation API.</p></div>
            <span className={statusClass(generationResult?.task?.status || lastResearch?.generation?.task?.status)}>{generationResult?.task?.status || lastResearch?.generation?.task?.status}</span>
          </div>
          <pre className="code-block">{generationResult?.generation?.strategy_code || lastResearch?.generation?.generation?.strategy_code || ""}</pre>
        </section>
      )}
    </section>
  );
}

function ParameterOptimizationPage({ lastResearch }: { lastResearch: any }) {
  const columns: ColumnsType<any> = [
    { title: zh.paramName, dataIndex: "key" },
    { title: zh.currentValue, dataIndex: "current" },
    { title: "low", dataIndex: "low" },
    { title: "high", dataIndex: "high" },
    { title: "step", dataIndex: "step" },
    { title: "type", dataIndex: "type" }
  ];
  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div><p className="eyebrow">Parameter Research</p><h2>{zh.optimize}</h2><p className="hero-copy">Entry shell copied from the old workbench style. No real optimizer is connected yet.</p></div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{lastResearch?.baseline?.run?.run_id ? "1" : "0"}</div><div className="metric-label">run</div></div>
          <div className="metric-tile"><div className="metric-value">{PARAM_ROWS.length}</div><div className="metric-label">params</div></div>
        </div>
      </div>
      <section className="band library-shell">
        <div className="library-section-head"><div><h3>{zh.currentSelection}</h3><p>From the latest research/create response.</p></div><span className="status-pill status-pending">not connected</span></div>
        <div className="summary-compact-grid">
          <div className="viewer-summary-card"><span className="summary-label">run</span><strong>{lastResearch?.baseline?.run?.run_id || "-"}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">strategy</span><strong>{lastResearch?.generation?.strategy?.strategy_name || lastResearch?.generation?.strategy?.strategy_id || "-"}</strong></div>
          <div className="viewer-summary-card"><span className="summary-label">baseline</span><strong>{lastResearch?.execution_mode || "-"}</strong></div>
        </div>
        <div className="empty-state optimizer-note">{zh.parameterEngineNotConnected}</div>
        <Table rowKey="key" columns={columns} dataSource={PARAM_ROWS} pagination={false} className="workbench-table" />
        <div className="action-row"><Button disabled>{zh.startOptimization}</Button></div>
      </section>
    </section>
  );
}

function PoolPage({ poolItems, refreshPool }: { poolItems: any[]; refreshPool: () => Promise<void> }) {
  const [selected, setSelected] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [curve, setCurve] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  async function openItem(record: any) {
    setSelected(record);
    setLoading(true);
    try {
      const [detailPayload, curvePayload] = await Promise.all([getPoolItem(record.pool_item_id), getPoolCurve(record.pool_item_id)]);
      setDetail(detailPayload);
      setCurve(curvePayload.data || []);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoading(false);
    }
  }

  const columns: ColumnsType<any> = useMemo(
    () => [
      {
        title: zh.strategyName,
        dataIndex: "strategy_name",
        render: (value, record) => (
          <div className="strategy-pool-name-cell"><strong>{value || record.strategy_id}</strong><span>{record.pool_item_id}</span></div>
        )
      },
      { title: zh.symbol, dataIndex: "vt_symbol", render: (value) => value || "-" },
      { title: zh.sharpe, dataIndex: "sharpe", sorter: (a, b) => Number(a.sharpe || 0) - Number(b.sharpe || 0), render: (value) => formatNumber(value) },
      { title: zh.return, dataIndex: "annual_return", sorter: (a, b) => Number(a.annual_return || 0) - Number(b.annual_return || 0), render: (value) => formatPercent(value) },
      { title: zh.drawdown, dataIndex: "max_drawdown", render: (value) => formatPercent(value) },
      { title: zh.createdAt, dataIndex: "created_at", render: formatDate },
      {
        title: zh.tags,
        dataIndex: "tags",
        render: (value) => {
          let tags: string[] = [];
          try {
            tags = JSON.parse(value || "[]");
          } catch {
            tags = [];
          }
          return tags.length ? tags.map((tag) => <Tag key={tag}>{tag}</Tag>) : "-";
        }
      },
      { title: zh.action, render: (_, record) => <Button size="small" onClick={() => openItem(record)}>{zh.open}</Button> }
    ],
    []
  );

  const metrics = detail?.result?.metrics || detail?.result || {};
  const params = detail?.config?.parameters || detail?.manifest?.parameters || detail?.result?.params || {};
  const trades = detail?.trades?.data || [];
  const tradeColumns = (detail?.trades?.columns || Object.keys(trades[0] || {})).slice(0, 8).map((column: string) => ({ title: column, dataIndex: column }));

  return (
    <section className="view is-active">
      <div className="hero-band library-hero-band">
        <div><p className="eyebrow">Strategy Pool</p><h2>{zh.pool}</h2><p className="hero-copy">Long-lived strategy snapshots admitted through FastAPI.</p></div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{poolItems.length}</div><div className="metric-label">\u5165\u6c60\u7ed3\u679c</div></div>
          <div className="metric-tile"><div className="metric-value">{new Set(poolItems.map((item) => item.vt_symbol).filter(Boolean)).size}</div><div className="metric-label">\u6807\u7684\u6570\u91cf</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head"><div><h3>{zh.poolList}</h3><p>Sortable table, with detail preview below.</p></div><Button onClick={() => refreshPool().catch((error) => message.error(String(error)))}>{zh.refresh}</Button></div>
        <div className="library-table-wrap">
          <Table rowKey="pool_item_id" columns={columns} dataSource={poolItems} pagination={{ pageSize: 8 }} loading={loading} className="workbench-table" rowClassName={(record) => (record.pool_item_id === selected?.pool_item_id ? "is-selected" : "")} />
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
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.curve}</h3></div></div><div className="library-curve-panel"><CurveChart rows={curve} /></div></section>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.trades}</h3></div></div><Table rowKey={(_, index) => String(index)} dataSource={trades} pagination={{ pageSize: 6 }} className="workbench-table" columns={tradeColumns} /></section>
          <section className="library-section"><div className="library-section-head"><div><h3>{zh.code}</h3></div></div><pre className="code-block">{detail.strategy_code || ""}</pre></section>
        </section>
      )}
    </section>
  );
}

function App() {
  const [page, setPage] = useState<PageKey>("generate");
  const [tasks, setTasks] = useState<any[]>([]);
  const [poolItems, setPoolItems] = useState<any[]>([]);
  const [lastResearch, setLastResearch] = useState<any>(null);
  const [, setLastGenerated] = useState<any>(null);

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
          {page === "generate" && (
            <StrategyGeneratePage
              tasks={tasks}
              poolCount={poolItems.length}
              lastResearch={lastResearch}
              onResearchCreated={(payload) => {
                setLastResearch(payload);
                refreshPool().catch((error) => message.error(String(error)));
              }}
              onGenerated={setLastGenerated}
              onGoOptimize={() => setPage("optimize")}
              refreshPool={refreshPool}
              refreshTasks={refreshTasks}
            />
          )}
          {page === "optimize" && <ParameterOptimizationPage lastResearch={lastResearch} />}
          {page === "pool" && <PoolPage poolItems={poolItems} refreshPool={refreshPool} />}
        </main>
      </div>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
