import React, { useEffect, useMemo, useState } from "react";
import { Button, Select, Tag, message } from "antd";
import { createStrategyInitialReview, getRun, getVariantCurve, listRuns } from "../api";
import { CopyCodeButton } from "../components/CopyCodeButton";
import {
  CurveControlItem,
  CurveControls,
  MultiVariantCurveChart,
  UI_TEXT,
  WorkflowUiState,
  clampDateRange,
  curveDateBoundsForRows,
  curveSummary,
  extractMissingRanges,
  formatDate,
  formatNumber,
  formatReturnPct,
  normalizeDateKey,
  missingRangeLabel,
  rowDate,
  shortcutDateRange,
  statusClass,
  strategyFamily,
  strategyLabel,
  taskStatusLabel,
  variantDisplayLabel,
  zh
} from "../app/ui";

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
  const [diagnosticsExpanded, setDiagnosticsExpanded] = useState(false);
  const [initialReviewPayload, setInitialReviewPayload] = useState<any>(null);
  const [initialReviewLoading, setInitialReviewLoading] = useState(false);
  const [initialReviewError, setInitialReviewError] = useState("");
  const workflowRunId = lastResearch?.baseline?.run?.run_id || "";
  const generationPayload = lastResearch?.generation || lastGenerated;
  const generation = generationPayload?.generation || {};
  const strategy = generationPayload?.strategy || {};
  const fallbackMetrics = lastResearch?.backtest?.metrics || lastResearch?.baseline?.result?.metrics || lastResearch?.baseline?.variant?.metrics || {};
  const diagnostics = [
    ...(Array.isArray(generation?.diagnostics) ? generation.diagnostics : []),
    ...(Array.isArray(lastResearch?.backtest?.diagnostics) ? lastResearch.backtest.diagnostics : [])
  ];
  const hasDiagnosticError = diagnostics.some((item: any) =>
    ["error", "failed", "fatal"].includes(String(item?.level || item?.status || "").toLowerCase())
  );
  const selectedStrategy = selectedRunDetail?.strategy || strategy;
  const benchmarkLabel = String(
    selectedRunDetail?.config?.vt_symbol
    || runs.find((item) => item.run_id === selectedRunId)?.vt_symbol
    || lastResearch?.baseline?.run?.vt_symbol
    || "buy_hold"
  ).trim();
  const selectedMetrics = selectedRunDetail?.baseline_result?.metrics || fallbackMetrics;
  const code = selectedRunDetail?.strategy_code || generation?.strategy_code || "";
  const tradeCount = Number(
    selectedRunDetail?.baseline_trades_count
    ?? (Array.isArray(lastResearch?.backtest?.trades) ? lastResearch.backtest.trades.length : NaN)
  );
  const curveDateBounds = useMemo(() => curveDateBoundsForRows(curveRows), [curveRows]);
  const filteredCurveRows = useMemo(() => clampDateRange(curveRows, curveStartDate, curveEndDate), [curveEndDate, curveRows, curveStartDate]);
  const normalizedSummary = useMemo(() => curveSummary(filteredCurveRows), [filteredCurveRows]);
  const initialReview = initialReviewPayload?.review || null;
  const initialReviewVerdict = initialReview?.verdict === "continue"
    ? { label: "可以进入参数优化", color: "success" }
    : initialReview?.verdict === "revise"
      ? { label: "建议先修正", color: "warning" }
      : { label: "样本不足", color: "error" };
  const curveControlItems = useMemo<CurveControlItem[]>(() => [
    { key: "baseline", label: UI_TEXT.term.baselineResult, type: "strategy", value: normalizedSummary.strategy?.totalReturn },
    { key: "buy_hold", label: benchmarkLabel, type: "benchmark", value: normalizedSummary.buyHold?.totalReturn }
  ], [benchmarkLabel, normalizedSummary]);

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
  const stageLabel = workflowUi.startedAt ? "生成与基线回测" : zh.waiting;
  const statusLabel = !workflowUi.startedAt
    ? "ready"
    : workflowUi.isRunning
      ? "running"
      : (baselineFailed ? "failed" : (baselineDone ? "completed" : "pending"));
  const selectedStatus = selectedRunDetail?.run?.status || (lastResearch?.error ? "failed" : generationPayload?.task?.status || "completed");
  const showDiagnostics = Boolean(generationPayload && (!selectedRunId || selectedRunId === workflowRunId));

  useEffect(() => {
    setDiagnosticsExpanded(hasDiagnosticError);
  }, [hasDiagnosticError, selectedRunId, workflowRunId]);

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

  useEffect(() => {
    let active = true;
    setInitialReviewPayload(null);
    setInitialReviewError("");
    if (!selectedRunId || selectedRunDetail?.run?.run_id !== selectedRunId || !selectedRunDetail?.baseline_result?.success) {
      setInitialReviewLoading(false);
      return () => {
        active = false;
      };
    }
    setInitialReviewLoading(true);
    createStrategyInitialReview(selectedRunId)
      .then((payload) => {
        if (!active) return;
        setInitialReviewPayload(payload);
      })
      .catch((error) => {
        if (!active) return;
        setInitialReviewError(String(error));
      })
      .finally(() => {
        if (active) setInitialReviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedRunDetail?.baseline_result?.success, selectedRunDetail?.run?.run_id, selectedRunId]);

  async function refreshInitialReview() {
    if (!selectedRunId || initialReviewLoading) return;
    setInitialReviewLoading(true);
    setInitialReviewError("");
    try {
      const payload = await createStrategyInitialReview(selectedRunId, true);
      setInitialReviewPayload(payload);
    } catch (error) {
      setInitialReviewError(String(error));
    } finally {
      setInitialReviewLoading(false);
    }
  }

  return (
    <section className="view is-active">
      <div className="hero-band compact-hero">
        <div>
          <p className="eyebrow">研究工作台</p>
          <h2>{zh.generate}</h2>
          <p className="hero-copy">这个页面会实时显示策略生成、行情下载、基线回测，以及首轮结果预览。</p>
        </div>
        <div className="action-row">
          <Button onClick={onBackLaunch}>{zh.launchFlow}</Button>
          <Button disabled={!selectedRunId} onClick={onGoOptimize}>{zh.goOptimize}</Button>
        </div>
      </div>

      {workflowUi.startedAt && (
        <section className="band progress-band compact-progress-band">
          <div className="compact-progress-row">
            <span className="compact-progress-label">{zh.currentProgress}</span>
            <span className="compact-progress-stage">{stageLabel}</span>
            <div className="progress-track compact-progress-track">
              <div className="progress-fill" style={{ width: `${Math.round(workflowProgress * 100)}%` }} />
            </div>
            <span className="compact-progress-percent">{Math.round(workflowProgress * 100)}%</span>
            <span className={statusClass(statusLabel)}>{taskStatusLabel(statusLabel)}</span>
          </div>
          <div className="compact-progress-note">{workflowUi.message}</div>
          <div className="job-meta compact-job-meta">
            <span>{`开始时间 ${formatDate(workflowUi.startedAt)}`}</span>
            <span>{workflowRunId ? `${UI_TEXT.term.runId}：${workflowRunId}` : `${UI_TEXT.term.run}待创建`}</span>
            <span>{workflowUi.isRunning ? "流程进行中" : baselineDone ? "流程已完成" : "等待启动"}</span>
          </div>
        </section>
      )}

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
            <h3>{UI_TEXT.term.run}</h3>
            <p>默认显示最新一次，也可以切换查看任意回测运行。</p>
          </div>
        </div>
        <div className="form-grid optimization-form-grid">
          <label className="field span-2">
            <span>选择{UI_TEXT.term.run}</span>
            <Select
              value={selectedRunId || undefined}
              onChange={setSelectedRunId}
              options={runs.map((item) => ({ value: item.run_id, label: `${strategyLabel(item)} | ${item.vt_symbol || "-"} | ${formatDate(item.created_at)}` }))}
            />
          </label>
        </div>
      </section>

      {!selectedRunDetail && !generationPayload && !lastResearch && (
        <section className="band empty-state">从“{UI_TEXT.page.launch}”开始后，这里会显示实时进度和结果预览。</section>
      )}

      {curveRows.length > 0 && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>累计收益对比</h3>
              <p>展示单位仓位（fixed size = 1）下，按当日净收益（net_pnl）与昨收计算并逐日累加的收益走势。</p>
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
            ? <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={{ baseline: filteredCurveRows }} visibleKeys={visibleCurveKeys} labels={{ baseline: UI_TEXT.term.baselineResult }} benchmarkLabel={benchmarkLabel} showLegend={false} height={420} /></div>
            : <div className="empty-state">请选择至少一条曲线。</div>}
        </section>
      )}

      {(selectedRunDetail || generationPayload) && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>绩效明细</h3>
              <p>{strategyLabel(selectedStrategy)}</p>
            </div>
            <span className={statusClass(selectedStatus)}>{taskStatusLabel(selectedStatus)}</span>
          </div>
          <div className="library-metric-grid">
            <div className="library-metric-card"><span>{zh.sharpe}</span><strong>{formatNumber(selectedMetrics.sharpe ?? selectedMetrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card positive"><span>{UI_TEXT.metric.totalReturn}</span><strong>{normalizedSummary.strategy ? formatReturnPct(normalizedSummary.strategy.totalReturn, 2) : "-"}</strong></div>
            <div className="library-metric-card"><span>{UI_TEXT.metric.benchmarkReturn}</span><strong>{normalizedSummary.buyHold ? formatReturnPct(normalizedSummary.buyHold.totalReturn, 2) : "-"}</strong></div>
            <div className={`library-metric-card ${Number(normalizedSummary.excess) >= 0 ? "positive" : "negative"}`}><span>{UI_TEXT.metric.excessReturn}</span><strong>{normalizedSummary.excess === null ? "-" : formatReturnPct(normalizedSummary.excess, 2)}</strong></div>
            <div className="library-metric-card negative"><span>{zh.drawdown}</span><strong>{normalizedSummary.strategy ? formatReturnPct(normalizedSummary.strategy.maxDrawdown, 2) : "-"}</strong></div>
            <div className="library-metric-card"><span>{UI_TEXT.metric.tradeCount}</span><strong>{Number.isFinite(tradeCount) ? String(tradeCount) : "-"}</strong></div>
            <div className="library-metric-card"><span>{UI_TEXT.term.runId}</span><strong>{selectedRunId || "-"}</strong></div>
            <div className="library-metric-card"><span>{UI_TEXT.term.strategySource}</span><strong>{selectedStrategy.source_filename || selectedStrategy.strategy_id || "-"}</strong></div>
          </div>
        </section>
      )}

      {selectedRunId && selectedRunDetail?.run?.run_id === selectedRunId && selectedRunDetail?.baseline_result?.success && (
        <section className="band library-shell ai-initial-review">
          <div className="library-section-head">
            <div>
              <h3>AI 初审</h3>
              <p>先检查成交样本，再快速核对回测表现和策略代码。</p>
            </div>
            <div className="ai-initial-review-actions">
              {initialReview && <Tag color={initialReviewVerdict.color}>{initialReviewVerdict.label}</Tag>}
              <Button size="small" loading={initialReviewLoading} onClick={refreshInitialReview}>
                {initialReview ? "重新初审" : "开始初审"}
              </Button>
            </div>
          </div>

          {initialReviewLoading && !initialReview && (
            <div className="ai-initial-review-state">AI 正在检查成交次数与策略代码…</div>
          )}

          {initialReviewError && !initialReviewLoading && (
            <div className="ai-initial-review-state is-error">
              <strong>AI 初审暂不可用</strong>
              <span>{initialReviewError}</span>
            </div>
          )}

          {initialReview && (
            <div className="ai-initial-review-body">
              <div className="ai-initial-review-conclusion">
                <span>初审结论</span>
                <strong>{initialReview.conclusion}</strong>
              </div>
              <div className="ai-initial-review-row is-code-review">
                <span>代码检查</span>
                <div>
                  <p>{initialReview.code_summary}</p>
                  {Array.isArray(initialReview.code_findings) && initialReview.code_findings.length > 0 && (
                    <div className="ai-code-finding-list">
                      {initialReview.code_findings.map((finding: any, index: number) => (
                        <article key={`${finding.title || "finding"}-${index}`}>
                          <Tag color={finding.severity === "confirmed" ? "error" : "warning"}>
                            {finding.severity === "confirmed" ? "确认问题" : "需要确认"}
                          </Tag>
                          <div>
                            <strong>{finding.title}</strong>
                            <small>{finding.evidence}</small>
                            <p>{finding.suggestion}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="ai-initial-review-row is-next-step">
                <span>下一步</span>
                <p>{initialReview.next_step}</p>
              </div>
              <div className="ai-initial-review-meta">
                <span>{initialReviewPayload.cached ? "已读取本次运行的初审缓存" : "已完成本次运行的初审"}</span>
                <span>{initialReviewPayload.model ? `模型：${initialReviewPayload.model}` : ""}</span>
              </div>
            </div>
          )}
        </section>
      )}

      {showDiagnostics && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>诊断信息</h3>
              <p>{diagnostics.length} 条记录</p>
            </div>
            <Button
              type="text"
              size="small"
              className="section-collapse-toggle"
              onClick={() => setDiagnosticsExpanded((current) => !current)}
            >
              {diagnosticsExpanded ? "收起" : "展开"}
            </Button>
          </div>
          {diagnosticsExpanded && (diagnostics.length ? (
            <div className="diagnostic-list">
              {diagnostics.map((item: any, index: number) => (
                <div className="diagnostic-item" key={`${item.message || "diag"}-${index}`}>
                  <span className={statusClass(item.level === "error" ? "failed" : "completed")}>{item.level === "error" ? "错误" : item.level === "warning" ? "警告" : "信息"}</span>
                  <p>{item.message || JSON.stringify(item)}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state">没有返回诊断信息。</div>
          ))}
        </section>
      )}

      {code && (
        <section className="band code-band">
          <div className="band-head compact">
            <div>
              <h3>strategy.py</h3>
              <p className="band-note">显示当前回测运行对应的策略代码。</p>
            </div>
            <div className="inline-input-row">
              <CopyCodeButton code={code} />
              <span className={statusClass(code ? "completed" : "pending")}>{code ? "已就绪" : "等待结果"}</span>
            </div>
          </div>
          <pre className="code-block">{code || ""}</pre>
        </section>
      )}
    </section>
  );
}

export default StrategyGenerationPage;
