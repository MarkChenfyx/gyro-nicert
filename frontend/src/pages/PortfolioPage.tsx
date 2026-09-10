import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, InputNumber, Modal, Select, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import AppIcon from "../components/AppIcon";
import {
  archivePortfolio,
  createPortfolio,
  downloadPortfolioCsv,
  getPortfolio,
  listPortfolios,
  refreshPortfolio,
  updatePortfolio
} from "../api";
import {
  CurveControlItem,
  CurveControls,
  MultiVariantCurveChart,
  clampDateRange,
  curveDateBoundsForRows,
  curveSummary,
  formatDate,
  formatNumber,
  formatReturnPct,
  shortcutDateRange,
  strategyLabel,
  UI_TEXT
} from "../app/ui";

type EditorComponent = { pool_item_id: string; weight: number };

type EditorState = {
  name: string;
  description: string;
  virtual_capital: number;
  start_date: string;
  end_date: string;
  components: EditorComponent[];
};

const EMPTY_EDITOR: EditorState = {
  name: "",
  description: "",
  virtual_capital: 1_000_000,
  start_date: "",
  end_date: "",
  components: []
};

function money(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number);
}

export default function PortfolioPage({ poolItems }: { poolItems: any[] }) {
  const [portfolios, setPortfolios] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR);
  const [editorSymbol, setEditorSymbol] = useState("");
  const [visibleCurveKeys, setVisibleCurveKeys] = useState<string[]>(["portfolio"]);
  const [curveStartDate, setCurveStartDate] = useState("");
  const [curveEndDate, setCurveEndDate] = useState("");
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [comparisonDetails, setComparisonDetails] = useState<Record<string, any>>({});
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonExpanded, setComparisonExpanded] = useState(true);
  const [comparisonStartDate, setComparisonStartDate] = useState("");
  const [comparisonEndDate, setComparisonEndDate] = useState("");
  const comparisonRequestRef = useRef(0);

  async function loadDetail(portfolioId: string) {
    if (!portfolioId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    try {
      const payload = await getPortfolio(portfolioId);
      setDetail(payload);
      setVisibleCurveKeys(["portfolio"]);
      const rows = payload?.snapshot?.daily_results || [];
      const bounds = curveDateBoundsForRows(rows);
      setCurveStartDate(bounds.min);
      setCurveEndDate(bounds.max);
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoading(false);
    }
  }

  async function loadList(preferredId = selectedId) {
    const payload = await listPortfolios();
    const rows = payload.items || [];
    setPortfolios(rows);
    setComparisonIds((current) => {
      const availableIds = new Set(rows.map((item: any) => String(item.portfolio_id)));
      const retained = current.filter((portfolioId) => availableIds.has(portfolioId)).slice(0, 10);
      return retained.length ? retained : rows.slice(0, 5).map((item: any) => String(item.portfolio_id));
    });
    const nextId = rows.some((item: any) => item.portfolio_id === preferredId)
      ? preferredId
      : String(rows[0]?.portfolio_id || "");
    setSelectedId(nextId);
    await loadDetail(nextId);
  }

  useEffect(() => {
    void loadList("").catch((error) => message.error(String(error)));
  }, []);

  useEffect(() => {
    const requestId = ++comparisonRequestRef.current;
    if (!comparisonIds.length) {
      setComparisonDetails({});
      setComparisonLoading(false);
      return;
    }
    setComparisonLoading(true);
    void Promise.all(comparisonIds.map(async (portfolioId) => {
      try {
        return [portfolioId, await getPortfolio(portfolioId)] as const;
      } catch {
        return null;
      }
    })).then((rows) => {
      if (requestId !== comparisonRequestRef.current) return;
      setComparisonDetails(Object.fromEntries(rows.filter((item): item is readonly [string, any] => Boolean(item))));
    }).finally(() => {
      if (requestId === comparisonRequestRef.current) setComparisonLoading(false);
    });
  }, [comparisonIds]);

  function openCreate() {
    setEditingId("");
    setEditor({ ...EMPTY_EDITOR, components: [] });
    setEditorSymbol("");
    setEditorOpen(true);
  }

  function openEdit() {
    const portfolio = detail?.portfolio;
    if (!portfolio) return;
    setEditingId(String(portfolio.portfolio_id));
    setEditor({
      name: String(portfolio.name || ""),
      description: String(portfolio.description || ""),
      virtual_capital: Number(portfolio.virtual_capital || 1_000_000),
      start_date: String(portfolio.start_date || ""),
      end_date: String(portfolio.end_date || ""),
      components: (portfolio.components || []).map((item: any) => ({
        pool_item_id: String(item.pool_item_id),
        weight: Number(item.weight || 1)
      }))
    });
    const firstPoolItemId = String(portfolio.components?.[0]?.pool_item_id || "");
    setEditorSymbol(String(poolItems.find((item) => String(item.pool_item_id) === firstPoolItemId)?.vt_symbol || ""));
    setEditorOpen(true);
  }

  function updateSelectedComponents(ids: string[]) {
    setEditor((current) => ({
      ...current,
      components: [
        ...current.components.filter((component) => {
          const item = poolItems.find((poolItem) => String(poolItem.pool_item_id) === component.pool_item_id);
          return String(item?.vt_symbol || "") !== editorSymbol;
        }),
        ...ids.map((poolItemId) => current.components.find((item) => item.pool_item_id === poolItemId) || {
          pool_item_id: poolItemId,
          weight: 1
        })
      ]
    }));
  }

  function updateWeight(poolItemId: string, value: number | null) {
    setEditor((current) => ({
      ...current,
      components: current.components.map((item) => item.pool_item_id === poolItemId
        ? { ...item, weight: Number(value || 0) }
        : item)
    }));
  }

  async function savePortfolio() {
    if (!editor.name.trim()) {
      message.warning("请输入组合名称");
      return;
    }
    if (!editor.components.length) {
      message.warning("请至少选择一个组成策略");
      return;
    }
    if (editor.components.some((item) => !Number.isFinite(item.weight) || item.weight <= 0)) {
      message.warning("所有组成策略权重都必须大于 0");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: editor.name.trim(),
        description: editor.description.trim(),
        virtual_capital: editor.virtual_capital,
        start_date: editor.start_date || undefined,
        end_date: editor.end_date || undefined,
        components: editor.components
      };
      const result = editingId
        ? await updatePortfolio(editingId, payload)
        : await createPortfolio(payload);
      const portfolioId = String(result?.portfolio?.portfolio_id || editingId);
      setEditorOpen(false);
      setSelectedId(portfolioId);
      await loadList(portfolioId);
      message.success(editingId ? "组合已更新并生成新组合快照" : "组合已创建");
    } catch (error) {
      message.error(String(error));
    } finally {
      setSaving(false);
    }
  }

  async function refreshSelected() {
    if (!selectedId) return;
    setRefreshing(true);
    try {
      await refreshPortfolio(selectedId);
      await loadList(selectedId);
      message.success("已根据当前策略快照生成新组合快照");
    } catch (error) {
      message.error(String(error));
    } finally {
      setRefreshing(false);
    }
  }

  function archiveSelected() {
    if (!selectedId) return;
    Modal.confirm({
      title: "归档这个组合？",
      content: "归档不会删除历史组合快照，组合将从当前列表中隐藏。",
      okText: "确认归档",
      cancelText: "取消",
      onOk: async () => {
        try {
          await archivePortfolio(selectedId);
          await loadList("");
          message.success("组合已归档");
        } catch (error) {
          message.error(String(error));
        }
      }
    });
  }

  const poolById = useMemo(() => new Map(poolItems.map((item) => [String(item.pool_item_id), item])), [poolItems]);
  const editorSymbols = useMemo(
    () => Array.from(new Set(poolItems.map((item) => String(item.vt_symbol || "")).filter(Boolean))).sort(),
    [poolItems]
  );
  const editorPoolItems = useMemo(
    () => poolItems
      .filter((item) => String(item.vt_symbol || "") === editorSymbol)
      .sort((left, right) => strategyLabel(left).localeCompare(strategyLabel(right), "zh-CN")),
    [editorSymbol, poolItems]
  );
  const editorSymbolComponentIds = editor.components
    .filter((component) => String(poolById.get(component.pool_item_id)?.vt_symbol || "") === editorSymbol)
    .map((component) => component.pool_item_id);
  const totalEditorWeight = editor.components.reduce((sum, item) => sum + Number(item.weight || 0), 0);
  const sortedEditorComponents = [...editor.components].sort((left, right) => {
    const leftItem = poolById.get(left.pool_item_id);
    const rightItem = poolById.get(right.pool_item_id);
    const symbolOrder = String(leftItem?.vt_symbol || "").localeCompare(String(rightItem?.vt_symbol || ""));
    if (symbolOrder !== 0) return symbolOrder;
    return strategyLabel(leftItem || left).localeCompare(strategyLabel(rightItem || right), "zh-CN");
  });
  const editorColumns: ColumnsType<EditorComponent> = [
    {
      title: UI_TEXT.term.tradingSymbol,
      key: "symbol",
      width: 120,
      render: (_, row) => <strong className="portfolio-editor-symbol">{poolById.get(row.pool_item_id)?.vt_symbol || "-"}</strong>
    },
    {
      title: UI_TEXT.term.componentStrategy,
      key: "strategy",
      render: (_, row) => {
        const item = poolById.get(row.pool_item_id);
        return <div className="portfolio-component-name"><strong>{item ? strategyLabel(item) : row.pool_item_id}</strong></div>;
      }
    },
    {
      title: "权重",
      dataIndex: "weight",
      width: 150,
      render: (value, row) => <InputNumber min={0.0001} precision={4} value={Number(value)} onChange={(next) => updateWeight(row.pool_item_id, next)} />
    },
    {
      title: "有效权重",
      key: "effective_weight",
      width: 120,
      render: (_, row) => totalEditorWeight > 0 ? `${(row.weight / totalEditorWeight * 100).toFixed(2)}%` : "-"
    }
  ];

  const comparisonBounds = useMemo(() => {
    const bounds = Object.values(comparisonDetails)
      .map((item: any) => curveDateBoundsForRows(item?.snapshot?.daily_results || []))
      .filter((item) => item.min && item.max);
    if (!bounds.length) return { min: "", max: "" };
    const commonMin = bounds.map((item) => item.min).sort().at(-1) || "";
    const commonMax = bounds.map((item) => item.max).sort()[0] || "";
    if (commonMin <= commonMax) return { min: commonMin, max: commonMax };
    return {
      min: bounds.map((item) => item.min).sort()[0] || "",
      max: bounds.map((item) => item.max).sort().at(-1) || ""
    };
  }, [comparisonDetails]);

  useEffect(() => {
    setComparisonStartDate(comparisonBounds.min);
    setComparisonEndDate(comparisonBounds.max);
  }, [comparisonBounds.min, comparisonBounds.max]);

  const comparisonCurves = useMemo(() => Object.fromEntries(
    Object.entries(comparisonDetails).map(([portfolioId, item]: [string, any]) => [
      portfolioId,
      clampDateRange(item?.snapshot?.daily_results || [], comparisonStartDate, comparisonEndDate)
    ])
  ), [comparisonDetails, comparisonEndDate, comparisonStartDate]);
  const comparisonLabels = useMemo(() => Object.fromEntries(
    portfolios.map((item) => [String(item.portfolio_id), String(item.name)])
  ), [portfolios]);
  const comparisonControlItems: CurveControlItem[] = portfolios.map((item) => {
    const portfolioId = String(item.portfolio_id);
    const totalReturn = curveSummary(comparisonCurves[portfolioId] || []).strategy?.totalReturn;
    return {
      key: portfolioId,
      label: String(item.name),
      type: "strategy",
      value: totalReturn,
      detail: `${item.component_count || 0} 个策略 · 累计 ${formatReturnPct(totalReturn, 2)}`
    };
  });

  function toggleComparison(portfolioId: string) {
    setComparisonIds((current) => {
      if (current.includes(portfolioId)) return current.filter((item) => item !== portfolioId);
      if (current.length >= 10) {
        message.warning("一次最多对比 10 个组合");
        return current;
      }
      return [...current, portfolioId];
    });
  }

  function selectAllComparisons() {
    const next = portfolios.slice(0, 10).map((item) => String(item.portfolio_id));
    if (portfolios.length > 10) message.info("已选择最近更新的 10 个组合");
    setComparisonIds(next);
  }

  function applyComparisonShortcut(range: "3m" | "6m" | "1y" | "all") {
    const next = shortcutDateRange(comparisonBounds, range);
    setComparisonStartDate(next.start);
    setComparisonEndDate(next.end);
  }

  const snapshot = detail?.snapshot || {};
  const metrics = snapshot.metrics || {};
  const componentSummaries = snapshot.components || [];
  const staleIds = detail?.stale_pool_item_ids || [];
  const componentColumns: ColumnsType<any> = [
    {
      title: UI_TEXT.term.componentStrategy,
      key: "strategy",
      width: 280,
      render: (_, row) => <div className="portfolio-component-name"><strong>{row.strategy_name}</strong><span>{row.strategy_version || "-"} · {row.pool_item_id}</span></div>
    },
    { title: UI_TEXT.term.tradingSymbol, dataIndex: "vt_symbol", width: 120 },
    { title: "原始权重", dataIndex: "weight", width: 100, align: "right", render: (value) => formatNumber(value, 2) },
    { title: "有效权重", dataIndex: "effective_weight", width: 110, align: "right", render: (value) => `${(Number(value) * 100).toFixed(2)}%` },
    { title: "现金天数", dataIndex: "cash_days", width: 100, align: "right", render: (value) => Number(value || 0) },
    { title: UI_TEXT.metric.totalReturn, dataIndex: "total_return", width: 110, align: "right", render: (value) => formatReturnPct(value, 2) },
    { title: "收益贡献", dataIndex: "weighted_contribution", width: 110, align: "right", render: (value) => formatReturnPct(value, 2) },
    { title: UI_TEXT.metric.maxDrawdown, dataIndex: "max_drawdown", width: 110, align: "right", render: (value) => formatReturnPct(value, 2) },
    { title: UI_TEXT.metric.tradeCount, dataIndex: "trade_count", width: 100, align: "right" },
    {
      title: "来源状态",
      key: "source_status",
      width: 100,
      render: (_, row) => staleIds.includes(row.pool_item_id) ? <Tag color="orange">已更新</Tag> : <Tag color="green">一致</Tag>
    }
  ];

  const componentDailyById = useMemo(() => {
    const grouped: Record<string, any[]> = {};
    for (const row of snapshot.component_daily || []) {
      const key = String(row.pool_item_id || "");
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push({
        date: row.date,
        close_price: 100,
        pre_close: 100,
        net_pnl: Number(row.daily_return || 0)
      });
    }
    return grouped;
  }, [snapshot.component_daily]);

  const curveRows = snapshot.daily_results || [];
  const curveBounds = curveDateBoundsForRows(curveRows);
  const filteredCurves = useMemo(() => {
    const curves: Record<string, any[]> = {
      portfolio: clampDateRange(curveRows, curveStartDate, curveEndDate)
    };
    for (const [key, rows] of Object.entries(componentDailyById)) {
      curves[key] = clampDateRange(rows, curveStartDate, curveEndDate);
    }
    return curves;
  }, [componentDailyById, curveEndDate, curveRows, curveStartDate]);
  const curveLabels = useMemo(() => ({
    portfolio: detail?.portfolio?.name || "组合",
    ...Object.fromEntries(componentSummaries.map((item: any) => [item.pool_item_id, item.strategy_name]))
  }), [componentSummaries, detail?.portfolio?.name]);
  const portfolioWindowReturn = curveSummary(filteredCurves.portfolio || []).strategy?.totalReturn;
  const curveControlItems: CurveControlItem[] = [
    { key: "portfolio", label: detail?.portfolio?.name || "组合", type: "strategy", value: portfolioWindowReturn, detail: `组合主曲线 · 累计 ${formatReturnPct(portfolioWindowReturn, 2)}` },
    ...componentSummaries.map((item: any) => {
      const poolItemId = String(item.pool_item_id);
      const totalReturn = curveSummary(filteredCurves[poolItemId] || []).strategy?.totalReturn;
      return {
        key: poolItemId,
        label: String(item.strategy_name),
        type: "strategy" as const,
        value: totalReturn,
        detail: `${item.vt_symbol || "-"} · 累计 ${formatReturnPct(totalReturn, 2)}`
      };
    })
  ];

  function applyShortcut(range: "3m" | "6m" | "1y" | "all") {
    const next = shortcutDateRange(curveBounds, range);
    setCurveStartDate(next.start);
    setCurveEndDate(next.end);
  }

  return (
    <section className="view is-active">
      <div className="hero-band library-hero-band portfolio-hero-band">
        <div>
          <p className="eyebrow">研究工作台</p>
          <h2>{UI_TEXT.page.portfolio}</h2>
          <p className="hero-copy">复用策略池历史快照，按固定权重汇总单位仓位收益；查看组合不会重新回测。</p>
        </div>
        <div className="hero-metrics">
          <div className="metric-tile"><div className="metric-value">{portfolios.length}</div><div className="metric-label">当前组合</div></div>
          <div className="metric-tile"><div className="metric-value">{portfolios.reduce((sum, item) => sum + Number(item.component_count || 0), 0)}</div><div className="metric-label">组成策略</div></div>
          <div className="metric-tile"><div className="metric-value">{portfolios.filter((item) => Number(item.stale_source_count || 0) > 0).length}</div><div className="metric-label">{UI_TEXT.status.pendingUpdate}</div></div>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div><h3>组合总览</h3><p>统一对比所有组合在共同有效区间内的累计收益表现。</p></div>
          <div className="portfolio-head-actions"><Button onClick={() => loadList().catch((error) => message.error(String(error)))}>刷新列表</Button><Button type="primary" onClick={openCreate}>新建组合</Button></div>
        </div>
        {portfolios.length > 0 ? (
          <div className={`portfolio-comparison-panel ${comparisonExpanded ? "is-expanded" : "is-collapsed"}`} aria-busy={comparisonLoading}>
            <button type="button" className="portfolio-comparison-toggle" onClick={() => setComparisonExpanded((current) => !current)} aria-expanded={comparisonExpanded}>
              <span><strong>不同组合累计收益对比</strong><small>默认展示最近更新的组合；曲线统一在所选组合的共同有效区间内从零开始累计。</small></span>
              <span className="portfolio-comparison-toggle-meta">
                <em className={`status-pill ${comparisonLoading ? "status-running" : "status-completed"}`}>{comparisonLoading ? "正在读取组合快照" : `已选择 ${comparisonIds.length} 个组合`}</em>
                <b><AppIcon name="chevron-down" size={18} /></b>
              </span>
            </button>
            {comparisonExpanded && (
              <div className="portfolio-comparison-body">
                <CurveControls
                  items={comparisonControlItems}
                  visibleKeys={comparisonIds}
                  startDate={comparisonStartDate}
                  endDate={comparisonEndDate}
                  bounds={comparisonBounds}
                  onToggle={toggleComparison}
                  onSelectAll={selectAllComparisons}
                  onClear={() => setComparisonIds([])}
                  onStartDateChange={setComparisonStartDate}
                  onEndDateChange={setComparisonEndDate}
                  onShortcut={applyComparisonShortcut}
                />
                {comparisonIds.length && Object.keys(comparisonDetails).length ? (
                  <div className="library-curve-panel unified-curve-panel">
                    <MultiVariantCurveChart
                      curves={comparisonCurves}
                      visibleKeys={comparisonIds.filter((portfolioId) => Boolean(comparisonDetails[portfolioId]))}
                      labels={comparisonLabels}
                      orderedKeys={comparisonControlItems.map((item) => item.key)}
                      showLegend
                      height={430}
                    />
                  </div>
                ) : <div className="empty-state">请选择至少一个组合进行对比。</div>}
              </div>
            )}
          </div>
        ) : <div className="empty-state">还没有组合。点击“新建组合”从策略池选择组成策略。</div>}
      </section>

      {detail && (
        <>
          <section className="band library-shell" aria-busy={loading}>
            <div className="library-section-head">
              <div className="portfolio-detail-heading">
                <h3>组合详情</h3>
                <label className="field">
                  <span>查看组合</span>
                  <Select
                    value={selectedId || undefined}
                    onChange={(portfolioId) => { setSelectedId(portfolioId); void loadDetail(portfolioId); }}
                    showSearch
                    optionFilterProp="label"
                    placeholder="搜索并选择组合"
                    options={portfolios.map((item) => ({
                      value: String(item.portfolio_id),
                      label: `${item.name} · 累计收益 ${formatReturnPct(item.metrics?.total_return, 2)}`
                    }))}
                  />
                </label>
                <p>{detail.portfolio?.description || "未填写组合说明。"}</p>
              </div>
              <div className="portfolio-head-actions">
                <Button onClick={() => downloadPortfolioCsv(selectedId, `${detail.portfolio?.name || selectedId}_收益明细.csv`).catch((error) => message.error(String(error)))}>下载收益明细</Button>
                <Button loading={refreshing} onClick={refreshSelected}>更新组合快照</Button>
                <Button onClick={openEdit}>编辑</Button>
                <Button danger onClick={archiveSelected}>归档</Button>
              </div>
            </div>
            {staleIds.length > 0 && <div className="portfolio-stale-alert"><strong>{staleIds.length} 个策略池来源已更新</strong><span>当前仍展示上次保存的组合快照。点击“更新组合快照”才会使用新来源计算，不会触发回测。</span></div>}
            <div className="library-metric-grid portfolio-metric-grid">
              <div className="library-metric-card positive"><span>{UI_TEXT.metric.totalReturn}</span><strong>{formatReturnPct(metrics.total_return, 2)}</strong></div>
              <div className="library-metric-card"><span>{UI_TEXT.metric.annualReturn}</span><strong>{formatReturnPct(metrics.annual_return, 2)}</strong></div>
              <div className="library-metric-card"><span>{UI_TEXT.metric.sharpe}</span><strong>{formatNumber(metrics.sharpe, 2)}</strong></div>
              <div className="library-metric-card negative"><span>{UI_TEXT.metric.maxDrawdown}</span><strong>{formatReturnPct(metrics.max_drawdown, 2)}</strong></div>
              <div className="library-metric-card"><span>{UI_TEXT.metric.calmar}</span><strong>{formatNumber(metrics.calmar, 2)}</strong></div>
              <div className="library-metric-card positive"><span>{UI_TEXT.metric.convertedPnl}</span><strong>{money(metrics.virtual_pnl)}</strong></div>
              <div className="library-metric-card"><span>{UI_TEXT.metric.tradeCount}</span><strong>{metrics.trade_count ?? "-"}</strong></div>
              <div className="library-metric-card"><span>盈 / 亏天数</span><strong>{metrics.winning_days ?? 0} / {metrics.losing_days ?? 0}</strong></div>
            </div>
            <div className="portfolio-definition-strip">
              <span><b>{UI_TEXT.metric.convertedCapital}</b>{money(detail.portfolio?.virtual_capital)}</span>
              <span><b>计算区间</b>{detail.portfolio?.start_date} 至 {detail.portfolio?.end_date}</span>
              <span><b>收益口径</b>单位仓位 · 固定权重 · 非复利</span>
              <span><b>缺失处理</b>对应权重按现金计，日收益为 0</span>
              <span><b>快照时间</b>{formatDate(snapshot.created_at)}</span>
            </div>
          </section>

          <section className="band library-shell">
            <div className="library-section-head"><div><h3>组合累计收益</h3><p>日期筛选只影响图表观察区间，不修改已保存的组合定义和正式指标。</p></div></div>
            <CurveControls
              items={curveControlItems}
              visibleKeys={visibleCurveKeys}
              startDate={curveStartDate}
              endDate={curveEndDate}
              bounds={curveBounds}
              onToggle={(key) => setVisibleCurveKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])}
              onSelectAll={() => setVisibleCurveKeys(curveControlItems.map((item) => item.key))}
              onClear={() => setVisibleCurveKeys([])}
              onStartDateChange={setCurveStartDate}
              onEndDateChange={setCurveEndDate}
              onShortcut={applyShortcut}
            />
            {visibleCurveKeys.length ? <div className="library-curve-panel unified-curve-panel"><MultiVariantCurveChart curves={filteredCurves} visibleKeys={visibleCurveKeys} labels={curveLabels} orderedKeys={curveControlItems.map((item) => item.key)} showLegend={false} height={430} /></div> : <div className="empty-state">请选择至少一条曲线。</div>}
          </section>

          <section className="band library-shell">
            <div className="library-section-head"><div><h3>组成策略绩效与贡献</h3><p>收益贡献 = 组成策略累计收益 × 有效权重；无数据日期保持原权重并按现金计息 0。</p></div></div>
            <div className="library-table-wrap"><Table rowKey="pool_item_id" columns={componentColumns} dataSource={componentSummaries} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 1230 }} className="workbench-table" /></div>
          </section>
        </>
      )}

      <Modal
        title={editingId ? "编辑组合" : "新建组合"}
        width={900}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={savePortfolio}
        confirmLoading={saving}
        okText={editingId ? "保存并生成组合快照" : "创建组合"}
        cancelText="取消"
      >
        <div className="portfolio-editor-grid">
          <label className="field"><span>组合名称</span><Input value={editor.name} maxLength={80} onChange={(event) => setEditor((current) => ({ ...current, name: event.target.value }))} placeholder="例如：转债低波动组合" /></label>
          <label className="field"><span>{UI_TEXT.metric.convertedCapital}</span><InputNumber min={1} precision={2} value={editor.virtual_capital} onChange={(value) => setEditor((current) => ({ ...current, virtual_capital: Number(value || 0) }))} /></label>
          <label className="field span-2"><span>组合说明</span><Input.TextArea value={editor.description} maxLength={1000} autoSize={{ minRows: 2, maxRows: 4 }} onChange={(event) => setEditor((current) => ({ ...current, description: event.target.value }))} /></label>
          <label className="field"><span>开始日期（留空取最早数据日）</span><Input type="date" value={editor.start_date} onChange={(event) => setEditor((current) => ({ ...current, start_date: event.target.value }))} /></label>
          <label className="field"><span>结束日期（留空取最晚数据日）</span><Input type="date" value={editor.end_date} onChange={(event) => setEditor((current) => ({ ...current, end_date: event.target.value }))} /></label>
          <label className="field"><span>搜索交易标的</span><Select value={editorSymbol || undefined} onChange={setEditorSymbol} showSearch allowClear optionFilterProp="label" placeholder="先搜索并选择交易标的" options={editorSymbols.map((symbol) => ({ value: symbol, label: symbol }))} /></label>
          <label className="field"><span>选择{UI_TEXT.term.poolSnapshot}</span><Select mode="multiple" value={editorSymbolComponentIds} onChange={updateSelectedComponents} disabled={!editorSymbol} showSearch optionFilterProp="label" placeholder={editorSymbol ? "选择该标的下的一个或多个策略" : "请先选择交易标的"} options={editorPoolItems.map((item) => ({ value: String(item.pool_item_id), label: strategyLabel(item) }))} /></label>
        </div>
        <div className="portfolio-weight-note">先按交易标的筛选并添加策略；切换标的不会清空已选策略。原始权重只表达相对比例，保存时会归一化；无数据日期对应权重按现金计、收益为 0，不会重新分配给其他策略。</div>
        <Table rowKey="pool_item_id" columns={editorColumns} dataSource={sortedEditorComponents} pagination={false} size="small" scroll={{ y: 220 }} className="portfolio-editor-table" />
      </Modal>

    </section>
  );
}
