import { useCallback, useEffect, useState } from "react";
import { Button, Input, Modal, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import LiveReplayDetails from "../components/LiveReplayDetails";
import {
  createLiveSource,
  deleteLiveSource,
  getLiveAutomationStatus,
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

export default function LivePage() {
  const [localStatus, setLocalStatus] = useState<any>(null);
  const [automation, setAutomation] = useState<any>(null);
  const [sources, setSources] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [record, setRecord] = useState<any>(null);
  const [tradeDate, setTradeDate] = useState("");
  const [sourceName, setSourceName] = useState("实盘组合");
  const [busy, setBusy] = useState("");
  const [replayInstance, setReplayInstance] = useState<string | null>(null);

  useEffect(() => { setReplayInstance(null); }, [record?.record_id]);

  const loadSources = useCallback(async () => {
    const [status, list, automatic] = await Promise.all([getLiveLocalStatus(), listLiveSources(), getLiveAutomationStatus()]);
    setLocalStatus(status);
    setAutomation(automatic);
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
  const rows = record?.rows || [];
  const available = Boolean(localStatus?.available);
  const alreadyRecorded = Boolean(localStatus?.recorded_as);

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
        <>
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
                <label className="field"><span>跟踪交易日</span>
                  <Input type="date" max={todayInBeijing()} value={tradeDate} onChange={(event) => setTradeDate(event.target.value)} />
                </label>
                <Button type="primary" loading={busy === "track"} onClick={runTracking} disabled={!sourceId}>
                  {detail?.snapshots?.some((item: any) => item.trade_date === tradeDate) ? "使用已存快照重新回放" : "记录收盘快照并跟踪"}
                </Button>
                <Button danger onClick={confirmDiscard}>弃用</Button>
              </div>
            </div>
            <div className="portfolio-weight-note">
              已有快照时复用已存状态；没有快照时采集对应日期的收盘状态。历史结果请在下方记录列表中查看，无需重新回放。
              因此需要该日与更早的两份快照，最早的一份只能当起点、本身无法被跟踪；
              不同日期允许状态相同，但文件时间必须对应所选日期。首次运行可能需要补齐预热行情。
            </div>
          </section>

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

          {Boolean(detail.records?.length) && (
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
        </>
      )}
      {replayInstance !== null && record && <LiveReplayDetails rows={rows} tradeDate={record.trade_date} instance={replayInstance} onClose={() => setReplayInstance(null)} />}
    </section>
  );
}
