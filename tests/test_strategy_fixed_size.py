from backend.services.strategy_service import normalize_fixed_size


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
