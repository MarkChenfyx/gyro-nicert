import { useMemo, useState } from "react";
import { Alert, Drawer, Empty, Select, Table, Tabs, Tag } from "antd";

type Row = Record<string, any>;
const valueText = (value: any) => value == null ? "—" : typeof value === "boolean" ? (value ? "是" : "否") : String(value);
const timeText = (value: any) => String(value || "—").replace("T", " ");

function Fields({ values }: { values: Row }) {
  return <dl className="live-evidence-fields">{Object.entries(values).map(([key, value]) =>
    <div key={key}><dt>{key}</dt><dd>{valueText(value)}</dd></div>)}</dl>;
}

function Bar({ title, bar }: { title: string; bar?: Row }) {
  if (!bar?.datetime) return null;
  return <div><h4>{title} · {timeText(bar.datetime)}</h4><Fields values={{
    开盘: bar.open_price, 最高: bar.high_price, 最低: bar.low_price, 收盘: bar.close_price, 成交量: bar.volume,
  }} /></div>;
}

function Evidence({ signal, trade }: { signal?: Row; trade?: Row }) {
  return <div className="live-evidence">
    {trade && <><h4>成交时持仓变化</h4><Fields values={{ 成交编号: trade.tradeid, 委托编号: trade.orderid,
      成交前持仓: trade.position_before, 成交后持仓: trade.position_after }} /><Bar title="撮合使用的分钟 K 线" bar={trade.fill_bar} /></>}
    {!signal ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该记录未保存关联信号。新回放会记录下单证据，查看此处不会触发回放。" /> : <>
      <h4>下单时信号证据</h4>
      <Fields values={{ 信号编号: signal.signal_id, 下单时间: timeText(signal.datetime), 委托类型: signal.order_type,
        方向: signal.direction, 开平: signal.offset, 请求价格: signal.requested_price, 数量: signal.volume, 下单时持仓: signal.position_at_signal }} />
      <Bar title="下单时输入的分钟 K 线" bar={signal.input_bar} />
      <h4>策略变量与参数快照</h4><Fields values={signal.variables || {}} />
      {(signal.contexts || []).map((context: Row, index: number) => <div key={index}>
        <h4>{signal.source_file} · {context.function} · 第 {context.line} 行</h4>
        <Bar title="策略回调中的 K 线（可能为聚合周期）" bar={context.bar} />
        <Fields values={context.locals || {}} />
        <pre className="live-evidence-code">{context.code}</pre>
      </div>)}
      {!signal.contexts?.length && <p>本次未定位到策略源文件调用位置。</p>}
      <p className="live-evidence-note">以上数值在下单时采集。代码片段可能包含未执行分支，不能视为自动解释或无前视偏差证明；数组、模型及未计算的指标不在快照中。</p>
    </>}
  </div>;
}

export default function LiveReplayDetails({ rows, tradeDate, instance, onClose }: {
  rows: Row[]; tradeDate: string; instance: string; onClose: () => void;
}) {
  const [selectedInstance, setSelectedInstance] = useState(instance);
  const [selectedDay, setSelectedDay] = useState(tradeDate);
  const entries = useMemo(() => rows.flatMap(row => (row.replay_trades || []).map((trade: Row) => ({
    ...trade, instance_name: row.instance_name, vt_symbol: row.vt_symbol,
    key: `${row.instance_name}:trade:${trade.tradeid}`,
    signal: (row.replay_signals || []).find((signal: Row) => signal.signal_id === trade.signal_id),
  }))), [rows]);
  const orders = useMemo(() => rows.flatMap(row => (row.replay_orders || []).map((order: Row) => ({
    ...order, instance_name: row.instance_name, key: `${row.instance_name}:order:${order.order_id}`,
    signal: (row.replay_signals || []).find((signal: Row) => signal.signal_id === order.signal_id),
  }))), [rows]);
  const dates = [...new Set([tradeDate, ...entries.map(row => String(row.datetime || "").slice(0, 10)),
    ...orders.map(row => String(row.datetime || "").slice(0, 10))])].filter(Boolean).sort();
  const selectedRows = rows.filter(row => !selectedInstance || row.instance_name === selectedInstance);
  const match = (row: Row) => (!selectedInstance || row.instance_name === selectedInstance) && String(row.datetime || "").slice(0, 10) === selectedDay;
  const chronological = (a: Row, b: Row) => String(a.datetime).localeCompare(String(b.datetime)) || String(a.key).localeCompare(String(b.key), undefined, { numeric: true });
  const tradesForDay = entries.filter(match).sort(chronological);
  const ordersForDay = orders.filter(match).sort(chronological);
  const common = [
    { title: "策略", dataIndex: "instance_name", width: 180, ellipsis: true },
    { title: "时间", dataIndex: "datetime", width: 175, render: timeText },
    { title: "方向", dataIndex: "direction", width: 60 },
    { title: "开平", dataIndex: "offset", width: 60 },
    { title: "价格", dataIndex: "price", width: 90 },
    { title: "数量", dataIndex: "volume", width: 80 },
  ];
  return <Drawer title="回放成交与信号" open onClose={onClose} width="min(1120px, 96vw)">
    <Alert type="info" showIcon message="这里展示平台分钟回放的委托与成交，不是券商实盘订单。" />
    <div className="live-replay-filters">
      <label>策略<Select aria-label="选择策略" value={selectedInstance} onChange={setSelectedInstance} style={{ width: 310 }} options={[
        { value: "", label: "全部策略" }, ...rows.map(row => ({ value: row.instance_name, label: row.instance_name })),
      ]} /></label>
      <label>交易日<Select aria-label="选择交易日" value={selectedDay} onChange={setSelectedDay} style={{ width: 150 }} options={dates.map(day => ({ value: day, label: day }))} /></label>
    </div>
    {selectedRows.some(row => !["MATCH", "MISMATCH"].includes(row.status)) &&
      <Alert type="warning" message="所选范围中有策略未完成有效回放，不能将其空记录理解为当天没有交易。" />}
    {selectedRows.some(row => !row.trace_version) &&
      <p>部分记录未保存委托与信号细节；仍可查看已保存的成交。此页面只读取结果。</p>}
    <Tabs items={[
      { key: "trades", label: `当日成交 ${tradesForDay.length} 笔`, children: <>
        <p>展开一笔成交，查看它关联的下单信号（可能发生在前一交易日）。</p>
        <Table rowKey="key" size="small" columns={[...common, { title: "成交后持仓", dataIndex: "position_after", width: 100, render: valueText }]}
          dataSource={tradesForDay} scroll={{ x: 860 }} pagination={{ pageSize: 12, showSizeChanger: false }}
          locale={{ emptyText: "当前筛选下没有已保存的回放成交" }}
          expandable={{ expandedRowRender: row => <Evidence signal={row.signal} trade={row} /> }} />
      </> },
      { key: "orders", label: `当日提交委托 ${ordersForDay.length} 笔`, children: <>
        <p>状态为整个回放区间结束时的状态。停止单触发后的成交通过关联信号追溯，不重复计入提交次数。</p>
        <Table rowKey="key" size="small" columns={[...common,
          { title: "类型", dataIndex: "order_type", width: 80 },
          { title: "最终状态", dataIndex: "status", width: 100, render: value => <Tag>{value}</Tag> }]}
          dataSource={ordersForDay} scroll={{ x: 920 }} pagination={{ pageSize: 12, showSizeChanger: false }}
          locale={{ emptyText: "当前筛选下没有已保存的委托；未下单条件不在本次记录范围内" }}
          expandable={{ expandedRowRender: row => <><Fields values={{ 委托编号: row.order_id, 关联成交委托: row.child_order_ids?.join("、") }} /><Evidence signal={row.signal} /></> }} />
      </> },
    ]} />
  </Drawer>;
}
