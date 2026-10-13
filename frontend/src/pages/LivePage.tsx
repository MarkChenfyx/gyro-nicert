import { useCallback, useEffect, useState } from "react";
import { Button, Collapse, Input, Modal, Table, Tabs, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import LiveReplayDetails from "../components/LiveReplayDetails";
import BrokerAssetCurve from "../components/BrokerAssetCurve";
import {
  captureBrokerDbf,
  createLiveSource,
  deleteLiveSource,
  getLiveAutomationStatus,
  getBrokerOverview,
  getLiveLocalStatus,
  getLiveRecord,
  getLiveSource,
  importLiveSnapshot,
  listLiveSources,
  trackLiveDay
} from "../api";

const STATUS_META: Record<string, { label: string; color: string; hint: string }> = {
  MATCH: { label: "一致", color: "green", hint: "回放持仓与实盘一致" },
  MISMATCH: { label: "有差异", color: "red", hint: "回放持仓与实盘不一致，需要排查" },
  DATA_GAP: { label: "行情不全", color: "orange", hint: "本地行情有缺口，本次不下结论" },
  CONFIG_CHANGED: { label: "配置已变", color: "purple", hint: "实盘参数或标的变了，需重新建立实盘源" },
  NO_STATE: { label: "缺状态", color: "orange", hint: "快照里没有这个策略的状态" },
  NEW_INSTANCE: { label: "新增策略", color: "blue", hint: "实盘新加的策略，尚未绑定" },
  REPLAY_ERROR: { label: "回放失败", color: "red", hint: "策略回放过程出错" }
};

function todayInBeijing(): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function num(value: unknown, digits = 0) {
  const parsed = Number(value);
  if (value === null || value === undefined || !Number.isFinite(parsed)) return "-";
  return parsed.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(value: unknown, digits = 2) {
  const parsed = Number(value);
  const tone = !Number.isFinite(parsed) || parsed === 0 ? "" : parsed > 0 ? "positive" : "negative";
  return <span className={`broker-value ${tone}`}>{num(value, digits)}</span>;
}

const STATUS_ORDER: Record<string, number> = { MISMATCH: 0, REPLAY_ERROR: 1, DATA_GAP: 2, NO_STATE: 3, CONFIG_CHANGED: 4, NEW_INSTANCE: 5, MATCH: 9 };

type DayCell = { date: string; kind: string; label: string; hint: string };

const DAY_KIND: Record<string, string> = {
  match: "全部一致", mismatch: "有差异", unresolved: "未能判定", baseline: "仅快照",
  closed: "休市", missing: "未记录", pending: "待记录"
};

function isoDay(value: Date): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(value);
}

// 最近若干周的工作日各一格：已跟踪（一致/有差异/未判定）、仅快照、休市、未记录。
function recordCalendar(records: any[], snapshots: any[], closedDays: string[], weeks = 8): DayCell[] {
  const today = todayInBeijing();
  const byDate = new Map(records.map((row) => [String(row.trade_date), row]));
  const snapshotDates = new Set(snapshots.map((row) => String(row.trade_date)));
  const closed = new Set(closedDays);
  const anchor = new Date(`${today}T12:00:00+08:00`);
  const monday = anchor.getTime() - ((anchor.getUTCDay() + 6) % 7) * 86400000;
  const cells: DayCell[] = [];
  for (let week = weeks - 1; week >= 0; week -= 1) {
    for (let weekday = 0; weekday < 5; weekday += 1) {
      const date = isoDay(new Date(monday - week * 7 * 86400000 + weekday * 86400000));
      const record = byDate.get(date);
      const summary = record?.summary || {};
      let kind = "missing";
      if (date > today) kind = "future";
      else if (closed.has(date)) kind = "closed";
      else if (record) kind = Number(summary.mismatch) > 0 ? "mismatch" : Number(summary.match) > 0 ? "match" : "unresolved";
      else if (snapshotDates.has(date)) kind = "baseline";
      else if (date === today) kind = "pending";
      const hint = record ? `一致 ${summary.match ?? 0} · 有差异 ${summary.mismatch ?? 0} · 未判定 ${summary.unresolved ?? 0}` : DAY_KIND[kind] || "";
      cells.push({ date, kind, label: date.slice(5), hint });
    }
  }
  return cells;
}

export default function LivePage() {
  const [localStatus, setLocalStatus] = useState<any>(null);
  const [automation, setAutomation] = useState<any>(null);
  const [broker, setBroker] = useState<any>(null);
  const [sources, setSources] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [record, setRecord] = useState<any>(null);
  const [tradeDate, setTradeDate] = useState("");
  const [sourceName, setSourceName] = useState("实盘组合");
  const [busy, setBusy] = useState("");
  const [replayInstance, setReplayInstance] = useState<string | null>(null);

  useEffect(() => { setReplayInstance(null); }, [record?.record_id]);

  const loadSources = useCallback(async () => {
    const [status, list, automatic, brokerOverview] = await Promise.all([getLiveLocalStatus(), listLiveSources(), getLiveAutomationStatus(), getBrokerOverview()]);
    setLocalStatus(status);
    setAutomation(automatic);
    setBroker(brokerOverview);
    // 状态文件的北京日期就是它代表的交易日，直接当默认值，避免手填错日期。
    setTradeDate((current) => current || String(status?.state_trade_date || "") || todayInBeijing());
    const items = list?.items || [];
    setSources(items);
    if (items.length) {
      const payload = await getLiveSource(String(items[0].source_id));
      setDetail(payload);
      setRecord(payload?.latest || null);
    } else {
      setDetail(null);
      setRecord(null);
    }
  }, []);

  useEffect(() => {
    loadSources().catch((error) => message.error(String(error)));
  }, [loadSources]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      getLiveAutomationStatus().then(setAutomation).catch(() => undefined);
    }, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const sourceId = String(detail?.source?.source_id || "");

  async function withBusy(key: string, action: () => Promise<void>) {
    setBusy(key);
    try {
      await action();
    } catch (error) {
      message.error(String(error));
    } finally {
      setBusy("");
    }
  }

  const createSource = () =>
    withBusy("create", async () => {
      await createLiveSource({ trade_date: tradeDate, name: sourceName.trim() || "实盘组合" });
      await loadSources();
      message.success("已从本机实盘目录建立实盘源");
    });

  const runTracking = () =>
    withBusy("track", async () => {
      if (!detail?.snapshots?.some((item: any) => item.trade_date === tradeDate)) {
        await importLiveSnapshot(sourceId, tradeDate);
      }
      const result = await trackLiveDay(sourceId, tradeDate);
      await loadSources();
      setRecord(result);
      const summary = result?.summary || {};
      message.success(`跟踪完成：一致 ${summary.match || 0}，有差异 ${summary.mismatch || 0}`);
    });

  const captureBroker = () =>
    withBusy("broker", async () => {
      const payload = await captureBrokerDbf();
      setBroker(payload?.overview || null);
      message.success(payload?.capture?.status === "refreshed" ? "DBF 内容没有变化，已重新导入" : "券商数据已归档并导入");
    });

  function confirmDiscard() {
    Modal.confirm({
      title: "弃用这个实盘源？",
      content: "会删除它的策略绑定、每日快照和跟踪记录。实盘目录里的文件不受影响，可以重新建立。",
      okText: "弃用",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () =>
        deleteLiveSource(sourceId)
          .then(loadSources)
          .then(() => message.success("已弃用，可以重新建立实盘源"))
          .catch((error) => message.error(String(error)))
    });
  }

  const openRecord = (date: string) =>
    withBusy("record", async () => {
      setRecord(await getLiveRecord(sourceId, date));
    });

  const columns: ColumnsType<any> = [
    { title: "策略实例", dataIndex: "instance_name", width: 300, ellipsis: true, render: value => <Button type="link" onClick={() => setReplayInstance(String(value))}>{value}</Button> },
    { title: "标的", dataIndex: "vt_symbol", width: 118 },
    { title: "实盘手数", dataIndex: "fixed_size", width: 96, align: "right", render: (v) => num(v) },
    { title: "实盘持仓", dataIndex: "actual_pos", width: 104, align: "right", render: (v) => num(v) },
    { title: "回放持仓", dataIndex: "replay_pos", width: 104, align: "right", render: (v) => num(v) },
    {
      title: "差异",
      dataIndex: "difference",
      width: 96,
      align: "right",
      render: (value) => {
        if (value === null || value === undefined) return "-";
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) return "-";
        if (parsed === 0) return <span>0</span>;
        return <strong style={{ color: "#be123c" }}>{num(parsed)}</strong>;
      }
    },
    {
      title: "当日回放成交",
      dataIndex: "replay_trades",
      width: 116,
      align: "right",
      render: (value, row) => <Button type="link" size="small" onClick={() => setReplayInstance(String(row.instance_name))}>
        {(Array.isArray(value) ? value : []).filter(trade => String(trade.datetime || "").slice(0, 10) === record?.trade_date).length} 笔 · 查看
      </Button>
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 108,
      render: (value) => {
        const meta = STATUS_META[String(value)] || { label: String(value || "未知"), color: "default", hint: "" };
        return <Tag color={meta.color} title={meta.hint}>{meta.label}</Tag>;
      }
    },
    { title: "说明", dataIndex: "message", ellipsis: true }
  ];

  const summary = record?.summary || {};
  const rows = [...(record?.rows || [])].sort(
    (a: any, b: any) => (STATUS_ORDER[String(a.status)] ?? 5) - (STATUS_ORDER[String(b.status)] ?? 5)
  );
  const available = Boolean(localStatus?.available);
  const alreadyRecorded = Boolean(localStatus?.recorded_as);
  const today = todayInBeijing();
  const closedDays: string[] = automation?.closed_days || [];
  const tradingToday = new Date().getDay() % 6 !== 0 && !closedDays.includes(today);
  const latestRecord = detail?.records?.[0];
  const calendar = recordCalendar(detail?.records || [], detail?.snapshots || [], closedDays);
  const pastDays = calendar.filter((day) => !["future", "closed", "pending"].includes(day.kind));
  const recordedCount = pastDays.filter((day) => !["missing", "baseline"].includes(day.kind)).length;
  const alerts: string[] = [];
  if (localStatus && !available) alerts.push(`本机实盘目录不可用：${localStatus.message || "请检查 .env 配置"}`);
  if (available && tradingToday && localStatus.state_trade_date !== today) {
    alerts.push(`状态文件还停在 ${localStatus.state_trade_date || "-"}（写于 ${String(localStatus.state_modified_at || "").replace("T", " ").slice(0, 16)}）。收盘后在 VeighNa 点“全部停止”，平台会在 23:00 前自动补记今天。`);
  }
  if (broker?.source?.available && tradingToday && broker?.dates?.account !== today) {
    alerts.push(`券商 DBF 最新日期是 ${broker?.dates?.account || "-"}，今天还没采集到；确认 QMT 保持登录并开着自动导出。`);
  }
  if (automation?.last_status === "failed") alerts.push(`自动跟踪失败：${automation.last_message || "未知原因"}`);

  return (
    <section className="page-shell">
      <div className="page-head">
        <div>
          <h2>实盘跟踪</h2>
          <p>
            每天以实盘前一交易日收盘的真实状态为起点，用平台引擎重放当天，
            再与当天实盘持仓比对。这里的结果不会写入策略池，也不影响任何研究产物。
          </p>
        </div>
        <div className="portfolio-head-actions">
          <Button onClick={() => loadSources().catch((error) => message.error(String(error)))}>刷新</Button>
        </div>
      </div>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>今日概览</h3>
            <p>{today} · 最近一次跟踪 {latestRecord?.trade_date || "尚无"} · 最近 8 周 {pastDays.length} 个交易日中跟踪了 {recordedCount} 天</p>
          </div>
          <span className={`status-pill ${alerts.length ? "status-failed" : "status-completed"}`}>{alerts.length ? `${alerts.length} 项需处理` : "运行正常"}</span>
        </div>
        <div className="library-metric-grid portfolio-metric-grid">
          <div className="library-metric-card"><span>最近跟踪日</span><strong>{latestRecord?.trade_date || "-"}</strong></div>
          <div className="library-metric-card positive"><span>持仓一致</span><strong>{latestRecord?.summary?.match ?? "-"}</strong></div>
          <div className="library-metric-card negative"><span>有差异</span><strong>{latestRecord?.summary?.mismatch ?? "-"}</strong></div>
          <div className="library-metric-card"><span>未能判定</span><strong>{latestRecord?.summary?.unresolved ?? "-"}</strong></div>
          <div className="library-metric-card"><span>账户总资产 · {broker?.dates?.account || "-"}</span><strong>{broker?.account ? `¥ ${num(broker.account.total_assets, 0)}` : "-"}</strong></div>
        </div>
        {alerts.length > 0 && <ul className="live-alerts">{alerts.map((text) => <li key={text}>{text}</li>)}</ul>}
      </section>

      {Boolean(detail) && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>记录日历</h3>
              <p>每个交易日一格；点击已跟踪的日子查看当天比对。</p>
            </div>
            <div className="portfolio-head-actions">
              <label className="field"><span>手动跟踪交易日</span>
                <Input type="date" max={today} value={tradeDate} onChange={(event) => setTradeDate(event.target.value)} />
              </label>
              <Button type="primary" loading={busy === "track"} onClick={runTracking} disabled={!sourceId}>
                {detail?.snapshots?.some((item: any) => item.trade_date === tradeDate) ? "使用已存快照重新回放" : "记录收盘快照并跟踪"}
              </Button>
            </div>
          </div>
          <div className="live-calendar">
            {["一", "二", "三", "四", "五"].map((name) => <span key={name} className="live-calendar-head">周{name}</span>)}
            {calendar.map((day) => (
              <button
                key={day.date}
                type="button"
                className={`live-day live-day-${day.kind}${record?.trade_date === day.date ? " selected" : ""}`}
                title={`${day.date} · ${day.hint}`}
                disabled={!["match", "mismatch", "unresolved"].includes(day.kind)}
                onClick={() => openRecord(day.date)}
              >
                {day.label}
              </button>
            ))}
          </div>
          <div className="live-calendar-legend">
            {["match", "mismatch", "unresolved", "baseline", "missing", "closed"].map((kind) => (
              <span key={kind}><i className={`live-day-${kind}`} />{DAY_KIND[kind]}</span>
            ))}
          </div>
        </section>
      )}

          {Boolean(record?.trade_date) && (
            <section className="band library-shell">
              <div className="library-section-head">
                <div>
                  <h3>{record.trade_date} 跟踪结果</h3>
                  <p>回放起点为 {summary.prior_date || "-"} 收盘状态；该回放区间共成交 {summary.trade_count || 0} 笔。</p>
                </div>
                <span className="status-pill status-completed">{summary.total || rows.length} 个策略</span>
              </div>
              <div className="library-metric-grid portfolio-metric-grid">
                <div className="library-metric-card positive"><span>持仓一致</span><strong>{summary.match ?? 0}</strong></div>
                <div className="library-metric-card negative"><span>有差异</span><strong>{summary.mismatch ?? 0}</strong></div>
                <div className="library-metric-card"><span>未能判定</span><strong>{summary.unresolved ?? 0}</strong></div>
                <div className="library-metric-card"><span>目标日回放成交</span><Button type="link" onClick={() => setReplayInstance("")}>
                  {rows.reduce((total: number, row: any) => total + (row.replay_trades || []).filter((trade: any) => String(trade.datetime || "").slice(0, 10) === record.trade_date).length, 0)} 笔 · 查看成交与信号
                </Button></div>
              </div>
              <div className="library-table-wrap">
                <Table
                  rowKey={(row) => String(row.binding_id || row.instance_name)}
                  columns={columns}
                  dataSource={rows}
                  pagination={{ pageSize: 15, showSizeChanger: false }}
                  scroll={{ x: 1180 }}
                  className="workbench-table"
                />
              </div>
            </section>
          )}

          {Boolean(detail?.records?.length) && (
            <section className="band library-shell">
              <div className="library-section-head">
                <div><h3>历史跟踪记录</h3><p>点击某一天查看当时的比对明细。</p></div>
              </div>
              <div className="library-table-wrap">
                <Table
                  rowKey="record_id"
                  size="small"
                  columns={[
                    { title: "交易日", dataIndex: "trade_date", width: 130 },
                    { title: "策略数", width: 90, align: "right", render: (_, row: any) => num(row.summary?.total) },
                    { title: "一致", width: 80, align: "right", render: (_, row: any) => num(row.summary?.match) },
                    { title: "有差异", width: 90, align: "right", render: (_, row: any) => num(row.summary?.mismatch) },
                    { title: "未判定", width: 90, align: "right", render: (_, row: any) => num(row.summary?.unresolved) },
                    {
                      title: "",
                      width: 90,
                      render: (_, row: any) => (
                        <Button size="small" loading={busy === "record"} onClick={() => openRecord(String(row.trade_date))}>
                          查看
                        </Button>
                      )
                    }
                  ]}
                  dataSource={detail.records}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  className="workbench-table"
                />
              </div>
            </section>
          )}
      <section className="band library-shell broker-panel">
        <div className="library-section-head">
          <div>
            <h3>券商账户</h3>
            <p>只读采集 QMT 交易端导出的 DBF，保存真实账户、持仓、委托和成交。每项日期独立显示，不把旧数据当成当天数据。</p>
          </div>
          <div className="portfolio-head-actions">
            <span className={`status-pill ${broker?.source?.available ? "status-completed" : "status-failed"}`}>
              {broker?.source?.available ? "数据目录可读" : "尚未连接"}
            </span>
            <Button type="primary" loading={busy === "broker"} disabled={!broker?.source?.available} onClick={captureBroker}>立即采集</Button>
          </div>
        </div>
        {broker?.account ? (
          <>
            <div className="library-metric-grid portfolio-metric-grid">
              <div className="library-metric-card"><span>总资产 · {broker.dates?.account || "-"}</span><strong>¥ {num(broker.account.total_assets, 2)}</strong></div>
              <div className="library-metric-card"><span>可用资金</span><strong>¥ {num(broker.account.available_cash, 2)}</strong></div>
              <div className="library-metric-card"><span>总市值</span><strong>¥ {num(broker.account.total_market_value, 2)}</strong></div>
              <div className={`library-metric-card ${Number(broker.account.profit_loss) >= 0 ? "positive" : "negative"}`}><span>账户盈亏</span><strong>¥ {num(broker.account.profit_loss, 2)}</strong></div>
            </div>
            {broker.asset_curve?.length > 1 ? <BrokerAssetCurve rows={broker.asset_curve} /> : <div className="broker-note">目前只有 {broker.dates?.account || "一个"} 交易日的快照；每天归档后会逐步形成账户资产曲线。</div>}
            <Tabs
              items={[
                {
                  key: "positions", label: `持仓 ${broker.positions?.length || 0}`,
                  children: <Table size="small" rowKey="vt_symbol" pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={broker.positions || []} columns={[
                    { title: "标的", dataIndex: "vt_symbol" },
                    { title: "持仓", dataIndex: "quantity", align: "right", render: (value) => num(value) },
                    { title: "可用", dataIndex: "available_quantity", align: "right", render: (value) => num(value) },
                    { title: "成本价", dataIndex: "cost_price", align: "right", render: (value) => num(value, 4) },
                    { title: "市值", dataIndex: "market_value", align: "right", render: (value) => num(value, 2) },
                    { title: "盈亏", dataIndex: "profit_loss", align: "right", render: (value) => signed(value) }
                  ]} />
                },
                {
                  key: "orders", label: `委托 ${broker.orders?.length || 0} · ${broker.dates?.orders || "无日期"}`,
                  children: <Table size="small" rowKey="order_key" scroll={{ x: 900 }} pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={broker.orders || []} columns={[
                    { title: "时间", dataIndex: "order_time", width: 100 }, { title: "标的", dataIndex: "vt_symbol", width: 120 },
                    { title: "方向", dataIndex: "action", width: 80 }, { title: "委托价", dataIndex: "order_price", align: "right", render: (value) => num(value, 4) },
                    { title: "委托量", dataIndex: "order_quantity", align: "right", render: (value) => num(value) }, { title: "成交量", dataIndex: "filled_quantity", align: "right", render: (value) => num(value) },
                    { title: "状态", dataIndex: "status", width: 110 }, { title: "拒绝原因", dataIndex: "reject_reason", ellipsis: true }
                  ]} />
                },
                {
                  key: "deals", label: `成交 ${broker.deals?.length || 0} · ${broker.dates?.deals || "无日期"}`,
                  children: <Table size="small" rowKey="deal_key" scroll={{ x: 760 }} pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={broker.deals || []} columns={[
                    { title: "时间", dataIndex: "deal_time", width: 100 }, { title: "标的", dataIndex: "vt_symbol", width: 120 },
                    { title: "方向", dataIndex: "action", width: 80 }, { title: "成交价", dataIndex: "price", align: "right", render: (value) => num(value, 4) },
                    { title: "数量", dataIndex: "quantity", align: "right", render: (value) => num(value) }, { title: "金额", dataIndex: "amount", align: "right", render: (value) => num(value, 2) },
                    { title: "费用", dataIndex: "fee", align: "right", render: (value) => num(value, 2) }
                  ]} />
                },
                {
                  key: "settlements", label: `交割单 ${broker.settlements?.length || 0}`,
                  children: <>
                    <div className="broker-note">交割单是 T+1 的已清算记录，真实手续费和印花税只有这里才有；当日成交里的费用是 0。下表费率可与回测参数对照。</div>
                    <div className="broker-table-caption">按标的的实际费率<em>回测当前统一使用 0.45 bp</em></div>
                    <Table size="small" rowKey="vt_symbol" pagination={false} dataSource={broker.fee_summary || []} columns={[
                      { title: "标的", dataIndex: "vt_symbol" }, { title: "笔数", dataIndex: "trades", align: "right" },
                      { title: "成交额", dataIndex: "amount", align: "right", render: (value) => num(value, 2) },
                      { title: "费用合计", dataIndex: "fee", align: "right", render: (value) => num(value, 2) },
                      { title: "实际费率", dataIndex: "fee_bp", align: "right", render: (value) => value === null || value === undefined ? "-" : `${num(value, 3)} bp` },
                      { title: "区间", dataIndex: "first_date", render: (value, row: any) => `${value || "-"} ~ ${row.last_date || "-"}` }
                    ]} />
                    <div className="broker-table-caption">交割明细<em>最近 {broker.settlements?.length || 0} 条</em></div>
                    <Table size="small" rowKey="settlement_key" scroll={{ x: 900 }} pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={broker.settlements || []} columns={[
                      { title: "日期", dataIndex: "trade_date", width: 110 }, { title: "时间", dataIndex: "deal_time", width: 100 },
                      { title: "标的", dataIndex: "vt_symbol", width: 120 }, { title: "名称", dataIndex: "security_name", width: 110 },
                      { title: "方向", dataIndex: "action", width: 80 }, { title: "价格", dataIndex: "price", align: "right", render: (value) => num(value, 4) },
                      { title: "数量", dataIndex: "quantity", align: "right", render: (value) => num(value) },
                      { title: "金额", dataIndex: "amount", align: "right", render: (value) => num(value, 2) },
                      { title: "费用", dataIndex: "fee", align: "right", render: (value) => num(value, 2) },
                      { title: "资金余额", dataIndex: "cash_balance", align: "right", render: (value) => num(value, 2) }
                    ]} />
                  </>
                },
                {
                  key: "fund_flows", label: `资金流水 ${broker.fund_flows?.length || 0}`,
                  children: <>
                    <div className="broker-note">
                      按业务分类汇总：{(broker.cash_summary || []).map((row: any) => `${row.category} ${num(row.amount, 2)}（${row.count} 笔）`).join(" · ") || "暂无"}。算账户收益时要先剔除出入金。
                    </div>
                    <Table size="small" rowKey="flow_key" scroll={{ x: 820 }} pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={broker.fund_flows || []} columns={[
                      { title: "日期", dataIndex: "trade_date", width: 110 }, { title: "时间", dataIndex: "flow_time", width: 100 },
                      { title: "业务", dataIndex: "business", width: 140 },
                      { title: "分类", dataIndex: "category", width: 90, render: (value) => <Tag color={value === "出入金" ? "orange" : value === "证券交易" ? "blue" : "default"}>{value}</Tag> },
                      { title: "标的", dataIndex: "vt_symbol", width: 120 },
                      { title: "发生金额", dataIndex: "amount", align: "right", render: (value) => signed(value) },
                      { title: "剩余资金", dataIndex: "balance", align: "right", render: (value) => num(value, 2) }
                    ]} />
                  </>
                },
                {
                  key: "reconciliation", label: "三方持仓",
                  children: <>
                    <div className="broker-note">券商 {broker.reconciliation?.dates?.broker || "-"} · vn.py {broker.reconciliation?.dates?.vnpy || "-"} · 平台回放 {broker.reconciliation?.dates?.platform || "-"}。日期不一致时只展示，不判定差异。</div>
                    <Table size="small" rowKey="vt_symbol" pagination={{ pageSize: 10, showSizeChanger: false }} dataSource={broker.reconciliation?.items || []} columns={[
                      { title: "标的", dataIndex: "vt_symbol" }, { title: "券商", dataIndex: "broker_quantity", align: "right", render: (value) => num(value) },
                      { title: "vn.py", dataIndex: "vnpy_quantity", align: "right", render: (value) => num(value) }, { title: "平台回放", dataIndex: "platform_quantity", align: "right", render: (value) => num(value) },
                      { title: "状态", dataIndex: "status", render: (value) => <Tag color={value === "match" ? "green" : value === "difference" ? "red" : "default"}>{value === "match" ? "一致" : value === "difference" ? "有差异" : "日期未对齐"}</Tag> }
                    ]} />
                  </>
                }
              ]}
            />
          </>
        ) : (
          <div className="broker-note">{broker?.source?.message || "尚未采集券商 DBF。先在服务器 .env 配置 GYRO_LIVE_BROKER_DBF_DIR。"}</div>
        )}
      </section>

      <Collapse
        className="live-settings"
        items={[{
          key: "settings",
          label: "设置与诊断：自动跟踪、本机实盘目录、实盘源",
          children: <>
      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>内置自动跟踪</h3>
            <p>平台保持运行时，工作日北京时间 {automation?.schedule_time || "15:20"} 自动保存状态、补齐行情并执行回放对账。</p>
          </div>
          <span className={`status-pill ${automation?.enabled ? "status-completed" : "status-failed"}`}>
            {automation?.last_status === "running" ? "执行中" : automation?.enabled ? "已启用" : "已关闭"}
          </span>
        </div>
        <div className="library-metric-grid portfolio-metric-grid">
          <div className="library-metric-card"><span>下次检查</span><strong>{automation?.next_run_at ? String(automation.next_run_at).replace("T", " ").slice(0, 16) : "-"}</strong></div>
          <div className="library-metric-card"><span>上次执行</span><strong>{automation?.last_finished_at ? String(automation.last_finished_at).replace("T", " ").slice(0, 16) : "尚未执行"}</strong></div>
          <div className="library-metric-card"><span>上次状态</span><strong>{({ completed: "已完成", failed: "失败", skipped: "已跳过", running: "执行中" } as Record<string, string>)[automation?.last_status] || "等待首次执行"}</strong></div>
        </div>
        <div className="portfolio-weight-note">
          {automation?.last_message || "当天晚于计划时间才启动平台时会自动补跑一次；同一天不会重复执行。"}
        </div>
      </section>

      <section className="band library-shell">
        <div className="library-section-head">
          <div>
            <h3>本机实盘目录</h3>
            <p>
              策略目录和 <code>.vntrader</code> 目录分别配置在 <code>.env</code>，
              平台从中读取策略代码、模型文件和每日持仓状态。
            </p>
          </div>
          <span className={`status-pill ${available ? "status-completed" : "status-failed"}`}>
            {available ? "可读取" : "不可用"}
          </span>
        </div>
        {available ? (
          <>
            <div className="library-metric-grid portfolio-metric-grid">
              <div className="library-metric-card"><span>当前启用策略</span><strong>{localStatus.instance_count}</strong></div>
              <div className="library-metric-card"><span>状态文件写于（北京）</span><strong>{(localStatus.state_modified_at || "-").replace("T", " ").slice(0, 16)}</strong></div>
              <div className="library-metric-card"><span>对应交易日</span><strong>{localStatus.state_trade_date || "-"}</strong></div>
              <div className="library-metric-card"><span>内容指纹</span><strong>{localStatus.state_hash || "-"}</strong></div>
              <div className={`library-metric-card ${alreadyRecorded ? "" : "positive"}`}>
                <span>这份文件</span>
                <strong>{alreadyRecorded ? `已记录为 ${localStatus.recorded_as}` : "尚未导入"}</strong>
              </div>
            </div>
            <div className="portfolio-weight-note">
              {alreadyRecorded ? (
                <>
                  当前实盘目录里的状态文件已经记录为 <strong>{localStatus.recorded_as}</strong> 的快照。
                  内容相同不代表文件过期，请结合文件修改时间确认对应交易日。
                  新交易日应使用当天收盘后的 <code>cta_strategy_data.json</code>。
                </>
              ) : (
                <>
                  这份状态文件还没被记录过，可以用它记录一个新的交易日。
                  注意：它反映的是写入时刻的持仓，请选择与之对应的交易日。
                </>
              )}
            </div>
          </>
        ) : (
          <div className="portfolio-weight-note">{localStatus?.message || "正在读取本机实盘目录 ..."}</div>
        )}
      </section>

      {available && !sources.length && (
        <section className="band library-shell">
          <div className="library-section-head">
            <div>
              <h3>建立实盘源</h3>
              <p>首次使用先记录一天作为起点。第二天起就能对当天做跟踪。</p>
            </div>
          </div>
          <div className="portfolio-editor-grid">
            <label className="field"><span>起点交易日</span>
              <Input type="date" max={todayInBeijing()} value={tradeDate} onChange={(event) => setTradeDate(event.target.value)} />
            </label>
            <label className="field"><span>名称</span>
              <Input value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
            </label>
          </div>
          <div className="portfolio-head-actions">
            <Button type="primary" loading={busy === "create"} onClick={createSource}>读取本机目录并建立</Button>
          </div>
        </section>
      )}

          {Boolean(detail) && (
          <section className="band library-shell">
            <div className="library-section-head">
              <div>
                <h3>{detail.source?.name}</h3>
                <p>
                  绑定 {detail.bindings?.length || 0} 个策略实例 · 起点 {detail.source?.first_date} ·
                  已记录 {detail.snapshots?.length || 0} 天快照
                  {detail.snapshots?.length ? `（最近 ${detail.snapshots[0].trade_date}）` : ""}
                </p>
              </div>
              <div className="portfolio-head-actions">
                <Button danger onClick={confirmDiscard}>弃用</Button>
              </div>
            </div>
            <div className="portfolio-weight-note">
              已有快照时复用已存状态；没有快照时采集对应日期的收盘状态。历史结果请在下方记录列表中查看，无需重新回放。
              因此需要该日与更早的两份快照，最早的一份只能当起点、本身无法被跟踪；
              不同日期允许状态相同，但文件时间必须对应所选日期。首次运行可能需要补齐预热行情。
            </div>
          </section>

          )}
          </>
        }]}
      />
      {replayInstance !== null && record && <LiveReplayDetails rows={rows} tradeDate={record.trade_date} instance={replayInstance} onClose={() => setReplayInstance(null)} />}
    </section>
  );
}
