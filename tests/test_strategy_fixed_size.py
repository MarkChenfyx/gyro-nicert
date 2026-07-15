from backend.services.strategy_service import normalize_fixed_size
from strategy_generation.validation import validate_open_order_volumes

import pytest


def test_normalize_fixed_size_rewrites_existing_value():
    code = """class DemoStrategy:\n    fixed_size = 100\n"""

    normalized, changed, message = normalize_fixed_size(code)

    assert normalized == "class DemoStrategy:\n    fixed_size = 1\n"
    assert changed is True
    assert "normalized to 1" in message


def test_normalize_fixed_size_adds_missing_value_after_docstring():
    code = '''class DemoStrategy:\n    """Example."""\n    parameters = []\n'''

    normalized, changed, message = normalize_fixed_size(code)

    assert '    """Example."""\n    fixed_size = 1\n' in normalized
    assert changed is True
    assert "was missing" in message


def test_normalize_fixed_size_leaves_unit_position_unchanged():
    code = """class DemoStrategy:\n    fixed_size = 1\n"""

    normalized, changed, _ = normalize_fixed_size(code)

    assert normalized == code
    assert changed is False


def test_open_order_volume_accepts_self_fixed_size():
    code = """class DemoStrategy:\n    fixed_size = 1\n    def trade(self, price):\n        self.buy(price, self.fixed_size)\n        self.short(price=price, volume=self.fixed_size)\n"""

    validate_open_order_volumes(code)


@pytest.mark.parametrize("volume", ["self.target_size", "100", "self.fixed_size - self.pos"])
def test_open_order_volume_rejects_non_fixed_size(volume):
    code = f"""class DemoStrategy:\n    fixed_size = 1\n    def trade(self, price):\n        self.buy(price, {volume})\n"""

    with pytest.raises(ValueError, match="必须严格使用 self.fixed_size"):
        validate_open_order_volumes(code)
