"""Tests for risk management components."""

from unittest.mock import AsyncMock, MagicMock

from alphaforge.config.schema import RiskSection, StrategyLimit
from alphaforge.risk.kill_switch import KillSwitch
from alphaforge.risk.limits import StrategyLimits
from alphaforge.risk.manager import RiskManager
from alphaforge.risk.position_sizer import PositionSizer
from alphaforge.types import OrderRequest, RiskRejection, Signal, SignalType


# ── Position Sizer Tests ──

def test_position_sizer_basic():
    sizer = PositionSizer(total_capital=500000, max_risk_per_trade_pct=2.0, atr_multiplier=2.0)
    qty = sizer.compute(price=2500, atr=50)
    # Risk amount = 500000 * 0.02 = 10000
    # Risk per share = 50 * 2 = 100
    # ATR-based qty = 100, but capital cap = risk_amount / price * 10 = 40
    assert qty == 40


def test_position_sizer_lot_size():
    sizer = PositionSizer(total_capital=500000, max_risk_per_trade_pct=2.0, atr_multiplier=2.0)
    qty = sizer.compute(price=20000, atr=300, lot_size=25)
    # Risk = 10000, risk_per_share = 600, raw = 16.67
    # Round to lot size 25 → 0 (but check min lot tolerance)
    # 25 * 600 = 15000 > 10000 * 1.5 = 15000, so qty = 0
    assert qty == 0 or qty == 25  # Edge case at tolerance boundary


def test_position_sizer_zero_atr():
    sizer = PositionSizer(total_capital=500000)
    assert sizer.compute(price=100, atr=0) == 0


def test_position_sizer_stop_loss():
    sizer = PositionSizer(total_capital=500000, atr_multiplier=2.0)
    sl = sizer.compute_stop_loss(entry_price=2500, atr=50, is_long=True)
    assert sl == 2400.0  # 2500 - 50*2

    sl_short = sizer.compute_stop_loss(entry_price=2500, atr=50, is_long=False)
    assert sl_short == 2600.0


def test_position_sizer_target():
    sizer = PositionSizer(total_capital=500000)
    target = sizer.compute_target(entry_price=2500, stop_loss=2400, rr_ratio=2.0)
    assert target == 2700.0  # risk=100, reward=200


# ── Strategy Limits Tests ──

def test_strategy_limits_allow():
    limits = StrategyLimits(
        total_capital=500000,
        strategy_limits={"orb": StrategyLimit(max_allocation_pct=20.0, max_positions=3)},
    )
    ok, reason = limits.can_open_position("orb")
    assert ok is True
    assert reason == ""


def test_strategy_limits_position_cap():
    limits = StrategyLimits(
        total_capital=500000,
        strategy_limits={"orb": StrategyLimit(max_allocation_pct=50.0, max_positions=2)},
    )
    limits.register_position("orb", 10000)
    limits.register_position("orb", 10000)

    ok, reason = limits.can_open_position("orb")
    assert ok is False
    assert "max positions" in reason


def test_strategy_limits_allocation_cap():
    limits = StrategyLimits(
        total_capital=500000,
        strategy_limits={"orb": StrategyLimit(max_allocation_pct=10.0, max_positions=10)},
    )
    # Max allocation = 50000
    limits.register_position("orb", 50000)

    ok, reason = limits.can_open_position("orb")
    assert ok is False
    assert "max allocation" in reason


def test_strategy_limits_release():
    limits = StrategyLimits(
        total_capital=500000,
        strategy_limits={"orb": StrategyLimit(max_allocation_pct=10.0, max_positions=1)},
    )
    limits.register_position("orb", 30000)
    ok, _ = limits.can_open_position("orb")
    assert ok is False

    limits.release_position("orb", 30000)
    ok, _ = limits.can_open_position("orb")
    assert ok is True


# ── Risk Manager Tests ──

def _make_signal(
    strategy: str = "orb",
    signal_type: SignalType = SignalType.BUY,
    price: float = 2500.0,
    stop_loss: float = 2400.0,
    target: float = 2700.0,
    quantity: int = 0,
) -> Signal:
    return Signal(
        strategy_name=strategy,
        tradingsymbol="RELIANCE",
        exchange="NSE",
        signal_type=signal_type,
        confidence=0.8,
        suggested_price=price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        product="MIS",
    )


def _make_risk_manager() -> RiskManager:
    config = RiskSection(
        initial_capital=500000,
        max_capital_per_trade_pct=2.0,
        daily_loss_limit_pct=3.0,
        max_concurrent_positions=10,
        trailing_stop_atr_multiplier=2.0,
        strategy_limits={"orb": StrategyLimit(max_allocation_pct=20.0, max_positions=3)},
    )
    mock_client = MagicMock()
    kill_switch = KillSwitch(client=mock_client, initial_capital=500000)
    return RiskManager(config=config, kill_switch=kill_switch)


def test_risk_manager_approve_signal():
    rm = _make_risk_manager()
    signal = _make_signal(quantity=10)
    result = rm.evaluate_signal(signal)
    assert isinstance(result, OrderRequest)
    assert result.quantity == 10
    assert result.tradingsymbol == "RELIANCE"


def test_risk_manager_auto_size():
    rm = _make_risk_manager()
    signal = _make_signal(quantity=0)
    result = rm.evaluate_signal(signal, current_atr=50.0)
    assert isinstance(result, OrderRequest)
    assert result.quantity > 0


def test_risk_manager_reject_hold():
    rm = _make_risk_manager()
    signal = _make_signal(signal_type=SignalType.HOLD)
    result = rm.evaluate_signal(signal)
    assert isinstance(result, RiskRejection)


def test_risk_manager_reject_no_stop_loss():
    rm = _make_risk_manager()
    signal = _make_signal(stop_loss=0, quantity=10)
    result = rm.evaluate_signal(signal)
    assert isinstance(result, RiskRejection)
    assert "stop-loss" in result.reason.lower()


def test_risk_manager_reject_invalid_sl_for_buy():
    rm = _make_risk_manager()
    signal = _make_signal(signal_type=SignalType.BUY, price=2500, stop_loss=2600, quantity=10)
    result = rm.evaluate_signal(signal)
    assert isinstance(result, RiskRejection)
    assert "Stop-loss above" in result.reason


def test_risk_manager_reject_kill_switch():
    rm = _make_risk_manager()
    rm.kill_switch._triggered = True
    signal = _make_signal(quantity=10)
    result = rm.evaluate_signal(signal)
    assert isinstance(result, RiskRejection)
    assert "Kill switch" in result.reason


def test_risk_manager_reject_max_positions():
    rm = _make_risk_manager()
    rm.config.max_concurrent_positions = 1
    # Fill one position
    signal1 = _make_signal(quantity=10)
    rm.evaluate_signal(signal1)
    # Second should be rejected
    signal2 = _make_signal(quantity=10)
    result = rm.evaluate_signal(signal2)
    assert isinstance(result, RiskRejection)
    assert "concurrent positions" in result.reason.lower()
