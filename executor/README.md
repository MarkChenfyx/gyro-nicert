# 交易引擎（executor）

独立运行的交易程序：从行情网关接收报价，喂给策略；策略给出目标持仓；引擎负责下单、跟踪委托、处理成交和记账。
回测、纸面、实盘共用同一套代码，只换行情来源和成交来源：

| 模式 | 行情 | 成交 | 数据库 |
| --- | --- | --- | --- |
| backtest | 历史行情文件 | 模拟撮合 | `storage/executor/backtests/<名称>/executor.sqlite` |
| paper | QMT 实时行情 | 模拟撮合（不下单） | `storage/executor/paper.sqlite` |
| live | QMT 实时行情 | QMT 真实成交 | `storage/executor/live.sqlite` |

平台“执行监控”页面只读这些数据库。

## 结构

```
events.py      统一数据结构：报价、快照、目标持仓、委托、成交、除权除息、网关状态
clock.py       实盘/回放时钟，交易时段，决策时点（09:31 起每 N 分钟，14:56 后不再决策）
market.py      最新报价缓存；按决策时点生成快照，过期/缺 IOPV 的标的标记为 stale
data.py        行情文件读写（录制、下载、回放同一格式）与除权除息表
strategies/    策略接口 + 同指数轮动
execution.py   目标持仓 → 委托：先卖后买、整手、T+1、限价留 1 跳余量、30 秒未成交撤单重挂、有效期
oms.py         委托状态机、客户端委托号、成交去重
portfolio.py   每个策略独立账本（与账户里 vn.py 等其他仓位隔离）
risk.py        停止文件、价格保护、单笔上限、每日换仓次数、策略熔断
store.py       SQLite + 每日 JSONL 流水；日终保存账本和策略状态，供重启恢复和每日重放
recorder.py    实盘行情录制（每分钟最后快照），供回测和重放
engine.py      单线程事件处理；实盘网关回调经线程安全队列进入
gateways/      base 接口、sim 模拟撮合、qmt（xtquant，尚未在服务器实测）
runner.py      启动入口；report.py 回测报告；replay_check.py 每日重放核对
```

## 约定

- **策略只输出目标持仓**（预算内各标的权重），不直接下单；同一策略同一时间只有一个进行中的换仓。
- **成交先记账再通知策略**；撤单发出不等于撤单成功，以回报为准。
- **策略确定性**：不读系统时间、不保存文件，内部状态通过 `state()`/`restore()` 保存。同样的数据 + 同样的起点状态 → 同样的决策。
- **账本隔离**：启动时核对“券商持仓 ≥ 本引擎账本”（账户里可能有 vn.py 策略的仓位），不满足则只接行情、不交易。
- **真实下单需要两道开关**：`mode = "live"` 且 `live_trading = true`；QMT 网关默认拒绝一切下单。
- **一键停止**：创建 `storage/executor/STOP` 文件即拒绝所有新委托（撤单仍可进行）。

## 使用

```powershell
# 回测（行情目录可以是录制/下载的数据）
python -m executor.runner --config executor/config.example.toml --mode backtest --start 2024-01-01 --end 2026-10-15 --run-name test
# 压力测试：报单延迟、部分成交、随机拒单（也可在 [sim] 段配置）
python -m executor.runner --config executor/config.example.toml --mode backtest --start 2024-01-01 --end 2026-04-15 --latency 60
# 每日重放核对（纸面/实盘收盘后）
python -m executor.replay_check --config executor/config.toml --db storage/executor/paper.sqlite --date 2026-10-16
# 下载历史 tick 到 storage/executor/ticks
python scripts/executor_download_ticks.py --config executor/config.example.toml --start 2024-01-01 --end 2026-10-14
```

服务器上：先运行 `scripts/executor_probe_qmt.py` 只读探测（行情字段、IOPV、持仓、资金），核对 `gateways/qmt.py` 的字段名；
再复制 `config.example.toml` 为 `config.toml`，`mode = "paper"`，用装有 xtquant 的 Python（VeighNa 环境）运行
`start-executor.bat`（可用环境变量 `EXECUTOR_PYTHON` 指定解释器）。

## 已验证（2026-10-15，本地历史 tick 回放）

- 与研究脚本对照（开发期 2024-01～2026-04-14，阈值统一 0.3，立即成交）：年化超额 高股息 9.6%（研究 9.8%）、恒指 8.3%（7.4%）、
  标普 6.2%（4.0%）、生物科技 13.6%（9.7%）、日经 11.3%（16.0%）。差异来自基准口径（研究为 5 分钟再平衡等权）、整手和现金。
- 压力测试：半数成交、5% 随机拒单时结果几乎不变；报单延迟 60 秒时超额降为 0.3%～7%（生物科技最敏感），无卡死委托。
- 每日重放核对自检：同一份数据重放，决策 240 个时点全部一致，成交笔数和金额一致。
- 单元测试 `tests/test_executor.py`：撮合、T+1、部分成交、委托状态、风控、策略确定性、先卖后买、重启后与不重启结果一致、账本核对失败时停止交易。

## 尚未完成

- QMT 网关未在服务器实测；IOPV 字段名待 `executor_probe_qmt.py` 确认，拿不到时需改用其他来源。
- 实盘分红：账本按 `corporate_actions.csv` 记分红，实盘需每日更新该表（或改为按券商资金流水核对）。
- 回测数据为每分钟快照，延迟测试的最小粒度是 1 分钟，实际几秒延迟的结果介于“立即成交”和“延迟 60 秒”之间。
