"""Walk-forward optimization for strategy parameters."""

import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import product as iter_product

import pandas as pd

from ..strategy.base import BaseStrategy
from .engine import BacktestEngine
from .metrics import sharpe_ratio

logger = logging.getLogger("alphaforge.backtest")


class WalkForwardOptimizer:
    """Walk-forward optimization with rolling train/test windows."""

    def __init__(
        self,
        train_months: int = 6,
        test_months: int = 2,
        metric: str = "sharpe_ratio",
    ):
        self.train_months = train_months
        self.test_months = test_months
        self.metric = metric

    async def optimize(
        self,
        strategy_factory: callable,
        param_grid: dict[str, list],
        data: dict[str, pd.DataFrame],
        interval: str = "15minute",
    ) -> dict:
        """Run walk-forward optimization.

        Args:
            strategy_factory: callable(params_dict) → BaseStrategy
            param_grid: dict of param_name → list of values to try.
            data: Historical data dict.
            interval: Candle interval.

        Returns:
            dict with best params and results per window.
        """
        # Generate parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combos = [dict(zip(param_names, v)) for v in iter_product(*param_values)]

        logger.info("Walk-forward optimization: %d param combos, %d train/%d test months",
                     len(combos), self.train_months, self.test_months)

        # Determine data range
        all_dates = set()
        for df in data.values():
            if "timestamp" in df.columns:
                dates = pd.to_datetime(df["timestamp"])
                all_dates.update(dates.dt.date.unique())

        if not all_dates:
            return {"error": "No data available"}

        sorted_dates = sorted(all_dates)
        start = sorted_dates[0]
        end = sorted_dates[-1]

        # Rolling windows
        window_results = []
        train_start = start

        while True:
            train_end = train_start + timedelta(days=self.train_months * 30)
            test_start = train_end
            test_end = test_start + timedelta(days=self.test_months * 30)

            if test_end > end:
                break

            # Find best params on training data
            best_metric = float("-inf")
            best_params = combos[0] if combos else {}

            for params in combos:
                strategy = strategy_factory(params)
                engine = BacktestEngine()

                # Filter data to training window
                train_data = self._filter_data(data, train_start, train_end)
                if not train_data:
                    continue

                result = await engine.run(strategy, train_data, interval)
                metric_val = result.get(self.metric, 0)

                if metric_val > best_metric:
                    best_metric = metric_val
                    best_params = params

            # Evaluate best params on test data
            strategy = strategy_factory(best_params)
            engine = BacktestEngine()
            test_data = self._filter_data(data, test_start, test_end)

            if test_data:
                test_result = await engine.run(strategy, test_data, interval)
            else:
                test_result = {}

            window_results.append({
                "train_start": str(train_start),
                "train_end": str(train_end),
                "test_start": str(test_start),
                "test_end": str(test_end),
                "best_params": best_params,
                "train_metric": best_metric,
                "test_result": test_result,
            })

            logger.info("Window %s–%s: best params=%s, train %.3f, test %.3f",
                         train_start, test_end, best_params, best_metric,
                         test_result.get(self.metric, 0))

            # Slide window
            train_start += timedelta(days=self.test_months * 30)

        return {
            "windows": window_results,
            "avg_test_metric": (
                sum(w["test_result"].get(self.metric, 0) for w in window_results) / len(window_results)
                if window_results else 0
            ),
        }

    def _filter_data(
        self,
        data: dict[str, pd.DataFrame],
        start: datetime,
        end: datetime,
    ) -> dict[str, pd.DataFrame]:
        """Filter data dict to a date range."""
        filtered = {}
        for symbol, df in data.items():
            if "timestamp" not in df.columns:
                continue
            mask = (pd.to_datetime(df["timestamp"]).dt.date >= start) & \
                   (pd.to_datetime(df["timestamp"]).dt.date <= end)
            subset = df[mask]
            if not subset.empty:
                filtered[symbol] = subset.reset_index(drop=True)
        return filtered
