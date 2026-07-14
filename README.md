# gyro_nicert

本地量化研究工作台。它将策略代码生成、市场数据、vn.py CTA 回测、参数优化与策略池放在同一条工作流中。

当前版本面向本地单用户研究：浏览器前端只通过 FastAPI 调用后端；行情和业务索引使用 SQLite；真实回测从本地行情库读取，不会在回测过程中访问 RQData。

## 已实现能力

- 自然语言策略生成：保存策略描述文本、调用兼容 OpenAI 的模型服务，生成 vn.py CTA `strategy.py`。
- 本地策略上传：在工作台直接选择单个 `.py` 文件，读取代码后登记、回测并进入参数优化。
- 直接粘贴策略代码：粘贴完整 `strategy.py`，后端登记策略后运行 baseline 回测。
- 数据管理：检查本地行情覆盖范围，按需通过 RQData 下载并写入 SQLite。
- 真实回测：使用项目内适配的老师版 CTA `BacktestingEngine` 与本地 SQLite K 线数据运行回测。
- 参数优化：支持 Optuna 自适应优化和手动网格搜索，保存优化变体、曲线与成交记录。
- 策略池：将 run/variant 快照长期保存，支持查看、比较与重跑。
- 任务与产物：记录策略、任务、run、variant、曲线、成交和池快照的索引关系。

## 技术结构

```text
frontend/                 React + Vite + Ant Design + ECharts
backend/                  FastAPI、API 路由、服务、仓储与领域模型
backtesting/              本地行情适配与 vn.py CTA 回测边界
strategy_generation/      自然语言到 vn.py 策略代码的生成边界
strategy_optimization/    参数清单、自动优化与手动网格优化
data_manager/             RQData 下载、本地行情 SQLite 与覆盖范围查询
strategies/               策略生成、校验和模板目录
storage/db/               app.sqlite 与 market_data.sqlite
storage/runtime/          临时 run 产物
storage/pool/             长期策略池快照
scripts/                  运维脚本，例如初始化数据库
tests/                    自动化测试
```

## 环境要求

- Python 3.11+
- Node.js 18+
- npm
- 可选：vn.py CTA 及其运行依赖（真实回测需要）
- 可选：RQData 凭据和 `rqdatac`（自动下载行情需要）
- 可选：兼容 OpenAI 的模型 API Key（自然语言生成需要）

安装 Python 基础依赖：

```powershell
pip install -e .
```

真实回测环境还需要安装与你的 vn.py 部署匹配的 `vnpy` 与 `vnpy_ctastrategy`。工作台实际导入的是 `backtesting/teacher_engine.py`，不会直接使用 site-packages 中的 vn.py CTA 回测引擎。若使用 RQData 下载行情，还需要安装 `rqdatac`。

## 配置

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

`.env` 支持以下配置：

- `GYRO_LLM_API_KEY`、`GYRO_LLM_BASE_URL`、`GYRO_LLM_MODEL`：自然语言策略生成。
- `GYRO_RQDATA_USERNAME`、`GYRO_RQDATA_PASSWORD`：RQData 行情下载。
- `GYRO_VT_SETTING_PATH`：可选的 vn.py `vt_setting.json` 路径。

RQData 凭据查找顺序：

1. `GYRO_RQDATA_USERNAME` / `GYRO_RQDATA_PASSWORD`
2. `RQDATA_USERNAME` / `RQDATA_PASSWORD`
3. `GYRO_VT_SETTING_PATH`
4. 项目或用户目录的 `.vntrader/vt_setting.json`

不要提交 `.env`、RQData 密码或模型 API Key。

项目本地的 vn.py/RQData 配置可放在 `.vntrader/vt_setting.json`。该目录已被 Git 忽略，项目不会读取工作区外的旧工程凭据。

## 启动

在项目根目录初始化数据库：

```powershell
python scripts/init_db.py
```

启动后端：

```powershell
cd C:\Users\24084\Desktop\test2\gyro_nicert
python scripts\init_db.py
python -m uvicorn backend.main:app --reload
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- API 文档：<http://127.0.0.1:8000/docs>

另开一个终端启动前端：

```powershell
cd C:\Users\24084\Desktop\test2\gyro_nicert\frontend
npm install
npm run dev
```

默认前端地址通常为 <http://localhost:5173>。后端不在 `http://127.0.0.1:8000` 时，设置 `VITE_API_BASE_URL`。

## 工作台使用流程

### 1. 选择策略来源

启动配置提供三种方式：

1. **自然语言生成**：选择或新建策略描述文本，生成 vn.py CTA 策略代码。
2. **直接粘贴策略代码**：填写策略名称并粘贴完整 `strategy.py`。
3. **从本地上传策略代码**：直接选择单个 `.py` 文件，平台读取、预览并登记其代码。

本地上传和粘贴代码复用相同的后端流程：策略登记 → baseline 回测 → 参数优化页面。

### 2. 配置回测

填写：

- 标的与交易所，例如 `511380.SSE`
- 输入周期，例如 `1m`
- 回测起止日期
- 手续费率、滑点、资金、合约大小和最小价格变动

对于策略内部用 `BarGenerator` 将 1 分钟 K 线聚合为 60 分钟 K 线的策略，工作台输入周期应选择 **`1m`**，不要选择 `60m` 或 `1h`。

### 3. 行情覆盖与真实回测

提交前端请求时，工作台会检查所选标的、周期和日期范围的本地行情覆盖情况。缺失或不完整时，前端会尝试调用数据下载接口补齐行情；真实回测只读取 `storage/db/market_data.sqlite` 中的数据。

`mode="real"` 为默认模式。真实模式使用老师版引擎的委托撮合、停止单、逐日盈亏和统计逻辑，同时通过适配器从 `storage/db/market_data.sqlite` 读取 K 线，不依赖 vn.py 的全局 MySQL/SQLite 数据库配置。`mode="mock"` 仅用于离线测试或明确的模拟回退。

当前工作台数据层只落库 K 线，因此平台回测默认并仅开放老师引擎的 `BAR` 模式。老师引擎本身保留 `TICK` 撮合能力；在本地 Tick 表、覆盖检查和下载链路接入前，请求 `data_mode="tick"` 会返回明确错误，不会静默改用 K 线。

### 4. 查看结果与优化

回测完成后可以查看：

- 策略累计收益与 Buy & Hold 对比
- 曲线最大回撤
- 夏普、交易数与其他 vn.py 指标
- 日度结果、成交记录和策略代码
- 可优化参数及自动/手动网格优化结果

Optuna 默认最多评估 200 次。若所有已选参数都是离散范围且唯一组合不足 200 组，平台会自动使用 Optuna `GridSampler` 将每个组合只回测一次，不会用重复参数补足 200 次；组合超过 200 组或包含连续分布时使用 TPE 抽样 200 次。

AI 生成的参数范围会按 run 和 baseline 版本缓存，包含参数分类、是否启用、范围、步长、解释、约束、虚拟参数和风险提示。重新进入参数优化页面时会恢复缓存内容；再次点击“AI 生成参数范围”会重新请求并覆盖旧缓存。

### 5. 加入策略池

接受某个 baseline 或优化变体后，可将其加入策略池。池快照会复制策略代码、配置、结果、曲线和成交记录，因此运行目录清理后仍可查看或重跑。

## 曲线与最大回撤口径

工作台的策略曲线使用单位仓位累计收益口径：

```text
C(t) = Σ(日 net_pnl / 昨日 close_price) × 100
DD(t) = C(t) - max(C(0...t))
最大回撤 = min(DD(t))
```

曲线、曲线最大回撤、优化表现表和策略池比较使用这一口径。它与 vn.py 基于账户资金 `balance` 计算的账户回撤是不同概念，页面不会将两者混为同一展示指标。

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
| run、曲线、成交 | `/api/runs` |
| 参数优化 | `/api/optimization/methods`、`/api/optimization/search-space`、`/api/optimization/suggest-space`、`/api/optimization/run` |
| 策略池 | `/api/pool` |
| 任务 | `/api/tasks` |

完整请求与响应结构以运行中的 <http://127.0.0.1:8000/docs> 为准。

## 数据与存储

- `storage/db/app.sqlite`：策略、任务、run、variant、策略池和产物索引。
- `storage/db/market_data.sqlite`：本地 K 线、覆盖范围和下载任务。
- `storage/runtime/runs/<run_id>/`：临时运行产物，包括 `strategy.py`、`config.json`、`result.json`、曲线与成交 CSV。
- `storage/pool/strategies/<pool_item_id>/`：长期池快照。

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
