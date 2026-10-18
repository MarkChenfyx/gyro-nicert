import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Select, Table, Tabs, Tag, message } from "antd";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getExecutorOverview, getExecutorRuns } from "../api";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const STRATEGY_LABEL: Record<string, string> = {
  rot_hk_dividend: "港股通高股息",
  rot_nikkei: "日经225",
  rot_sp500: "标普500",
  rot_hsi: "恒生指数",
  rot_hs_biotech: "恒生生物科技"
};

const ALERT_LABEL: Record<string, { label: string; color: string }> = {
  order_rejected: { label: "委托被拒", color: "red" },
  order_blocked: { label: "风控拦截委托", color: "orange" },
  intent_blocked: { label: "换仓被拦截", color: "orange" },
  intent_expired: { label: "换仓过期", color: "gold" },
  gateway_down: { label: "网关断开", color: "red" },
  unknown_or_duplicate_trade: { label: "未知成交", color: "red" },
  start: { label: "启动", color: "blue" }
};

const label = (name: string) => STRATEGY_LABEL[name] || name;

function actionText(action: string | undefined) {
  if (!action || action === "none") return "不动";
  if (action.startsWith("target:")) return `换到 ${action.slice(7)}`;
  if (action === "skip:data") return "数据不足，跳过";
  if (action === "skip:intent") return "换仓进行中";
  return action;
}
const num = (v: unknown, d = 0) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? "-" : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d }));

function Curves({ series, unit }: { series: { name: string; points: [string, number][] }[]; unit: string }) {
  const element = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    const days = Array.from(new Set(series.flatMap(s => s.points.map(p => p[0])))).sort();
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => `${Number(v ?? 0).toFixed(2)}${unit}` },
      legend: { top: 0 },
      grid: { left: 56, right: 20, top: 36, bottom: 32 },
      xAxis: { type: "category", boundaryGap: false, data: days },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => `${v}${unit}` } },
      series: series.map(s => {
        const map = new Map(s.points);
        return { name: s.name, type: "line", showSymbol: false, connectNulls: false, data: days.map(d => (map.has(d) ? map.get(d) : null)) };
      })
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [series, unit]);
  return <div className="broker-asset-curve" ref={element} />;
}

export default function ExecutionPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [run, setRun] = useState<string>("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const loadRuns = useCallback(async () => {
    const payload = await getExecutorRuns();
    const items = payload?.items || [];
    setRuns(items);
    setRun(current => current || (items[0]?.id ?? ""));
  }, []);

  const loadOverview = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    try {
      setData(await getExecutorOverview(id));
    } catch (error) {
      message.error(String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRuns().catch(error => message.error(String(error))); }, [loadRuns]);
  useEffect(() => { loadOverview(run); }, [run, loadOverview]);
  useEffect(() => {
    const kind = runs.find(r => r.id === run)?.kind;
    if (kind !== "live" && kind !== "paper") return;
    const timer = window.setInterval(() => loadOverview(run), 30000);
    return () => window.clearInterval(timer);
  }, [run, runs, loadOverview]);

  const strategies: any[] = data?.strategies || [];
  const excessCurves = data?.report?.excess_curves as Record<string, Record<string, number>> | undefined;
  const curves = useMemo(() => {
    if (excessCurves && Object.keys(excessCurves).length) {
      return { unit: "%", title: "累计超额（相对组内等权一直持有）", series: Object.entries(excessCurves).map(([name, pts]) => ({ name: label(name), points: Object.entries(pts) as [string, number][] })) };
    }
    return {
      unit: "%", title: "单位仓位累计收益（简单累加）",
      series: strategies.map(s => ({ name: label(s.name), points: (s.series || []).map((p: any) => [p.day, p.return_pct] as [string, number]) }))
    };
  }, [excessCurves, strategies]);

  const alerts: any[] = (data?.alerts || []).filter((a: any) => a.kind !== "start" || (a.payload?.problems || []).length);
  const summary = data?.report?.summary || {};
  const totalEquity = strategies.reduce((t, s) => t + Number(s.equity || 0), 0);
  const totalCash = strategies.reduce((t, s) => t + Number(s.cash || 0), 0);

  return (
    <section className="page-shell">
      <div className="page-head">
        <div>
          <h2>执行监控</h2>
          <p>交易引擎的运行情况：每组持有哪只、收益和超额、今天换了几次仓、有没有报警。实盘和纸面每 30 秒自动刷新。</p>
        </div>
        <div className="portfolio-head-actions">
          <Select style={{ minWidth: 260 }} value={run || undefined} placeholder="选择运行记录" onChange={setRun}
            options={runs.map(r => ({ value: r.id, label: `${r.label}（更新于 ${String(r.updated).replace("T", " ").slice(0, 16)}）` }))} />
          <Button onClick={() => { loadRuns(); loadOverview(run); }} loading={loading}>刷新</Button>
        </div>
      </div>

      {!runs.length ? (
        <section className="band library-shell"><Empty description="还没有引擎运行记录。回测、纸面或实盘运行后会出现在这里。" /></section>
      ) : (
        <>
          <section className="band library-shell">
            <div className="library-section-head">
              <div>
                <h3>概览</h3>
                <p>最近交易日 {data?.last_day || "-"}</p>
              </div>
              <span className={`status-pill ${alerts.some(a => ["order_rejected", "gateway_down", "unknown_or_duplicate_trade"].includes(a.kind)) ? "status-failed" : "status-completed"}`}>
                {alerts.length ? `${alerts.length} 条提醒` : "运行正常"}
              </span>
            </div>
            <div className="library-metric-grid portfolio-metric-grid">
              <div className="library-metric-card"><span>账本权益</span><strong>¥ {num(totalEquity)}</strong></div>
              <div className="library-metric-card"><span>账本资金余额</span><strong>¥ {num(totalCash)}</strong></div>
              <div className="library-metric-card"><span>策略数</span><strong>{strategies.length}</strong></div>
            </div>
            {curves.series.length > 0 && (<><div className="broker-table-caption">{curves.title}</div><Curves series={curves.series} unit={curves.unit} /></>)}
          </section>

          <section className="band library-shell">
            <div className="library-section-head"><div><h3>各组状态</h3><p>z = 当前溢价减自身 20 天中位数，越小越便宜；持有那只比最便宜的高出阈值以上就会换仓。</p></div></div>
            <Table size="small" rowKey="name" pagination={false} scroll={{ x: 980 }} dataSource={strategies} columns={[
              { title: "组", dataIndex: "name", render: (v: string) => <strong>{label(v)}</strong> },
              { title: "当前持有", dataIndex: "positions", render: (p: Record<string, number>) => Object.entries(p || {}).map(([s, q]) => `${s} × ${num(q)}`).join("，") || "空仓" },
              { title: "权益", dataIndex: "equity", align: "right", render: (v: number) => num(v) },
              { title: "单位仓位累计收益", dataIndex: "return_pct", align: "right", render: (v: number | null) => v === null ? "-" : <span className={v >= 0 ? "broker-value positive" : "broker-value negative"}>{num(v, 2)}%</span> },
              { title: "年化超额", dataIndex: "name", align: "right", render: (n: string) => (summary[n]?.["年化超额%"] !== undefined ? `${num(summary[n]["年化超额%"], 2)}%` : "-") },
              { title: "最近一日换仓", dataIndex: "today", align: "right", render: (t: Record<string, number>) => num((t || {}).intent_done || 0) },
              { title: "最新 z 值", dataIndex: "latest_decision", render: (d: any) => Object.entries(d?.z || {}).sort((a: any, b: any) => a[1] - b[1]).map(([s, z]: any) => `${s.slice(0, 6)} ${Number(z).toFixed(2)}`).join(" / ") || "-" },
              { title: "最新动作", dataIndex: "latest_decision", render: (d: any) => (d?.time ? `${String(d.time).replace("T", " ").slice(5, 16)} ${actionText(d.action)}` : "-") }
            ]} />
          </section>

          <section className="band library-shell">
            <Tabs items={[
              {
                key: "alerts", label: `提醒 ${alerts.length}`,
                children: <Table size="small" rowKey={(r: any) => `${r.time}-${r.kind}-${r.strategy}`} pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={alerts} columns={[
                  { title: "时间", dataIndex: "time", width: 160, render: (v: string) => String(v).replace("T", " ").slice(0, 19) },
                  { title: "类型", dataIndex: "kind", width: 120, render: (k: string) => <Tag color={ALERT_LABEL[k]?.color}>{ALERT_LABEL[k]?.label || k}</Tag> },
                  { title: "组", dataIndex: "strategy", width: 120, render: (v: string) => (v ? label(v) : "-") },
                  { title: "说明", dataIndex: "payload", render: (p: any) => p?.reason || p?.message || (p?.problems || []).join("；") || JSON.stringify(p?.positions || p || {}) }
                ]} />
              },
              {
                key: "trades", label: `最近成交 ${(data?.trades || []).length}`,
                children: <Table size="small" rowKey={(r: any) => `${r.time}-${r.symbol}-${r.side}-${r.volume}`} pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={data?.trades || []} columns={[
                  { title: "时间", dataIndex: "time", width: 160, render: (v: string) => String(v).replace("T", " ").slice(0, 19) },
                  { title: "组", dataIndex: "strategy", render: label },
                  { title: "标的", dataIndex: "symbol" },
                  { title: "方向", dataIndex: "side", render: (v: string) => <Tag color={v === "BUY" ? "red" : "green"}>{v === "BUY" ? "买入" : "卖出"}</Tag> },
                  { title: "价格", dataIndex: "price", align: "right", render: (v: number) => num(v, 3) },
                  { title: "数量", dataIndex: "volume", align: "right", render: (v: number) => num(v) },
                  { title: "手续费", dataIndex: "fee", align: "right", render: (v: number) => num(v, 2) }
                ]} />
              },
              {
                key: "orders", label: `最近委托 ${(data?.orders || []).length}`,
                children: <Table size="small" rowKey={(r: any) => `${r.created}-${r.symbol}-${r.side}-${r.volume}-${r.status}`} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 900 }} dataSource={data?.orders || []} columns={[
                  { title: "报单时间", dataIndex: "created", width: 160, render: (v: string) => String(v).replace("T", " ").slice(0, 19) },
                  { title: "组", dataIndex: "strategy", render: label },
                  { title: "标的", dataIndex: "symbol" },
                  { title: "方向", dataIndex: "side", render: (v: string) => (v === "BUY" ? "买入" : "卖出") },
                  { title: "限价", dataIndex: "price", align: "right", render: (v: number) => num(v, 3) },
                  { title: "数量", dataIndex: "volume", align: "right", render: (v: number) => num(v) },
                  { title: "已成交", dataIndex: "filled", align: "right", render: (v: number) => num(v) },
                  { title: "状态", dataIndex: "status" },
                  { title: "原因", dataIndex: "reason", ellipsis: true }
                ]} />
              }
            ]} />
          </section>
        </>
      )}
    </section>
  );
}
