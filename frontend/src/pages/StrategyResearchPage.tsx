import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, InputNumber, Select, Spin, message } from "antd";
import { getPoolResearchContext, runPoolResearchHeatmap } from "../api";
import ResearchHeatmap from "../components/ResearchHeatmap";
import { CurveChart, curveSummary, formatDate, strategyLabel } from "../app/ui";

const RESEARCH_POOL_STORAGE_KEY = "gyro_nicert.research_pool_item_id";
const RESEARCH_TAB_STORAGE_KEY = "gyro_nicert.research_tab";

type ResearchTab = "overview" | "heatmap";
type RangeSpec = { low: number; high: number; step: number };

function initialResearchTab(): ResearchTab {
  return window.localStorage.getItem(RESEARCH_TAB_STORAGE_KEY) === "heatmap" ? "heatmap" : "overview";
}

function formatPercent(value: unknown, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}%` : "-";
}

function formatNumber(value: unknown, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "-";
}

function gridValueCount(spec?: RangeSpec) {
  if (!spec) return 0;
  const low = Number(spec.low);
  const high = Number(spec.high);
  const step = Number(spec.step);
  if (![low, high, step].every(Number.isFinite) || step <= 0 || high < low) return 0;
  return Math.max(1, Math.floor((high - low) / step + 1.0000001));
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
  const [loadingContext, setLoadingContext] = useState(false);
  const [running, setRunning] = useState(false);
  const [xParameter, setXParameter] = useState("");
  const [yParameter, setYParameter] = useState("");
  const [ranges, setRanges] = useState<Record<string, RangeSpec>>({});
  const [metric, setMetric] = useState<"excess_return" | "sharpe">("excess_return");
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
      return;
    }
    window.localStorage.setItem(RESEARCH_POOL_STORAGE_KEY, selectedPoolItemId);
    const requestId = ++contextRequestRef.current;
    setLoadingContext(true);
    getPoolResearchContext(selectedPoolItemId)
      .then((payload) => {
        if (requestId !== contextRequestRef.current) return;
        const parameters = (payload.parameters || []) as any[];
        const parameterNames = new Set(parameters.map((item) => String(item.name)));
        const latest = payload.latest_heatmap || null;
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
        setXParameter(nextX);
        setYParameter(nextY);
        setRanges({ ...defaultRanges, ...(latest?.parameter_ranges || {}) });
        setMetric(latest?.objective === "sharpe" ? "sharpe" : "excess_return");
      })
      .catch((error) => {
        if (requestId === contextRequestRef.current) {
          setContext(null);
          setHeatmap(null);
          message.error(String(error));
        }
      })
      .finally(() => {
        if (requestId === contextRequestRef.current) setLoadingContext(false);
      });
  }, [selectedPoolItemId]);

  function switchTab(tab: ResearchTab) {
    setActiveTab(tab);
    window.localStorage.setItem(RESEARCH_TAB_STORAGE_KEY, tab);
  }

  function updateRange(name: string, key: keyof RangeSpec, value: number | null) {
    if (value === null) return;
    setRanges((current) => ({ ...current, [name]: { ...(current[name] || { low: 0, high: 0, step: 1 }), [key]: Number(value) } }));
  }

  const parameterOptions = useMemo(
    () => (context?.parameters || []).map((item: any) => ({ value: String(item.name), label: String(item.name) })),
    [context]
  );
  const xParameterMeta = (context?.parameters || []).find((item: any) => String(item.name) === xParameter);
  const yParameterMeta = (context?.parameters || []).find((item: any) => String(item.name) === yParameter);
  const totalGridCount = gridValueCount(ranges[xParameter]) * gridValueCount(ranges[yParameter]);

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
      message.success("参数稳定性研究完成");
      await refreshTasks().catch(() => undefined);
    } catch (error) {
      message.error(String(error));
      await refreshTasks().catch(() => undefined);
    } finally {
      setRunning(false);
    }
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

  function renderRangeRow(parameterName: string, parameterMeta: any) {
    const spec = ranges[parameterName];
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
              onChange={(value) => updateRange(parameterName, key, value === null ? null : Number(value))}
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
          <p className="eyebrow">STRATEGY RESEARCH</p>
          <h2>策略研究</h2>
          <p className="hero-copy">从策略池快照出发，检查收益表现和参数稳定性，不修改原策略与参数优化结果。</p>
        </div>
      </section>

      <section className="band research-selector-band">
        <label className="field research-symbol-select">
          <span>研究标的</span>
          <Select
            showSearch
            value={selectedSymbol}
            onChange={selectSymbol}
            optionFilterProp="label"
            placeholder="选择标的"
            options={symbolOptions}
          />
        </label>
        <label className="field research-strategy-select">
          <span>研究策略</span>
          <Select
            showSearch
            value={selectedPoolItemId || undefined}
            onChange={setSelectedPoolItemId}
            filterOption={(input, option) => fuzzySearchMatch(input, (option as any)?.searchText || option?.label)}
            filterSort={(left, right, info) => fuzzySearchScore(info.searchValue, (left as any)?.searchText || left?.label)
              - fuzzySearchScore(info.searchValue, (right as any)?.searchText || right?.label)}
            placeholder={selectedSymbol ? "搜索当前标的下的策略" : "请先选择标的"}
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
        <button type="button" className={activeTab === "heatmap" ? "is-active" : ""} onClick={() => switchTab("heatmap")}>参数稳定性</button>
      </nav>

      {loadingContext ? (
        <section className="band empty-state"><Spin size="small" /> 正在读取策略快照…</section>
      ) : !context ? (
        <section className="band empty-state">选择一个策略池快照后开始研究。</section>
      ) : activeTab === "overview" ? (
        <>
          <section className="library-metric-grid research-metric-grid">
            <div className="library-metric-card"><span>累计收益</span><strong>{formatPercent(strategyReturn)}</strong></div>
            <div className={`library-metric-card ${Number(excessReturn) >= 0 ? "positive" : "negative"}`}><span>超额收益</span><strong>{formatPercent(excessReturn)}</strong></div>
            <div className="library-metric-card"><span>Sharpe</span><strong>{formatNumber(metrics.sharpe ?? metrics.sharpe_ratio)}</strong></div>
            <div className="library-metric-card negative"><span>最大回撤</span><strong>{formatPercent(maxDrawdown)}</strong></div>
          </section>

          <section className="band research-overview-grid">
            <div className="library-curve-panel">
              <CurveChart rows={curveRows} height={360} />
            </div>
            <aside className="research-snapshot-card">
              <div><span>标的 / 周期</span><strong>{context.pool_item?.vt_symbol || "-"} · {context.config?.interval || "-"}</strong></div>
              <div><span>回测区间</span><strong>{context.config?.start_date || "-"} 至 {context.config?.end_date || "-"}</strong></div>
              <div><span>交易数量</span><strong>{Number(metrics.total_trade_count || 0).toLocaleString()}</strong></div>
              <div><span>快照编号</span><strong>{context.pool_item?.pool_item_id || "-"}</strong></div>
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
                <span>{positiveRows.length} 个有效组合，{positiveRatio === null ? "-" : `${Math.round(positiveRatio * 100)}%`} 的{metric === "excess_return" ? "超额收益" : "Sharpe"}为正。</span>
                <Button type="link" size="small" onClick={() => switchTab("heatmap")}>查看热力图</Button>
              </div>
            ) : <div className="empty-state compact-empty">尚未运行参数稳定性研究。</div>}
          </section>
        </>
      ) : (
        <>
          <section className="band research-settings-band">
            <div className="library-section-head">
              <div><h3>二维参数网格</h3><p>固定其他参数，只改变横纵轴两个参数；第一版最多运行 100 组。</p></div>
              <Button type="primary" loading={running} disabled={!xParameter || !yParameter || totalGridCount < 4 || totalGridCount > 100} onClick={runHeatmap}>运行参数研究</Button>
            </div>
            <div className="research-axis-grid">
              <label className="field"><span>横轴参数</span><Select value={xParameter || undefined} onChange={(value) => setXParameter(value)} options={parameterOptions.filter((item: { value: string }) => item.value !== yParameter)} /></label>
              <label className="field"><span>纵轴参数</span><Select value={yParameter || undefined} onChange={(value) => setYParameter(value)} options={parameterOptions.filter((item: { value: string }) => item.value !== xParameter)} /></label>
              <label className="field"><span>观察指标</span><Select value={metric} onChange={setMetric} options={[{ value: "excess_return", label: "超额收益" }, { value: "sharpe", label: "Sharpe" }]} /></label>
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
                <div><h3>参数稳定性热力图</h3><p>{heatmap.x_parameter} × {heatmap.y_parameter} · {formatDate(heatmap.created_at)} · ● 当前参数，★ 当前指标最优</p></div>
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
                  <p>{positiveRows.length} 个有效组合中，{positiveRatio === null ? "-" : `${Math.round(positiveRatio * 100)}%`} 的{metric === "excess_return" ? "超额收益" : "Sharpe"}为正。</p>
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
      )}
    </div>
  );
}
