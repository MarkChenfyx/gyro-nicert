# gyro_nicert

本地量化研究工作台。它将策略代码生成、市场数据、vn.py CTA 回测、参数优化、策略池与参数稳定性研究放在同一条工作流中。

当前版本面向本地单用户研究：浏览器前端只通过 FastAPI 调用后端；行情和业务索引使用 SQLite；真实回测从本地行情库读取，不会在回测过程中访问 RQData。

## 已实现能力

- 自然语言策略生成：保存策略描述文本、调用兼容 OpenAI 的模型服务，生成 vn.py CTA `strategy.py`；本地文本支持按名称或最近编辑排序，以及中文、拼音和常用英文策略词搜索。
- 本地策略上传：在工作台直接选择单个 `.py` 文件，读取代码后登记、回测并进入参数优化。
- 直接粘贴策略代码：粘贴完整 `strategy.py`，后端登记策略后运行 baseline 回测；上传和粘贴均可先调用“AI 修正代码”，并区分可运行、需要人工处理和修正失败。
- 数据管理：检查本地行情覆盖范围，按需通过 RQData 下载并写入 SQLite。
- 真实回测：使用项目内适配的 vn.py CTA `BacktestingEngine` 与本地 SQLite K 线数据运行回测。
- 参数优化：支持 Optuna 自适应优化和手动网格搜索；手动网格保留 Top 10 候选的轻量日度曲线，可在结果表中点击临时预览。
- 策略池：将代码、参数、配置、结果、曲线和成交记录保存为独立快照，支持备注、比较、重跑，以及从池快照重新回测为 baseline 后继续优化。
- 虚拟组合：从策略池快照选择多个子策略，以固定相对权重汇总单位仓位收益；缺失数据日期对应权重按现金计且不重新分配，保存不可变计算快照并检测来源更新；查看组合不会触发回测。
- 策略研究：从策略池快照运行双参数稳定性热力图和滚动优化样本外检验，对比滚动选参与固定参数表现，不修改原快照。
- 实盘跟踪：读取本机 vn.py 部署目录中的策略代码、模型文件与每日持仓状态，以前一交易日收盘状态为起点重放当天，比对回放持仓与实盘持仓并保留当日回放成交；结果独立保存，不写入策略池，也不影响任何研究产物。
- 任务与产物：记录策略、任务、run、variant、曲线、成交和池快照的索引关系。

## 技术结构

```text
frontend/                 React + Vite + Ant Design + ECharts
backend/                  FastAPI 后端与全部服务端模块
  api/                    API 路由
  services/               工作流与业务服务
  repositories/           SQLite 索引仓储
  backtesting/            本地行情适配与 vn.py CTA 回测边界
  data_manager/           RQData 下载、本地行情 SQLite 与覆盖范围查询
  strategy_generation/    自然语言到 vn.py 策略代码的生成边界
  strategy_optimization/  参数清单、自动优化与手动网格优化
storage/natural_language/ 工作台可选择的自然语言策略文本
storage/strategies/       策略生成、校验和模板目录
storage/db/               app.sqlite 与 market_data.sqlite
storage/runtime/          临时 run 产物
storage/runtime/research/ 参数热力图与滚动优化研究结果
storage/pool/             长期策略池快照
storage/portfolios/       虚拟组合计算快照与贡献明细
scripts/                  运维脚本，例如初始化数据库
tests/                    自动化测试
```

## 环境要求

本地开发：

- Python 3.11+
- Node.js 18+
- npm
- 可选：vn.py CTA 及其运行依赖（真实回测需要）
- 可选：RQData 凭据和 `rqdatac`（自动下载行情需要）
- 可选：兼容 OpenAI 的模型 API Key（自然语言生成需要）
- 可选：策略自身依赖的第三方库（例如加载 scikit-learn 模型文件的策略需要 `scikit-learn`）


安装 Python 基础依赖：

```powershell
pip install -e .
```

真实回测环境还需要安装与你的 vn.py 部署匹配的 `vnpy` 与 `vnpy_ctastrategy`。工作台实际导入的是 `backend/backtesting/cta_engine.py`，不会直接使用 site-packages 中的 vn.py CTA 回测引擎。若使用 RQData 下载行情，还需要安装 `rqdatac`。

## 配置

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

`.env` 支持以下配置：

- `GYRO_LLM_API_KEY`、`GYRO_LLM_BASE_URL`、`GYRO_LLM_MODEL`：自然语言策略生成。
- `GYRO_RQDATA_USERNAME`、`GYRO_RQDATA_PASSWORD`：RQData 行情下载。
- `GYRO_CORS_ORIGINS`：允许直接访问后端 API 的浏览器来源，多个来源用逗号分隔。
- `GYRO_TASK_STALE_AFTER_HOURS`：运行中或排队任务连续多久未更新后自动取消并归档，默认 `6` 小时；设为 `0` 可关闭。
- `GYRO_LIVE_STRATEGY_DIR`：实盘策略源码和模型文件所在目录。
- `GYRO_LIVE_VNTRADER_DIR`：包含 `cta_strategy_setting.json` 和 `cta_strategy_data.json` 的 `.vntrader` 目录。两个目录可以分开放置，且只写在本机 `.env` 中。旧的 `GYRO_LIVE_SOURCE_DIR` 单根目录配置仍可使用。

RQData 凭据统一配置在项目根目录的 `.env`：

```text
GYRO_RQDATA_USERNAME=你的用户名
GYRO_RQDATA_PASSWORD=你的密码
```

不要提交 `.env`、RQData 密码或模型 API Key。

## 本地开发

最简单的方式是在项目根目录双击 `start.bat`，或只运行一条命令：

```powershell
python scripts/dev.py
```

它会自动初始化数据库、在首次运行时安装前端依赖，并同时启动前后端。按 `Ctrl+C` 可一起关闭。下面是分别启动前后端的手动方式。

以下命令均从项目根目录运行。先初始化数据库：

```powershell
python scripts/init_db.py
```

启动后端：

```powershell
python -m uvicorn backend.main:app --reload
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- API 文档：<http://127.0.0.1:8000/docs>

另开一个终端启动前端：

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

默认工作台地址为 <http://127.0.0.1:5173>。开发服务器会将 `/api` 代理到 `http://127.0.0.1:8000`；只有后端位于其他地址时，才需要在构建前设置 `VITE_API_BASE_URL`。

## Windows 服务器迁移与试运行

当前使用 Python 直接托管构建后的前端和 API，不需要 Docker。服务器入口为 `start-server.bat`，开发入口仍为 `start.bat`。

### 搬迁前

先停止平台的生成、下载和回测任务，再运行：

```powershell
npm --prefix frontend run build
python scripts/package_server.py
```

迁移 ZIP 输出到 `outputs/`。包内包括源代码、构建后的前端、自然语言文本、手工策略以及通过 SQLite 备份接口复制的行情库。**不带旧业务数据库、Run、策略池、组合、实盘快照或 `.env`**，服务器从新业务记录开始；本机旧文件完全保留，不转换旧绝对路径。

新生成的策略、Run、策略池和组合产物路径按项目相对路径存储；实盘快照按 storage 相对路径存储。以后迁移这些新记录时，停止写入后一起复制整个项目和 `storage/`，不要只复制数据库，也不要只使用 Git 拉取。第三方策略自身引用的外部绝对路径仍需单独处理。

### 服务器首次安装

解压到一个新目录，不覆盖老师的交易程序。在项目目录使用独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-server.txt
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

`requirements-server.txt` 记录本机验证使用的直接依赖版本（Windows / Python 3.13），不是所有间接依赖的完整锁定。建议优先使用同一 Python 小版本。不要在老师交易程序的 Python 环境里执行安装；模型反序列化若提示版本不兼容，应在平台独立环境匹配模型训练依赖。

填写 `.env` 的模型服务、RQData 凭据、`GYRO_LIVE_STRATEGY_DIR` 和 `GYRO_LIVE_VNTRADER_DIR`。老师服务器上的策略目录与 `.vntrader` 目录可以分开放置。

包内已有前端构建文件，运行时不需要 Node.js。若后续修改前端，安装 Node.js 后运行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build`。

### 启动和验收

双击 `start-server.bat`，或运行：

```powershell
.\.venv\Scripts\python.exe scripts/serve.py
```

在远程桌面的浏览器打开 <http://127.0.0.1:8000>；健康检查为 <http://127.0.0.1:8000/api/health>。前后端共用端口，无热重载。若端口占用，可使用 `scripts/serve.py --port 8001`。页面无多用户认证，默认仅本机访问。

首次启动自动创建新业务表。先确认首页和本地行情可读，再用一个简单策略做最小回测并查看结果；不要在老师交易时段启动大批并行优化。远程桌面断开不等于注销，实际是否保留进程取决于服务器会话策略；部署后测试断开再连接，并关闭休眠。当前不提供系统服务自启动。

实盘第一次收盘快照只作为起点，第二个交易日开始比对。记录前确认北京时间、状态文件修改时间和交易日期一致。结果是**策略状态持仓与分钟回放持仓对比**，不是券商持仓或真实收益对账。

### 实盘检测边界

- 收盘限制在保存前执行；未来日期拒绝，同一日期的不同内容不会覆盖。允许不同日期状态相同，文件时间独立校验。
- 新快照保存代码及常见模型文件（py/model/pkl/pickle/joblib/npy）副本与哈希。回放使用快照副本；起止代码、模型或参数不一致时不比较，旧快照没有版本证据也不比较。
- 沪深分钟线支持分钟起点或终点两种时间标记。目标日及回放区间工作日不足完整交易时段时显示 DATA_GAP，并可尝试补下载。当前未接交易所节假日/停牌日历，因此无法确认的停市日会保守显示 DATA_GAP；其他交易所暂不作一致性结论。
- 已有快照可以独立重放，历史结果从记录列表直接查看；跨多天回放明确展示起止区间。缺少合法 pos 或状态无法恢复时不显示 MATCH。
- on_start 完成后再次恢复存档变量，避免启动预热覆盖状态；这仍不能重建未存档的活动委托或全部策略内部状态。真实成交、逐笔收益以后取得实际交易数据再接入。

## 工作台使用流程

### 1. 选择策略来源

启动配置提供三种方式：

1. **自然语言生成**：选择或新建策略描述文本，生成 vn.py CTA 策略代码。文本列表可按名称或最近编辑排序，并支持文件名、拼音和常用英文策略术语搜索；排序方式和启动草稿保存在浏览器本地。
2. **直接粘贴策略代码**：填写策略名称并粘贴完整 `strategy.py`。
3. **从本地上传策略代码**：直接选择单个 `.py` 文件，平台读取、预览并登记其代码。

本地上传和粘贴代码复用相同的后端流程：可选 AI 修正 → 后端校验与单位仓位规范化 → 策略登记 → baseline 回测 → 参数优化页面。AI 修正只有在返回结构化 `runnable` 状态时才会自动应用；仍依赖本地文件、外部数据或缺失依赖时会标为 `warning`，保留原代码等待人工处理。

### 2. 配置回测

填写：

- 标的与交易所，例如 `511380.SSE`
- 输入周期，例如 `1m`
- 回测起止日期
- 手续费率、滑点、资金、合约大小和最小价格变动

对于策略内部用 `BarGenerator` 将 1 分钟 K 线聚合为 60 分钟 K 线的策略，工作台输入周期应选择 **`1m`**，不要选择 `60m` 或 `1h`。

### 3. 行情覆盖与真实回测

提交前端请求时，工作台会检查所选标的、周期和日期范围的本地行情覆盖情况。缺失或不完整时，前端会尝试调用数据下载接口补齐行情；真实回测只读取 `storage/db/market_data.sqlite` 中的数据。

`mode="real"` 为默认模式。真实模式使用项目内适配引擎的委托撮合、停止单、逐日盈亏和统计逻辑，同时通过适配器从 `storage/db/market_data.sqlite` 读取 K 线，不依赖 vn.py 的全局 MySQL/SQLite 数据库配置。`mode="mock"` 仅用于离线测试或明确的模拟回退。

当前工作台数据层只落库 K 线，因此平台回测默认并仅开放该引擎的 `BAR` 模式。引擎本身保留 `TICK` 撮合能力；在本地 Tick 表、覆盖检查和下载链路接入前，请求 `data_mode="tick"` 会返回明确错误，不会静默改用 K 线。

### 4. 查看结果与优化

回测完成后可以查看：

- 策略累计收益与 Buy & Hold 对比
- 策略与 Buy & Hold 的回撤阴影及最大回撤
- 夏普、交易数与其他 vn.py 指标
- 日度结果、成交记录和策略代码
- 可优化参数及自动/手动网格优化结果

Optuna 默认最多评估 200 次。若所有已选参数都是离散范围且唯一组合不足 200 组，平台会自动使用 Optuna `GridSampler` 将每个组合只回测一次，不会用重复参数补足 200 次；组合超过 200 组或包含连续分布时使用 TPE 抽样 200 次。

AI 生成的参数范围会按 run 和 baseline 版本缓存，包含参数分类、是否启用、范围、步长、解释、约束、虚拟参数和风险提示。重新进入参数优化页面时会恢复缓存内容；再次点击“AI 生成参数范围”会重新请求并覆盖旧缓存。手动网格结果使用高密度 Top 10 表格，点击候选行会按需读取已缓存的 `daily_results` 并临时叠加曲线；行末“诊断”抽屉展示候选与 Baseline 的核心指标及轻量交易结构摘要，不会创建正式 variant，也不会保存完整候选成交记录。

参数表中的“本次默认值”可以直接编辑：未选中的参数会在本次优化中固定为该值，选中的参数仍按配置范围搜索。编辑只影响本次优化及其候选回测，不会改写策略源码、已有 baseline 或历史结果；隐藏的仓位和系统参数不可从该入口覆盖。

### 5. 加入策略池

接受某个 baseline 或优化变体后，可将其加入策略池。新快照以北京时间入池时刻生成 `pool_version` 和 `pool_item_id`，名称统一显示为“名称 | pool_version”。池快照会复制策略代码、配置、最终参数、结果、曲线、成交记录和用户备注，因此原 runtime run 被保留策略清理后，列表、详情、比较和重跑仍可独立工作。

从策略池选择“继续参数优化”时，平台读取池快照中的代码和最终参数，重新回测并创建一个新的 baseline run，再跳转到参数优化页；不会复制旧 run 的 variants。新 run 的 `manifest.lineage` 只记录系统来源关系，和用户可编辑的 `notes.md` 备注相互独立。

### 6. 策略研究

将候选策略加入策略池后，可在“策略研究”页面选择一个池快照进行分析。页面会读取快照中的策略代码、回测配置、固定参数、收益曲线和备注；研究结果单独保存，不会修改策略池快照或原参数优化结果。

**参数热力图**用于观察两个参数附近是否存在连续的有效区域：

- 横轴和纵轴选择两个不同的数值参数，并分别设置最小值、最大值和步长。
- 每个参数至少需要两个有效取值，两个维度的组合总数最多为 100 组。
- 评分指标可选择超额收益或 Sharpe；平台使用真实回测逐一评估组合。
- 热力图会标记当前参数与当前指标最优组合，并按指标为正的组合比例给出“较稳定 / 一般 / 较敏感”的提示。该提示是当前网格内的启发式摘要，不代表未来收益保证。

**滚动优化**用于检查滚动选参的样本外表现：

- 选择 1～3 个参数；每个训练窗口的参数组合总数必须在 2～100 组之间。
- 训练窗口可设置为 6～120 个月，默认 24 个月；样本外测试窗口固定为 6 个月，并每 6 个月向前滚动。
- 每个窗口只使用训练期数据按 Sharpe 选参，再将选出的参数用于紧随其后的 6 个月样本外回测。
- 滚动优化主流程会保存每个窗口的训练期完整参数网格；结果生成后，可点击“计算全量样本外”按需复测相同参数横截面，无需每次运行滚动优化都承担这部分计算。
- 全量样本外分析会计算训练 Sharpe 与样本外 Sharpe 排名的 Spearman Rank IC；结果写回当前实验并缓存，重复进入页面不会重新计算。
- 参数横截面按训练排名从低到高分为最多五组，展示各组样本外 Sharpe、分组单调性、训练前 20% 参数的样本外提升，以及训练最优参数的样本外百分位。
- 页面会将所有完整样本外窗口拼接成曲线，并与策略池快照中的固定参数在相同测试区间进行对照。
- 每个样本外窗口均独立冷启动，不继承上一窗口的持仓或策略内部状态；汇总指标不包含训练期表现。

研究前应确保整个训练和测试区间的本地行情完整。常规滚动优化的主要计算量约为“窗口数 × 参数组合数”，另加滚动选中参数与固定参数对照；点击“计算全量样本外”后，再增加约“窗口数 × 参数组合数”的计算。旧实验没有保存训练网格时，第一次全量分析还会补算训练横截面。每个实验保存到 `storage/runtime/research/<pool_item_id>/<experiment_id>/result.json`，重新进入页面时会恢复最近一次热力图和滚动优化结果。

### 7. 实盘跟踪

在 `.env` 中分别配置 `GYRO_LIVE_STRATEGY_DIR` 和 `GYRO_LIVE_VNTRADER_DIR` 后，「实盘跟踪」页可以：

1. **建立实盘源**：读取该目录下 `.vntrader/cta_strategy_setting.json` 中当前启用的策略，登记类名、标的、参数与实盘手数，并把当日 `cta_strategy_data.json` 记为起点快照。
2. **每日跟踪**：把当天的实盘状态记为该交易日快照，再以上一份快照为起点重放当天。

回放使用与实盘一致的预热区间（策略 `on_init` 中 `load_bar(days)` 声明的天数），预热完成后才注入实盘存档的持仓与策略变量，然后回放当日一分钟 K 线。策略参数按实盘原样传入，不做 `fixed_size` 归一化，因此回放持仓与实盘持仓同量纲，可直接相减。

每个策略实例给出一个状态：

| 状态 | 含义 |
| --- | --- |
| `MATCH` | 回放持仓与实盘一致 |
| `MISMATCH` | 回放持仓与实盘不一致，需要排查信号或成交 |
| `DATA_GAP` | 本地行情覆盖不完整，本次不下结论 |
| `CONFIG_CHANGED` | 实盘参数或标的已变，需要重新建立实盘源 |
| `NO_STATE` | 当日或起点快照缺少该策略状态 |
| `NEW_INSTANCE` | 实盘新增了尚未绑定的策略 |
| `REPLAY_ERROR` | 回放过程出错 |

跟踪需要起点与当日两份快照，因此首次建立实盘源的当天还不能跟踪。回放结果单独保存在 `storage/live/`，不写入策略池，也不创建虚拟组合。

服务器可在首次建立实盘源后运行 `powershell -ExecutionPolicy Bypass -File .\install-live-schedule.ps1`，创建“GYRO Daily Live Replay”计划任务。它会在周一至周五服务器本地时间 15:20 读取当天状态、保存快照、补齐行情并执行回放对账；休市或状态尚未更新时安全跳过，失败会每 10 分钟重试，日志写入 `storage/runtime/live-daily.log`。


## 实盘跟踪中的回放成交与信号

在实盘跟踪结果中点击“目标日回放成交”或某个策略的“当日回放成交”，打开详情抽屉。可按策略、日期查看：

- 当日成交：时间、方向、开平、价格、数量和成交前后持仓；展开后关联到原始下单信号，跨日成交也保留原信号日期。
- 当日提交委托：限价单和停止单，包含已撤销、未成交及已触发的最终状态。状态以整个回放区间结束时为准，停止单触发后的子委托不重复计数。
- 下单证据：输入分钟 K 线、策略回调 K 线（若可取得）、策略标量变量与参数、局部计算值、源文件行号和代码上下文。不修改策略代码或撮合算法，不调用模型解释信号，不自动重算指标。

详细信号从升级后的新回放开始记录，保存在实盘记录的 `rows.json` 中，另有 `replay_orders.csv`。旧记录有成交就能查看，但没有的信号细节不会凭空补全；打开抽屉或历史记录只读缓存，不会重新回放。这些是平台模拟订单，不是真实实盘成交或真实收益。当前只采集下单时的证据，不记录每根 K 线上未满足的条件；代码上下文不代表其中所有分支都执行过。

## 曲线与最大回撤口径

工作台的策略曲线使用单位仓位累计收益口径：

```text
C(t) = Σ(日 net_pnl / 昨日 close_price) × 100
DD(t) = C(t) - max(C(0...t))
最大回撤 = min(DD(t))
```

曲线、曲线最大回撤、优化表现表和策略池比较使用这一口径。策略曲线和 Buy & Hold 都会计算并展示各自的回撤阴影。它与 vn.py 基于账户资金 `balance` 计算的账户回撤是不同概念，页面不会将两者混为同一展示指标。

为了使不同策略可比，本地上传和直接粘贴的策略在登记时会检查 `fixed_size`：不是 `1` 时平台会自动将实际回测代码标准化为 `fixed_size = 1`，并在页面提示；原始上传文本仍作为来源记录保存。

## API 概览

主要 API：

| 目的 | API |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 自然语言源文件 | `GET/POST /api/natural-language/sources` |
| 生成策略 | `POST /api/strategies/generate` |
| 从策略 ID 创建 baseline | `POST /api/research/baseline` |
| 从直接代码创建 baseline | `POST /api/research/baseline-from-code` |
| 行情覆盖、下载、标的 | `/api/data/coverage`、`/api/data/download`、`/api/data/symbols` |
| run、正式曲线、候选曲线、成交 | `/api/runs` |
| 参数优化 | `/api/optimization/methods`、`/api/optimization/search-space`、`/api/optimization/suggest-space`、`/api/optimization/run` |
| 策略池、备注、继续优化 | `/api/pool` |
| 虚拟组合管理、刷新与净值导出 | `/api/portfolios` |
| 策略研究上下文 | `GET /api/strategy-research/pool/{pool_item_id}/context` |
| 参数稳定性热力图 | `POST /api/strategy-research/pool/{pool_item_id}/heatmap` |
| 滚动优化检验 | `POST /api/strategy-research/pool/{pool_item_id}/walk-forward` |
| 滚动优化全量样本外分析 | `POST /api/strategy-research/pool/{pool_item_id}/walk-forward/{experiment_id}/rank-analysis` |
| 实盘跟踪本机目录状态 | `GET /api/live/local-status` |
| 实盘源、每日快照、当日跟踪 | `/api/live/sources` |
| 任务 | `/api/tasks` |

完整请求与响应结构以运行中的 <http://127.0.0.1:8000/docs> 为准。

## 数据与存储

- `storage/db/app.sqlite`：策略、任务、run、variant、策略池、虚拟组合和产物索引。
- `storage/db/market_data.sqlite`：本地 K 线、覆盖范围和下载任务。
- `storage/runtime/runs/<run_id>/`：临时运行产物，包括 `strategy.py`、`config.json`、`result.json`、曲线与成交 CSV。
- `storage/runtime/research/<pool_item_id>/<experiment_id>/`：参数热力图与滚动优化实验结果。
- `storage/pool/strategies/<pool_item_id>/`：长期池快照。
- `storage/live/<source_id>/`：实盘跟踪的每日快照（`snapshots/<交易日>/`）与比对结果（`daily/<交易日>/`）。

`scripts/init_db.py` 使用 `CREATE TABLE IF NOT EXISTS`，可重复运行，不会删除已有表。

## 测试与构建

后端测试：

```powershell
python -m pytest -q
```

前端构建：

```powershell
cd frontend
npm run build
```

## 当前限制与注意事项

- 本项目面向本地研究工作流，不是多用户生产交易系统。
- 真实回测依赖本地行情完整性；没有本地数据时应先下载行情。
- 自然语言生成需要可用模型服务；自动化测试不依赖真实模型、RQData 或网络。
- 上传和粘贴的策略代码会在后端回测环境加载。只应使用你信任的策略文件。
- 策略代码应定义一个继承 `vnpy_ctastrategy.CtaTemplate` 的公开策略类，并实现平台所需回调。
- README 描述的是当前工作台行为；历史阶段性实现细节以 Git 提交记录为准。
