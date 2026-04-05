"""Tests for config loading and validation."""

import os

import pytest
from pydantic import ValidationError

from alphaforge.config.schema import RiskSection, StrategyLimit, AppConfig


def test_allocation_over_100_rejected():
    with pytest.raises(ValidationError, match="must be <= 100%"):
        RiskSection(strategy_limits={
            "a": StrategyLimit(max_allocation_pct=60),
            "b": StrategyLimit(max_allocation_pct=50),
        })


def test_allocation_exactly_100_accepted():
    r = RiskSection(strategy_limits={
        "a": StrategyLimit(max_allocation_pct=50),
        "b": StrategyLimit(max_allocation_pct=50),
    })
    assert sum(sl.max_allocation_pct for sl in r.strategy_limits.values()) == 100.0


def test_allocation_under_100_accepted():
    r = RiskSection(strategy_limits={
        "a": StrategyLimit(max_allocation_pct=30),
        "b": StrategyLimit(max_allocation_pct=20),
    })
    assert sum(sl.max_allocation_pct for sl in r.strategy_limits.values()) == 50.0


def test_risk_range_validation_negative():
    with pytest.raises(ValidationError):
        RiskSection(daily_loss_limit_pct=-1)


def test_risk_range_validation_too_high():
    with pytest.raises(ValidationError):
        RiskSection(daily_loss_limit_pct=25)


def test_env_var_interpolation():
    os.environ["KITE_API_KEY"] = "test_key"
    os.environ["KITE_API_SECRET"] = "test_secret"
    from alphaforge.config.loader import load_config
    config = load_config()
    assert config.broker.api_key == "test_key"
    assert config.broker.api_secret == "test_secret"


def test_config_has_paper_section():
    os.environ["KITE_API_KEY"] = "test"
    os.environ["KITE_API_SECRET"] = "test"
    from alphaforge.config.loader import load_config
    config = load_config()
    assert config.paper.slippage_pct == 0.05
    assert config.paper.latency_min_ms == 50


def test_config_strategy_limits_sum_100():
    os.environ["KITE_API_KEY"] = "test"
    os.environ["KITE_API_SECRET"] = "test"
    from alphaforge.config.loader import load_config
    config = load_config()
    total = sum(sl.max_allocation_pct for sl in config.risk.strategy_limits.values())
    assert total <= 100.0
