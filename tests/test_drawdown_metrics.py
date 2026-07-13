from backtesting.run import _metric_aliases
from strategy_optimization.optimizers.common import score_metrics


def test_metric_aliases_expose_drawdown_percent_as_canonical_field():
    metrics = _metric_aliases(
        {
            "annual_return": 12.5,
            "max_drawdown": -1234.5,
            "max_ddpercent": -6.78,
            "sharpe_ratio": 1.23,
            "return_drawdown_ratio": 1.84,
        }
    )

    assert metrics["max_drawdown_value"] == -1234.5
    assert metrics["max_drawdown_pct"] == -6.78
    assert metrics["max_drawdown"] == -6.78


def test_score_metrics_uses_drawdown_percent_instead_of_cash_value():
    metrics = {"max_drawdown": -1234.5, "max_ddpercent": -6.78}

    assert score_metrics(metrics, "drawdown") == -6.78
