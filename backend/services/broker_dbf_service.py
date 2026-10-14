"""Read-only capture and presentation of broker DBF exports."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.common.time_utils import BEIJING_TZ, now_iso
from backend.core.environment import env
from backend.core.paths import BROKER_RAW_ROOT, stored_path
from backend.repositories import broker_repository, live_repository
from backend.services.dbf_reader import read_dbf_bytes


DBF_DIR_ENV = "GYRO_LIVE_BROKER_DBF_DIR"
_CAPTURE_LOCK = threading.Lock()


def _pick(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) >= 8 else ""


def _clock(value: Any) -> str:
    text = re.sub(r"\D", "", str(value or "")).zfill(6)[-6:]
    return f"{text[:2]}:{text[2:4]}:{text[4:]}" if text != "000000" else ""


def _account_identity(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip()
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    groups = re.findall(r"\d{6,}", raw)
    visible = groups[-1][-4:] if groups else key[:4]
    return key, f"账户 ****{visible}"


def _vt_symbol(market: Any, symbol: Any) -> str:
    code = str(symbol or "").strip()
    name = str(market or "").strip().upper()
    exchange = "SSE" if name in {"SH", "SSE", "1", "沪A"} else "SZSE" if name in {"SZ", "SZSE", "2", "深A"} else name
    if not exchange and code:  # 交割单和资金流水没有市场字段，按代码前缀判断
        exchange = "SSE" if code[0] in {"5", "6"} else "SZSE" if code[0] in {"0", "1", "2", "3"} else ""
    return f"{code}.{exchange}" if code and exchange else code


def _flow_category(business: str) -> str:
    """资金流水分类：出入金要单独拿出来，算收益时必须剔除。"""
    text = str(business or "")
    if any(word in text for word in ("转账", "存入", "取出", "银证", "汇入", "汇出")):
        return "出入金"
    if any(word in text for word in ("买入", "卖出", "申购", "赎回")):
        return "证券交易"
    if "回购" in text:
        return "回购"
    if any(word in text for word in ("股息", "分红", "利息")):
        return "分红利息"
    return "其他"


def _stable_read(path: Path, attempts: int = 3) -> bytes:
    for attempt in range(attempts):
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if before.st_size == after.st_size == len(data) and before.st_mtime_ns == after.st_mtime_ns:
            return data
        if attempt + 1 < attempts:
            time.sleep(0.15)
    raise RuntimeError(f"{path.name} 正在写入，请稍后重试")


def configured_status() -> dict[str, Any]:
    raw = env(DBF_DIR_ENV)
    if not raw:
        return {"configured": False, "available": False, "message": f"尚未配置 {DBF_DIR_ENV}"}
    path = Path(raw).expanduser()
    if not path.is_dir():
        return {"configured": True, "available": False, "message": "券商 DBF 目录不存在"}
    count = len({item.resolve() for item in (*path.glob("*.dbf"), *path.glob("*.DBF"))})
    return {"configured": True, "available": count > 0, "file_count": count, "message": "" if count else "目录中没有 DBF 文件"}


def _source_files() -> tuple[Path, dict[str, bytes]]:
    status = configured_status()
    if not status["available"]:
        raise FileNotFoundError(status["message"])
    root = Path(env(DBF_DIR_ENV)).expanduser()
    paths = sorted({*root.glob("*.dbf"), *root.glob("*.DBF")}, key=lambda item: item.name.lower())
    # 目录里可能残留旧的导出（如 xxx_10159_account.dbf）；只取账户文件最新的那一组前缀。
    accounts = [path for path in paths if path.name.lower().endswith("_account.dbf")]
    if len(accounts) > 1:
        prefix = max(accounts, key=lambda path: path.stat().st_mtime).name[: -len("account.dbf")].lower()
        paths = [path for path in paths if path.name.lower().startswith(prefix) and "_" not in path.name[len(prefix):]]
    return root, {path.name: _stable_read(path) for path in paths}


def _rows(files: dict[str, bytes], suffix: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name, data in files.items():
        if name.lower().endswith(suffix.lower()):
            result.extend(read_dbf_bytes(data))
    return result


def _hash_key(*values: Any) -> str:
    return hashlib.sha256("|".join(str(value or "") for value in values).encode("utf-8")).hexdigest()


def capture() -> dict[str, Any]:
    with _CAPTURE_LOCK:
        _root, files = _source_files()
        digest = hashlib.sha256()
        for name, data in files.items():
            digest.update(name.lower().encode("utf-8")); digest.update(b"\0"); digest.update(data)
        source_hash = digest.hexdigest()
        existing = broker_repository.find_capture(source_hash)

        raw_accounts = _rows(files, "_account.dbf")
        raw_positions = _rows(files, "_positions.dbf")
        raw_orders = _rows(files, "_orders.dbf")
        raw_deals = _rows(files, "_deals.dbf")
        raw_settlements = _rows(files, "_stkdelivery.dbf")
        raw_flows = _rows(files, "_stkfundflow.dbf")
        if not raw_accounts:
            raise ValueError("account.dbf 中没有账户快照")

        captured_at = now_iso()
        account_date = _date(_pick(raw_accounts[0], "交易日"))
        fallback_dates = [_date(_pick(row, "委托日期", "成交日期", "交易日")) for row in raw_orders + raw_deals]
        trade_date = account_date or max((item for item in fallback_dates if item), default=datetime.now(BEIJING_TZ).date().isoformat())
        capture_id = f"broker_{trade_date.replace('-', '')}_{source_hash[:10]}"
        archive = BROKER_RAW_ROOT / capture_id
        temporary = BROKER_RAW_ROOT / f".{capture_id}.{uuid4().hex}.tmp"
        temporary.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        counts = {"files": len(files), "accounts": len(raw_accounts), "positions": len(raw_positions), "orders": len(raw_orders),
                  "deals": len(raw_deals), "settlements": len(raw_settlements), "fund_flows": len(raw_flows)}
        manifest = {"capture_id": capture_id, "source_hash": source_hash, "trade_date": trade_date, "captured_at": captured_at, "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}, "counts": counts}
        (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if archive.exists():
            shutil.rmtree(temporary)
        else:
            temporary.replace(archive)

        account_map: dict[str, tuple[str, str]] = {}
        accounts: list[dict[str, Any]] = []
        for row in raw_accounts:
            raw_id = _pick(row, "账号", "资金账号")
            key, label = _account_identity(raw_id)
            account_map[str(raw_id)] = (key, label)
            row_date = _date(_pick(row, "交易日")) or trade_date
            accounts.append({
                "account_key": key, "account_label": label, "trade_date": row_date, "capture_id": capture_id, "captured_at": captured_at,
                "total_assets": _number(_pick(row, "总资产")), "available_cash": _number(_pick(row, "可用资金")),
                "withdrawable_cash": _number(_pick(row, "可取资金")), "total_market_value": _number(_pick(row, "总市值")),
                "stock_market_value": _number(_pick(row, "股票市值")), "fund_market_value": _number(_pick(row, "基金市值")),
                "profit_loss": _number(_pick(row, "盈亏")), "login_status": str(_pick(row, "登录状态", default="") or ""),
            })
        default_identity = (accounts[0]["account_key"], accounts[0]["account_label"])

        def identity(row: dict[str, Any]) -> tuple[str, str]:
            raw = str(_pick(row, "账号", "资金账号", "账号信息", default="") or "")
            return account_map.get(raw) or (_account_identity(raw) if raw else default_identity)

        positions: list[dict[str, Any]] = []
        for row in raw_positions:
            key, _label = identity(row); market = _pick(row, "市场", "市场代码"); symbol = str(_pick(row, "证券代码", "代码", default="") or "").strip()
            positions.append({
                "account_key": key, "trade_date": trade_date, "capture_id": capture_id, "market": str(market or ""), "symbol": symbol, "vt_symbol": _vt_symbol(market, symbol),
                "quantity": _number(_pick(row, "当前拥股", "当前持仓", "股份余额")), "available_quantity": _number(_pick(row, "可用数量", "可用股份", "可用余额")),
                "in_transit": _number(_pick(row, "在途数量", "在途股份")), "frozen_quantity": _number(_pick(row, "冻结数量", "冻结股份")), "overnight_quantity": _number(_pick(row, "昨夜拥股", "昨夜持股", "昨日持仓")),
                "cost_price": _number(_pick(row, "成本价")), "market_value": _number(_pick(row, "市值")), "profit_loss": _number(_pick(row, "盈亏")),
            })

        orders: list[dict[str, Any]] = []
        for row in raw_orders:
            key, _label = identity(row); day = _date(_pick(row, "委托日期", "交易日")) or trade_date; market = _pick(row, "市场", "市场代码"); symbol = str(_pick(row, "证券代码", "代码", default="") or "").strip()
            entrust_id = str(_pick(row, "合同编号", "委托编号", default="") or ""); order_id = str(_pick(row, "订单编号", "系统编号", default="") or "")
            orders.append({
                "order_key": _hash_key(key, day, entrust_id, order_id, _pick(row, "委托时间"), symbol), "account_key": key, "trade_date": day, "capture_id": capture_id,
                "order_time": _clock(_pick(row, "委托时间")), "market": str(market or ""), "symbol": symbol, "vt_symbol": _vt_symbol(market, symbol),
                "action": str(_pick(row, "买卖方向", "操作", default="") or ""), "quote_type": str(_pick(row, "报价类型", default="") or ""),
                "order_price": _number(_pick(row, "委托价格")), "order_quantity": _number(_pick(row, "委托数量")), "filled_quantity": _number(_pick(row, "成交数量")),
                "filled_average_price": _number(_pick(row, "成交均价")), "filled_amount": _number(_pick(row, "成交金额")), "canceled_quantity": _number(_pick(row, "撤单数量")),
                "status": str(_pick(row, "委托状态", "状态", default="") or ""), "entrust_id": entrust_id, "order_id": order_id,
                "strategy_name": str(_pick(row, "策略名称", default="") or ""), "remark": str(_pick(row, "备注", default="") or ""), "reject_reason": str(_pick(row, "废单原因", "拒绝原因", default="") or ""), "updated_at": captured_at,
            })

        deals: list[dict[str, Any]] = []
        for row in raw_deals:
            key, _label = identity(row); day = _date(_pick(row, "成交日期", "交易日")) or trade_date; market = _pick(row, "市场", "市场代码"); symbol = str(_pick(row, "证券代码", "代码", default="") or "").strip()
            trade_id = str(_pick(row, "成交编号", "成交合同号", default="") or ""); entrust_id = str(_pick(row, "合同编号", "委托编号", default="") or ""); order_id = str(_pick(row, "订单编号", default="") or "")
            deals.append({
                "deal_key": _hash_key(key, day, trade_id, entrust_id, _pick(row, "成交时间"), symbol, _pick(row, "成交数量")), "account_key": key, "trade_date": day, "capture_id": capture_id,
                "deal_time": _clock(_pick(row, "成交时间")), "market": str(market or ""), "symbol": symbol, "vt_symbol": _vt_symbol(market, symbol),
                "action": str(_pick(row, "买卖方向", "操作", default="") or ""), "price": _number(_pick(row, "成交价格")), "quantity": _number(_pick(row, "成交数量")),
                "amount": _number(_pick(row, "成交金额")), "fee": _number(_pick(row, "手续费", "费用")), "entrust_id": entrust_id, "trade_id": trade_id, "order_id": order_id,
                "strategy_name": str(_pick(row, "策略名称", default="") or ""), "remark": str(_pick(row, "备注", default="") or ""), "updated_at": captured_at,
            })

        # 交割单：已清算的成交，手续费和印花税只有这里才有，当日成交里是 0。
        settlements: list[dict[str, Any]] = []
        for row in raw_settlements:
            key, _label = identity(row); day = _date(_pick(row, "日期", "成交日期")) or trade_date
            symbol = str(_pick(row, "证券代码", "代码", default="") or "").strip()
            trade_id = str(_pick(row, "成交序号", "成交编号", default="") or ""); entrust_id = str(_pick(row, "委托号", "合同编号", default="") or "")
            settlements.append({
                "settlement_key": _hash_key(key, day, trade_id, entrust_id, symbol, _pick(row, "成交数量")), "account_key": key, "trade_date": day, "capture_id": capture_id,
                "deal_time": _clock(_pick(row, "成交时间")), "symbol": symbol, "vt_symbol": _vt_symbol(_pick(row, "市场"), symbol),
                "security_name": str(_pick(row, "证券名称", default="") or ""), "action": str(_pick(row, "操作", "买卖", default="") or ""),
                "price": _number(_pick(row, "成交价格")), "quantity": _number(_pick(row, "成交数量")), "amount": _number(_pick(row, "成交金额")),
                "fee": _number(_pick(row, "手续费")), "stamp_tax": _number(_pick(row, "印花税")), "other_fee": _number(_pick(row, "其它杂费", "其他杂费")),
                "cash_balance": _number(_pick(row, "资金余额")), "share_balance": _number(_pick(row, "股份余额")),
                "entrust_id": entrust_id, "trade_id": trade_id, "updated_at": captured_at,
            })

        # 资金流水：出入金要单独分出来，否则资金曲线会把转账当成盈亏。
        flows: list[dict[str, Any]] = []
        for row in raw_flows:
            key, _label = identity(row); day = _date(_pick(row, "发生日期", "日期")) or trade_date
            symbol = str(_pick(row, "证券代码", default="") or "").strip(); business = str(_pick(row, "业务名称", default="") or "")
            serial = str(_pick(row, "流水序号", "定位串", default="") or "")
            flows.append({
                "flow_key": _hash_key(key, day, serial, business, _pick(row, "发生金额"), symbol), "account_key": key, "trade_date": day, "capture_id": capture_id,
                "flow_time": _clock(_pick(row, "发生时间")), "serial": serial, "business": business, "category": _flow_category(business),
                "amount": _number(_pick(row, "发生金额")), "balance": _number(_pick(row, "剩余金额")), "symbol": symbol,
                "vt_symbol": _vt_symbol(_pick(row, "交易市场"), symbol), "security_name": str(_pick(row, "证券名称", default="") or ""),
                "quantity": _number(_pick(row, "发生数量")), "price": _number(_pick(row, "成交价格")), "fee": _number(_pick(row, "手续费")),
                "updated_at": captured_at,
            })

        warnings = [] if any(item.get("strategy_name") for item in orders + deals) else ["券商导出未提供策略名称，当前只能按账户和标的核对"]
        if not raw_settlements:
            warnings.append("导出目录里没有交割单，真实手续费无法统计")
        broker_repository.save_capture({"capture_id": capture_id, "source_hash": source_hash, "trade_date": trade_date, "captured_at": captured_at, "artifact_path": stored_path(archive), "counts": counts, "warnings": warnings}, accounts, positions, orders, deals, settlements, flows)
        status = "refreshed" if existing else "completed"
        message = "DBF 内容未变化，已重新导入" if existing else "券商 DBF 已归档并导入"
        return {"status": status, "capture_id": capture_id, "trade_date": trade_date, "counts": counts, "warnings": warnings, "message": message}


def _reconciliation(positions: list[dict[str, Any]], broker_date: str) -> dict[str, Any]:
    broker = {str(row["vt_symbol"]): float(row.get("quantity") or 0) for row in positions}
    vnpy: dict[str, float] = {}; vnpy_date = ""; platform: dict[str, float] = {}; platform_date = ""
    messages: list[str] = []
    try:
        from backend.services import live_service
        settings, states = live_service.read_local_live_files()
        status = live_service.local_source_status(); vnpy_date = str(status.get("state_trade_date") or "")
        for instance, setting in settings.items():
            symbol = str(setting.get("vt_symbol") or ""); vnpy[symbol] = vnpy.get(symbol, 0) + float((states.get(instance) or {}).get("pos") or 0)
    except Exception as exc:
        messages.append(f"vn.py 状态不可用：{exc}")
    try:
        local_sources = [item for item in live_repository.list_sources() if str(item.get("source_kind")) == "local_dir"]
        if local_sources:
            records = live_repository.list_daily_records(str(local_sources[0]["source_id"]), limit=1)
            if records:
                from backend.core.paths import STORAGE_ROOT
                record = records[0]; platform_date = str(record.get("trade_date") or "")
                # 实盘记录存的是 storage 下的相对路径（live/...），不能直接当绝对路径用。
                stored = Path(str(record["artifact_path"]))
                rows_path = (stored if stored.is_absolute() else STORAGE_ROOT / stored) / "rows.json"
                for row in json.loads(rows_path.read_text(encoding="utf-8")):
                    if row.get("replay_pos") is not None:
                        symbol = str(row.get("vt_symbol") or ""); platform[symbol] = platform.get(symbol, 0) + float(row.get("replay_pos") or 0)
    except Exception as exc:
        messages.append(f"平台回放状态不可用：{exc}")
    dates_match = bool(broker_date and vnpy_date and platform_date and broker_date == vnpy_date == platform_date)
    items = []
    for symbol in sorted(set(broker) | set(vnpy) | set(platform)):
        values = [broker.get(symbol), vnpy.get(symbol), platform.get(symbol)]
        comparable = dates_match and all(value is not None for value in values)
        items.append({"vt_symbol": symbol, "broker_quantity": values[0], "vnpy_quantity": values[1], "platform_quantity": values[2], "status": "match" if comparable and len(set(values)) == 1 else "difference" if comparable else "not_comparable"})
    return {"dates": {"broker": broker_date, "vnpy": vnpy_date, "platform": platform_date}, "comparable": dates_match, "items": items, "messages": messages}


def overview() -> dict[str, Any]:
    latest = broker_repository.latest_capture()
    rows = broker_repository.overview_rows()
    if rows["account"]:
        rows["account"].pop("account_key", None)
    for collection in (rows["asset_curve"], rows["positions"], rows["orders"], rows["deals"], rows["settlements"], rows["fund_flows"]):
        for row in collection:
            row.pop("account_key", None)
    for row in rows["orders"]:
        row["order_time"] = _clock(row.get("order_time"))
    for row in rows["deals"] + rows["settlements"]:
        row["deal_time"] = _clock(row.get("deal_time"))
    for row in rows["fund_flows"]:
        row["flow_time"] = _clock(row.get("flow_time"))
    for row in rows["fee_summary"]:  # 实际费率，和回测参数对照用
        amount = float(row.get("amount") or 0)
        row["fee_bp"] = round(float(row.get("fee") or 0) / amount * 10000, 4) if amount else None
    result = {"source": configured_status(), "latest_capture": latest, **rows}
    result["reconciliation"] = _reconciliation(rows["positions"], rows["dates"]["positions"]) if rows["positions"] else {"dates": {}, "comparable": False, "items": [], "messages": []}
    return result
