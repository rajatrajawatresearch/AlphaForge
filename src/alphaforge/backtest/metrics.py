"""Backtesting performance metrics."""

import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.06, periods: int = 252) -> float:
    """Annualized Sharpe Ratio. risk_free_rate is annual (6% for India)."""
    if returns.empty or returns.std() == 0:
        return 0.0
    daily_rf = risk_free_rate / periods
    excess = returns - daily_rf
    return float(excess.mean() / excess.std() * np.sqrt(periods))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.06, periods: int = 252) -> float:
    """Annualized Sortino Ratio (only downside deviation)."""
    if returns.empty:
        return 0.0
    daily_rf = risk_free_rate / periods
    excess = returns - daily_rf
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0:
        return float("inf") if excess.mean() > 0 else 0.0
    return float(excess.mean() / downside.std() * np.sqrt(periods))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum drawdown as a negative percentage."""
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return float(drawdown.min())


def win_rate(pnls: list[float]) -> float:
    """Percentage of winning trades."""
    if not pnls:
        return 0.0
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)


def profit_factor(pnls: list[float]) -> float:
    """Gross profits / gross losses."""
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def avg_trade_duration(durations: list[float]) -> float:
    """Average trade duration in hours."""
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def compute_all_metrics(
    equity_curve: pd.Series,
    trade_pnls: list[float],
    trade_durations: list[float] | None = None,
) -> dict:
    """Compute all performance metrics."""
    returns = equity_curve.pct_change().dropna()

    return {
        "total_return_pct": float((equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100) if len(equity_curve) > 1 else 0,
        "sharpe_ratio": sharpe_ratio(returns),
        "sortino_ratio": sortino_ratio(returns),
        "max_drawdown_pct": max_drawdown(equity_curve) * 100,
        "win_rate_pct": win_rate(trade_pnls) * 100,
        "profit_factor": profit_factor(trade_pnls),
        "total_trades": len(trade_pnls),
        "avg_trade_pnl": sum(trade_pnls) / len(trade_pnls) if trade_pnls else 0,
        "best_trade": max(trade_pnls) if trade_pnls else 0,
        "worst_trade": min(trade_pnls) if trade_pnls else 0,
        "avg_duration_hours": avg_trade_duration(trade_durations) if trade_durations else 0,
    }
