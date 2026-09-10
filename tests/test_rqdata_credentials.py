from datetime import datetime
import sys
import types

from backend.data_manager.rqdata_client import PRICE_ADJUST_TYPE, RQDataClient, load_credentials


def test_rqdata_credentials_load_from_environment(monkeypatch):
    monkeypatch.setenv("GYRO_RQDATA_USERNAME", "demo-user")
    monkeypatch.setenv("GYRO_RQDATA_PASSWORD", "demo-password")

    credentials = load_credentials()

    assert credentials.username == "demo-user"
    assert credentials.password == "demo-password"
    assert credentials.source == "environment"


def test_rqdata_downloads_pre_adjusted_prices(monkeypatch):
    captured = {}

    class FakeFrame:
        def __len__(self):
            return 1

        def reset_index(self):
            return self

        def to_dict(self, *, orient):
            assert orient == "records"
            return [
                {
                    "datetime": datetime(2024, 1, 2),
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 100,
                    "total_turnover": 105,
                }
            ]

    def fake_get_price(*args, **kwargs):
        captured.update(kwargs)
        return FakeFrame()

    fake_rqdatac = types.SimpleNamespace(get_price=fake_get_price)
    monkeypatch.setitem(sys.modules, "rqdatac", fake_rqdatac)
    client = RQDataClient()
    monkeypatch.setattr(client, "init", lambda: {"initialized": True})

    rows = client.query_bars("510300", "SSE", "1d", "2024-01-01", "2024-01-03")

    assert PRICE_ADJUST_TYPE == "pre"
    assert captured["adjust_type"] == "pre"
    assert rows[0]["close"] == 1.05
