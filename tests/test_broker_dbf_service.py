from __future__ import annotations

from datetime import date
import struct

from backend.data_manager import database
from backend.services import broker_dbf_service


def _write_dbf(path, fields, rows):
    record_length = 1 + sum(length for _name, length in fields)
    header_length = 32 + 32 * len(fields) + 1
    header = bytearray(header_length)
    header[0] = 3
    today = date.today()
    header[1:4] = bytes((today.year - 1900, today.month, today.day))
    struct.pack_into("<I", header, 4, len(rows))
    struct.pack_into("<H", header, 8, header_length)
    struct.pack_into("<H", header, 10, record_length)
    offset = 32
    for name, length in fields:
        encoded = name.encode("gbk")[:11]
        header[offset:offset + len(encoded)] = encoded
        header[offset + 11] = ord("C")
        header[offset + 16] = length
        offset += 32
    header[offset] = 0x0D
    body = bytearray()
    for row in rows:
        body.extend(b" ")
        for name, length in fields:
            encoded = str(row.get(name, "")).encode("gbk")[:length]
            body.extend(encoded.ljust(length, b" "))
    path.write_bytes(bytes(header + body + b"\x1a"))


def test_capture_is_idempotent_and_normalizes_account_data(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    account = "2____750003642____"
    _write_dbf(source / "x_account.dbf", [("账号", 32), ("总资产", 16), ("可用资金", 16), ("总市值", 16), ("盈亏", 16), ("交易日", 8)], [{"账号": account, "总资产": "1000000", "可用资金": "250000", "总市值": "750000", "盈亏": "1200", "交易日": "20260914"}])
    _write_dbf(source / "x_positions.dbf", [("账号", 32), ("市场", 4), ("证券代码", 8), ("当前拥股", 12), ("可用数量", 12), ("市值", 16)], [{"账号": account, "市场": "SH", "证券代码": "513120", "当前拥股": "12100", "可用数量": "12100", "市值": "15000"}])
    _write_dbf(source / "x_orders.dbf", [("账号", 32), ("市场", 4), ("证券代码", 8), ("委托日期", 8), ("委托时间", 8), ("委托编号", 12), ("委托数量", 12), ("成交数量", 12)], [{"账号": account, "市场": "SH", "证券代码": "513120", "委托日期": "20260914", "委托时间": "100001", "委托编号": "1", "委托数量": "12100", "成交数量": "12100"}])
    _write_dbf(source / "x_deals.dbf", [("账号", 32), ("市场", 4), ("证券代码", 8), ("成交日期", 8), ("成交时间", 8), ("成交编号", 12), ("成交数量", 12)], [{"账号": account, "市场": "SH", "证券代码": "513120", "成交日期": "20260914", "成交时间": "100002", "成交编号": "2", "成交数量": "12100"}])
    monkeypatch.setenv(broker_dbf_service.DBF_DIR_ENV, str(source))
    monkeypatch.setattr(database, "APP_DB_PATH", tmp_path / "app.sqlite")
    monkeypatch.setattr(broker_dbf_service, "BROKER_RAW_ROOT", tmp_path / "archive")

    first = broker_dbf_service.capture()
    second = broker_dbf_service.capture()
    overview = broker_dbf_service.overview()

    assert first["status"] == "completed"
    # 重复采集会重新导入同一份归档，用于把新增的交割单、资金流水补进已有快照；结果必须仍然只有一份。
    assert second["status"] == "refreshed"
    assert second["capture_id"] == first["capture_id"]
    assert overview["account"]["account_label"] == "账户 ****3642"
    assert overview["account"]["total_assets"] == 1_000_000
    assert overview["positions"][0]["vt_symbol"] == "513120.SSE"
    assert overview["positions"][0]["quantity"] == 12_100
    assert len(overview["orders"]) == 1
    assert len(overview["deals"]) == 1
    assert "account_key" not in overview["account"]


def test_capture_reads_settlements_and_fund_flows(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    account = "2____750003642____"
    _write_dbf(source / "x_account.dbf", [("账号", 32), ("总资产", 16), ("交易日", 8)], [{"账号": account, "总资产": "1000000", "交易日": "20260914"}])
    _write_dbf(
        source / "x_stkDelivery.dbf",
        [("资金账号", 32), ("日期", 8), ("成交时间", 8), ("证券代码", 8), ("证券名称", 12), ("操作", 8), ("成交数量", 12), ("成交价格", 12), ("成交金额", 16), ("手续费", 12), ("印花税", 12), ("其它杂费", 12), ("成交序号", 12), ("委托号", 12)],
        [{"资金账号": account, "日期": "20260911", "成交时间": "93101", "证券代码": "511380", "证券名称": "转债ETF", "操作": "卖出",
          "成交数量": "-1000.00", "成交价格": "13.2330", "成交金额": "13233.0000", "手续费": "0.1300", "印花税": "0.0000", "其它杂费": "0.0000", "成交序号": "2145853", "委托号": "567"}],
    )
    _write_dbf(
        source / "x_stkFundFlow.dbf",
        [("账号信息", 32), ("发生日期", 8), ("发生时间", 8), ("流水序号", 12), ("业务名称", 16), ("发生金额", 16), ("剩余金额", 16), ("证券代码", 8)],
        [{"账号信息": account, "发生日期": "20260911", "发生时间": "093101", "流水序号": "1", "业务名称": "证券卖出", "发生金额": "13233.00", "剩余金额": "70.31", "证券代码": "511380"},
         {"账号信息": account, "发生日期": "20260910", "发生时间": "150000", "流水序号": "2", "业务名称": "银证转账转入", "发生金额": "50000.00", "剩余金额": "50070.31", "证券代码": ""}],
    )
    monkeypatch.setenv(broker_dbf_service.DBF_DIR_ENV, str(source))
    monkeypatch.setattr(database, "APP_DB_PATH", tmp_path / "app.sqlite")
    monkeypatch.setattr(broker_dbf_service, "BROKER_RAW_ROOT", tmp_path / "archive")

    capture = broker_dbf_service.capture()
    overview = broker_dbf_service.overview()

    assert capture["counts"]["settlements"] == 1 and capture["counts"]["fund_flows"] == 2
    fees = {row["vt_symbol"]: row for row in overview["fee_summary"]}
    assert fees["511380.SSE"]["fee_bp"] == 0.0982  # 0.13 / 13233 * 10000
    assert overview["settlements"][0]["security_name"] == "转债ETF"
    assert {row["category"] for row in overview["cash_summary"]} == {"证券交易", "出入金"}
    assert [row["amount"] for row in overview["cash_summary"] if row["category"] == "出入金"] == [50_000]


def test_split_position_rows_are_merged(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    account = "2____750003642____"
    _write_dbf(source / "x_account.dbf", [("账号", 32), ("总资产", 16), ("交易日", 8)], [{"账号": account, "总资产": "1000000", "交易日": "20261016"}])
    fields = [("账号", 32), ("市场", 4), ("证券代码", 8), ("当前拥股", 12), ("成本价", 12), ("市值", 16)]
    _write_dbf(source / "x_positions.dbf", fields, [
        {"账号": account, "市场": "SH", "证券代码": "204001", "当前拥股": "3160", "成本价": "100", "市值": "316000"},
        {"账号": account, "市场": "SH", "证券代码": "204001", "当前拥股": "3130", "成本价": "100", "市值": "313000"},
    ])
    monkeypatch.setenv(broker_dbf_service.DBF_DIR_ENV, str(source))
    monkeypatch.setattr(database, "APP_DB_PATH", tmp_path / "app.sqlite")
    monkeypatch.setattr(broker_dbf_service, "BROKER_RAW_ROOT", tmp_path / "archive")

    capture = broker_dbf_service.capture()
    positions = broker_dbf_service.overview()["positions"]

    assert [(row["vt_symbol"], row["quantity"], row["cost_price"], row["market_value"]) for row in positions] == [("204001.SSE", 6290, 100, 629000)]
    assert any("204001.SSE" in warning for warning in capture["warnings"])


def test_stale_export_group_is_ignored(tmp_path, monkeypatch):
    import os
    from backend.services import broker_dbf_service
    for name, mtime in [("750_2_10159_account.dbf", 1), ("750_2_10159_positions.dbf", 1),
                        ("750_2_account.dbf", 2), ("750_2_positions.dbf", 2), ("750_2_stkDelivery.dbf", 2)]:
        path = tmp_path / name
        path.write_bytes(b"x")
        os.utime(path, (mtime * 1000, mtime * 1000))
    monkeypatch.setenv(broker_dbf_service.DBF_DIR_ENV, str(tmp_path))
    _root, files = broker_dbf_service._source_files()
    assert sorted(files) == ["750_2_account.dbf", "750_2_positions.dbf", "750_2_stkDelivery.dbf"]
