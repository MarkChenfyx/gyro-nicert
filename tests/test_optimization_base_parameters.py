import pytest

from backend.services.optimization_service import _resolve_base_parameters


SEARCH_SPACE = {
    "base_parameters": {
        "lookback_window": 15,
        "trailing_stop_pct": 1.8,
        "fixed_size": 1,
    },
    "parameters": [
        {"name": "lookback_window", "type": "int"},
        {"name": "trailing_stop_pct", "type": "float"},
    ],
    "hidden_parameters": [
        {"name": "fixed_size", "current": 1, "reason": "position_sizing"},
    ],
}


def test_edited_base_parameters_are_merged_with_strategy_defaults():
    resolved = _resolve_base_parameters(
        SEARCH_SPACE,
        {"lookback_window": 40, "trailing_stop_pct": 2},
    )

    assert resolved == {
        "lookback_window": 40,
        "trailing_stop_pct": 2.0,
        "fixed_size": 1,
    }


def test_hidden_base_parameter_cannot_be_overridden():
    with pytest.raises(ValueError, match="not editable: fixed_size"):
        _resolve_base_parameters(SEARCH_SPACE, {"fixed_size": 2})


def test_integer_base_parameter_rejects_fractional_values():
    with pytest.raises(ValueError, match="must be an integer: lookback_window"):
        _resolve_base_parameters(SEARCH_SPACE, {"lookback_window": 20.5})
