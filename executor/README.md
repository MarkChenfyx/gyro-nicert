# 交易引擎（executor）

独立进程接收 QMT 行情，统一整理报价、封口窗口和 K 线，按订阅调用策略；策略输出目标持仓，引擎负责数量冻结、资源检查、报单、撤单、成交入账和恢复。

## 运行与数据

| 模式 | 行情 | 成交 | 默认交易库 |
| --- | --- | --- | --- |
| backtest | 历史分钟采样或原始事件录制 | 模拟网关 | `storage/executor_v2/backtests/<名称>/executor.sqlite` |
| paper | QMT 实时行情 | 模拟网关 | `storage/executor_v2/paper.sqlite` |
| live | QMT 实时行情 | QMT 成交 | `storage/executor_v2/live.sqlite` |

QMT 行情（`QmtMarketGateway`，xtdata）与账户（`QmtTradeGateway`，xttrader）是两个网关。paper 只连行情、不登录账户，因此同一账户上其他程序的委托和成交不会进入或暂停纸面引擎；live 同时使用两者。

新版本使用第 2 版数据库，旧库拒绝作为可写运行库打开，不自动迁移。现有同名回测禁止覆盖。历史行情可以继续从原目录只读读取。平台执行监控默认读取 `storage/executor_v2/`，打开页面不会重跑策略。

真实下单仍要求 `mode="live"` 与 `live_trading=true`。当前实盘要求专用资金账户，启动时比较完整持仓并检查未知活动委托；运行时出现无法归属的活动委托或成交会暂停。与 vn.py 共用账户的资金和重叠持仓，需另行接入统一资源协调后再支持。策略账本本身不能隔离两个独立下单程序。

## 文件职责

```text
engine.py       单线程事件分发、生命周期、统一最终报单检查及一致性检查点
market.py       报价缓存、分钟窗口封口、多标的快照、缺失/过期标记
bars.py         BarGenerator；按声明的周期合成报价采样时间 K 线
clock.py        北京时间时钟、回放时钟、交易时段与调度进度
strategies/     订阅、指标、信号、目标持仓及策略内部状态
execution.py    冻结目标数量、先卖后买、有效期、超时撤单与有限次追价
oms.py          短客户端编号、委托状态、已确认/已入账数量、成交去重
portfolio.py    实际策略账本与单位仓位收益序列
risk.py         STOP 文件、价格/金额限制、策略熔断、日内计数
store.py        SQLite、检查点、完整委托/成交记录、单进程文件锁
recorder.py     原始报价批次与时钟事件；每次启动独立 JSONL 分片
data.py        历史分钟采样、原始事件录制及除权除息数据读取
gateways/     QMT 行情网关、QMT 交易网关与可恢复的模拟成交
runner.py       backtest / paper / live 启动与可选历史预热
replay_check.py 只读核对每次策略实际输入、起点状态、完整输出和结束状态
report.py       单位仓位收益与基准超额报告
```

## 策略接口

策略实现 `subscription()` 返回 `Subscription(symbols, bar_minutes, ticks, snapshots, require_iopv)`。同指数轮动有两种信号：`signal = "premium"`（溢价，需要 IOPV）和 `signal = "price"`（组内相对复权价格，不需要 IOPV）。QMT 推送只在深市 ETF 的 `pe` 字段里给出 IOPV，沪市为 0，因此含沪市 ETF 的组合使用价格版。

除权除息：回测读 `corporate_actions.csv`；纸面/实盘每天开盘前读 QMT 除权数据（`get_divid_factors`）。引擎据此调整账本，并以 `on_corporate_action(symbol, ratio)` 通知策略调整价格历史。每只标的当日首笔行情的交易所前收盘参考价会与“昨日收盘 × 除权比例”核对，不符时按交易所参考价修正、相关策略当日暂停并弹窗。

- `on_tick(ctx, quote)`：只接收订阅标的的有效报价。
- `on_snapshot(ctx, snapshot)`：收到同一分钟窗口的数据，附带 stale 集合。缺失标的不会用另一分钟的旧报价悄悄补齐。
- `on_bars(ctx, end, minutes, bars, missing)`：按周期接收一组已结束 K 线；不完整窗口带 complete=False，并列入 missing。
- `on_order(ctx, order)` / `on_trade(ctx, trade)`：订单变化和新增成交。逐笔成交先更新账本再通知策略；Context 使用账本副本。
- `state()` / `restore()`：保存全部影响决策的内部状态。`configuration()` 返回需保持一致的策略定义与参数；已有运行库参数改变会拒绝恢复。

返回值是 `TargetIntent` 或 None。None 表示没有新目标；空 targets 明确表示清仓。本策略尚有活动任务或未入账成交时，新目标会被拒绝，旧目标继续被完整管理。目标数量在接受时结合预算、价格和预计费用冻结。

标准快照默认从北京时间 09:31 起每 N 分钟、下午 13:01 起每 N 分钟触发。实时窗口默认等待 2 秒封口；历史已完成分钟采样通过 interval_end=True 标明时间含义，某个策略自己的标的在窗口内到齐即决策，不等其他策略的标的。迟到数据不改写已经决策的窗口。

BarGenerator 当前合成的是实际收到的报价样本 OHLC，不包含成交量，也不等同于交易所完整成交生成的 K 线。依赖交易所成交 OHLC/量的策略，需要接入相应官方 K 线数据。周期在交易时段内对齐，午休不跨段合成。

## 执行与恢复

发送前先提交委托、任务、账本和策略检查点；客户端编号不超过 QMT 备注的 24 个英文字符，完整策略归属存在数据库中。备注用于关联，不假定券商按备注去重。

报单结果未知、撤单失败、已确认成交尚未入账时，保留资金和数量约束。委托全成不会提前释放尚未入账的部分。每笔新委托都重新检查交易许可、时段、行情年龄、熔断、策略预算和账户实际可用资源。账户资源的预留采用保守规则，可能暂时少下单。

重启恢复策略状态、调仓任务、调度、风控、行情窗口和模拟网关；QMT 重新查询全部当日委托及成交，补记缺失成交后核对持仓。无法确认的订单保持 UNKNOWN 并暂停，禁止盲目重发。运行中每 30 秒查询一次结果未确认（待确认、撤单中、状态不明）的委托：补记丢失的回报；券商仍显示有效的撤单中委托重发撤单；券商查不到的委托标为 UNKNOWN 并暂停交易。文件锁防止同一交易库被两个执行器同时使用。

模拟成交只使用下单后到达的新报价。同一订单对同一报价仅撮合一次，重复心跳不会把部分成交自动刷成全成。模拟不保证等同真实排队、深度和成交效果。

## 录制、重放和收益

原始录制保留报价时间、实际处理时间、批次顺序和推进时钟，写入 `events_<日期>_<会话>.jsonl`。重启使用新分片。每次策略调用的实际输入、上下文、完整目标和开始/结束状态的校验值保存在交易库中；完整策略状态每日收盘保存一份（state_history）。

日常核对从前一交易日收盘状态出发，以当时实际上下文逐次重放策略调用，并用校验值核对每次调用前后的状态；数据库只读打开。它验证决策确定性，不用模拟成交金额相等来证明实盘执行正确。

策略收益按单位持仓盈亏除以上期收盘价、乘 100 后简单累加，包含成交价差与已知费用。单位份数按冻结目标的成交比例记录；预算主要用于实际下单数量约束。QMT 提供有效 lastClose 时优先用它作为前收盘参考，历史采样使用前一交易日最后样本；数据不足时不伪造累计值。账户权益和现金单独作为资金信息展示。旧版本账户资金收益不作为新口径曲线展示。

## 使用

```powershell
# 先复制配置示例并填写本地连接信息；真实账号不提交
# 历史数据验证应使用已获准的开发区间；最近六个月继续留作最终测试集
python -m executor.runner --config executor/config.example.toml --mode backtest --start 2024-01-01 --end 2026-04-15 --run-name rotation_v2

# 重放指定日期的实际决策输入
python -m executor.replay_check --config executor/config.toml --db storage/executor_v2/paper.sqlite --date 2026-01-05

# 直接相关的离线回归
python -m pytest tests/test_executor.py tests/test_executor_safety.py tests/test_executor_service.py -q
```

`warmup_start` 与 `warmup_end` 同时配置时，首次启动从 data_dir 通过相同的策略接口进行历史预热，预热期间禁止交易。已有交易状态直接恢复，不重新预热。

2026-10-19 服务器只读探测：QMT 行情推送正常；深市 ETF 的 IOPV 在 `pe` 字段，沪市没有 IOPV。QMT 除权数据的实际格式尚未在服务器上见过，代码对字段做检查，不符即报错。QMT 的真实柜台回调时序尚未在服务器验证。实盘分红、拆分和实际费用还需要权威数据源核对；本地离线测试不替代这些步骤。
