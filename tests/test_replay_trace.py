from datetime import datetime

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData

from backend.backtesting import local_data_provider, replay_worker


SOURCE = '''from vnpy_ctastrategy import CtaTemplate
class Probe(CtaTemplate):
    parameters = ["fixed_size"]
    variables = ["step", "threshold"]
    fixed_size = 2
    threshold = 99
    step = 0
    def on_init(self): pass
    def on_bar(self, bar):
        self.step += 1
        if self.step == 1:
            entry_threshold = self.threshold
            if bar.close_price > entry_threshold:
                self.buy(101, self.fixed_size)
        elif self.step == 2:
            self.sell(95, self.fixed_size, stop=True)
            for orderid in self.buy(50, 1):
                self.cancel_order(orderid)
            self.threshold = 999
        elif self.step == 3:
            self.buy(10, 1)
'''


def test_fills_link_to_limit_and_stop_signals_without_changing_execution(tmp_path, monkeypatch):
    (tmp_path / "strategy.py").write_text(SOURCE, encoding="utf-8")
    bars = [BarData(gateway_name="TEST", symbol="511380", exchange=Exchange.SSE,
                    datetime=when, interval=Interval.MINUTE,
                    open_price=price, high_price=price + 1, low_price=price - 1, close_price=price)
            for when, price in [(datetime(2026, 9, 3, 14, 59), 100),
                                (datetime(2026, 9, 4, 9, 30), 100), (datetime(2026, 9, 4, 9, 31), 94)]]
    monkeypatch.setattr(local_data_provider, "load_bar_data", lambda *a: bars)
    monkeypatch.setattr(replay_worker, "replay_data_issue", lambda *a: "")
    payload = {"package_root": str(tmp_path), "module_path": "strategy.py", "class_name": "Probe",
               "vt_symbol": "511380.SSE", "start_date": "2026-09-03", "end_date": "2026-09-04", "prior_state": {"pos": 0}}
    result = replay_worker.run(payload)
    assert len(result["trades"]) == 2
    assert len(result["orders"]) == 4
    assert result["trades"][0]["signal_id"] == "signal_1"
    assert result["trades"][1]["signal_id"] == "signal_2"
    assert result["trades"][0]["position_before"] == 0
    assert result["trades"][0]["position_after"] == 2
    assert result["trades"][1]["position_after"] == 0
    assert result["trades"][1]["price"] == 94  # Gap through stop: actual engine fill differs from stop price.
    assert result["signals"][0]["datetime"].startswith("2026-09-03")
    assert result["trades"][0]["datetime"].startswith("2026-09-04")
    assert result["signals"][0]["variables"]["threshold"] == 99
    context = result["signals"][0]["contexts"][0]
    assert context["locals"]["entry_threshold"] == 99
    assert "self.buy" in context["code"]
    assert context["function"] == "on_bar"
    assert result["orders"][2]["status"] == "已撤销"
    assert result["orders"][3]["status"] == "提交中"
    assert result["orders"][1]["child_order_ids"] == [result["trades"][1]["vt_orderid"]]

    class NoTrace:
        def __init__(self, *a): pass
        def finish(self, trades): return {"trades": trades}
    monkeypatch.setattr(replay_worker, "ReplayTrace", NoTrace)
    baseline = replay_worker.run(payload)
    assert result["end_pos"] == baseline["end_pos"]
    assert [{key: trade[key] for key in expected} for trade, expected in zip(result["trades"], baseline["trades"])] == baseline["trades"]
