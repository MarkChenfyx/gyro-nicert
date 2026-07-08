# gyro_nicert

Phase 1 builds the foundation for a maintainable Quant Research Workbench. This stage only defines the project skeleton, storage contract, SQLite schema, and minimal repository/service tests.

## Current Structure

- `frontend/`: reserved for a future React app.
- `backend/`: domain enums, path management, repositories, and services.
- `strategy_generation/`: converts natural-language strategy descriptions into strategy code.
- `backtesting/`: boundary for backtest engines; Phase 3.5 provides only mock/not-implemented behavior.
- `strategy_optimization/`: boundary for parameter optimizers; Phase 3.5 provides only mock/not-implemented behavior.
- `data_manager/`: database connection helpers for app and market SQLite databases.
- `strategies/`: generated, validated, and template strategy code folders.
- `storage/runtime/`: temporary run artifacts that may be cleaned.
- `storage/pool/`: long-lived strategy snapshots that must not depend on runtime files.
- `scripts/`: operational scripts such as database initialization.
- `tests/`: storage and task service tests.

## Initialize Databases

```bash
python scripts/init_db.py
```

This creates:

- `storage/db/app.sqlite`
- `storage/db/market_data.sqlite`

The script is idempotent and uses `CREATE TABLE IF NOT EXISTS`, so rerunning it will not destroy existing data.

## Run Tests

```bash
pytest tests/test_storage_contract.py tests/test_task_service.py
```

## Start Backend API

```bash
uvicorn backend.main:app --reload
```

The OpenAPI docs are available at:

- `http://127.0.0.1:8000/docs`

## Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` when the backend is not running on `http://127.0.0.1:8000`.

## Runtime vs Pool

`storage/runtime` stores temporary run outputs such as `manifest.json`, `input.json`, `config.json`, `strategy.py`, and variant results.

`storage/pool` stores accepted strategy snapshots. A pool snapshot copies the required runtime artifacts into its own folder so it remains usable after runtime cleanup.

## Not Included Yet

This phase does not implement React, FastAPI routes, real RQData integration, full strategy generation, backtesting, or optimization business flows.

## Phase 2

Phase 2 connects the Phase 1 storage contract to SQLite indexes.

Repository layer:

- `strategy_repository`: stores generated strategy metadata.
- `run_repository`: stores run metadata and status.
- `variant_repository`: stores variant result paths.
- `pool_repository`: stores long-lived pool item indexes and search filters.
- `artifact_repository`: stores important file references and hashes.

Service layer:

- `strategy_service`: registers already-generated strategy code.
- `run_service`: creates a simulated baseline run and records task/run/variant/artifact rows.
- `pool_service`: promotes a variant into a complete pool snapshot.
- `query_service`: reads run details, variant CSV results, trades, and pool curves.

`artifact_service` remains responsible for filesystem writes and complete pool snapshots. Repositories are responsible for SQLite persistence. Services orchestrate those two layers without writing SQL directly.

SQLite is the only supported database for v1. There is no MySQL, ORM, SQLAlchemy, or SQLModel in this phase.

Currently supported test chain:

- Register strategy.
- Create baseline run.
- Save baseline variant.
- Query run detail.
- Read variant curve and trades.
- Add variant to pool.
- Read pool item detail after deleting runtime artifacts.

Still not fully implemented:

- Production-grade parameter optimization API and frontend workflow.
- Full strategy-pool multi-variant comparison workflow.

## Phase 3 And 3.5

Phase 3 added a minimal strategy generation boundary. Phase 3.5 clarifies the core capability modules:

- `strategy_generation/`: input natural language, output `strategy_code`; it does not backtest, optimize, enter the pool, or write DB rows.
- `backtesting/`: input `strategy_code`, symbol, parameters, and config; output metrics, daily results, and trades; it does not generate strategies, optimize, or enter the pool.
- `strategy_optimization/`: input strategy code, parameter space, and backtest config; output recommended parameters, candidates, and grid summary; it optimizes parameters only and does not modify strategy code.
- `backend/services/`: orchestrates workflows, tasks, DB rows, artifacts, runs, and pool snapshots.

Backend services depend on strategy generation only through:

```python
generate_strategy_from_text(source_text: str, options: dict | None = None) -> dict
```

The default strategy generator is the API-backed generator. The old generator remains outside the main path.

`backtesting.run_backtest(...)` supports deterministic mock mode and real vn.py CTA backtesting from local SQLite market data. `strategy_optimization.optimize_parameters(...)` keeps mock mode for tests and now has a legacy-style adapter for manual grid parameter search; it does not write storage, create runs, or modify strategy code.

New services:

- `strategy_generation_service`: creates a strategy generation task, calls the natural-language boundary, registers generated code, writes `generation_report.json`, and records artifacts.
- `research_workflow_service`: optional orchestration for tests and demos; it calls strategy generation, then uses the existing run service with mock baseline results.

Automatic tests remain offline. They do not require real model keys, RQData, vn.py, FastAPI, React, `test1`, or old outputs.

## Current API And Frontend

The FastAPI API and React frontend are now the formal integration surfaces. The frontend calls only API endpoints; it does not read storage or SQLite.

Current API workflows:

- Generate strategy code.
- Create a research run through the temporary mock baseline fallback.
- View run details, curves, and trades.
- Add a variant to the strategy pool.
- View pool items and task history.

The mock baseline is a temporary fallback only. The next backend step is replacing `/api/research/create` internals with a real backtest service call while keeping the API contract stable.

## Phase 5A Data Layer

The data layer now exposes formal RQData-oriented market data APIs:

- `GET /api/data/coverage`
- `POST /api/data/download`
- `GET /api/data/symbols`

Implementation boundaries:

- `data_manager/rqdata_client.py`: initializes and queries RQData.
- `data_manager/market_repository.py`: stores bars, coverage, and download task rows in `storage/db/market_data.sqlite`.
- `data_manager/coverage_service.py`: reports local data coverage and missing ranges.
- `data_manager/download_service.py`: downloads bars through a data client and writes them to SQLite.
- `backend/api/data_api.py`: HTTP layer only; it calls data services and does not read/write SQLite directly.

RQData credentials are resolved at runtime in this order:

1. `GYRO_RQDATA_USERNAME` and `GYRO_RQDATA_PASSWORD`
2. `RQDATA_USERNAME` and `RQDATA_PASSWORD`
3. `GYRO_VT_SETTING_PATH`
4. local vn.py style `.vntrader/vt_setting.json`

Automatic tests use fake clients and do not consume RQData quota. The current data layer writes bars into a generic `bars` table and keeps `data_coverage` updated. Phase 5B connects real vn.py backtesting to this local market database while preserving the existing run/variant artifact contract.

## Phase 5B Real Backtesting

`backtesting.run_backtest(...)` now supports real vn.py CTA backtesting with local SQLite market data:

- `mode="real"` reads bars only from `storage/db/market_data.sqlite`.
- Strategy code remains a pure vn.py CTA `strategy.py`; it must define a class inheriting `vnpy_ctastrategy.CtaTemplate`.
- Backtests do not call RQData and do not auto-download missing data.
- Missing or partial local coverage returns a failed backtest result with `missing_ranges` and a suggestion to call `POST /api/data/download`.
- `mode="mock"` remains available for deterministic tests and explicit fallback.

`POST /api/research/create` defaults to real backtesting. Use `mode="mock"` in the request body when you need the old temporary fallback.
