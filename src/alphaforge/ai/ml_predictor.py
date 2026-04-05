"""XGBoost + LightGBM ensemble for price prediction."""

import logging
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

logger = logging.getLogger("alphaforge.ai")

MODEL_DIR = Path("data/models")


class MLPredictor:
    """Ensemble ML predictor using XGBoost and LightGBM."""

    def __init__(self):
        self.xgb_model = None
        self.lgb_model = None
        self._feature_names: list[str] = []

    def train(self, X: pd.DataFrame, y: pd.Series, symbol: str = "default") -> dict:
        """Train XGBoost and LightGBM models with TimeSeriesSplit cross-validation.

        Returns:
            dict with training metrics.
        """
        import lightgbm as lgb
        import xgboost as xgb
        from sklearn.metrics import accuracy_score, f1_score

        self._feature_names = list(X.columns)

        # TimeSeriesSplit — 5 splits
        tscv = TimeSeriesSplit(n_splits=5)
        xgb_scores, lgb_scores = [], []

        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            # XGBoost
            xgb_clf = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric="logloss",
                verbosity=0,
            )
            xgb_clf.fit(X_train, y_train)
            xgb_pred = xgb_clf.predict(X_test)
            xgb_scores.append(accuracy_score(y_test, xgb_pred))

            # LightGBM
            lgb_clf = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                verbosity=-1,
            )
            lgb_clf.fit(X_train, y_train)
            lgb_pred = lgb_clf.predict(X_test)
            lgb_scores.append(accuracy_score(y_test, lgb_pred))

        # Final models trained on all data
        import xgboost as xgb_mod
        import lightgbm as lgb_mod

        self.xgb_model = xgb_mod.XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", verbosity=0,
        )
        self.xgb_model.fit(X, y)

        self.lgb_model = lgb_mod.LGBMClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, verbosity=-1,
        )
        self.lgb_model.fit(X, y)

        # Save models
        self._save(symbol)

        metrics = {
            "xgb_cv_accuracy": np.mean(xgb_scores),
            "lgb_cv_accuracy": np.mean(lgb_scores),
            "ensemble_cv_accuracy": (np.mean(xgb_scores) + np.mean(lgb_scores)) / 2,
            "samples": len(X),
            "features": len(self._feature_names),
        }
        logger.info("Training complete for %s: XGB=%.3f, LGB=%.3f, Ensemble=%.3f",
                     symbol, metrics["xgb_cv_accuracy"], metrics["lgb_cv_accuracy"],
                     metrics["ensemble_cv_accuracy"])
        return metrics

    def predict(self, X: pd.DataFrame) -> tuple[float, float]:
        """Predict using ensemble.

        Returns:
            (probability_up, confidence) — probability that price goes up, and confidence score.
        """
        if self.xgb_model is None or self.lgb_model is None:
            raise ValueError("Models not trained or loaded")

        # Align features
        for col in self._feature_names:
            if col not in X.columns:
                X[col] = 0

        X_aligned = X[self._feature_names]

        xgb_prob = self.xgb_model.predict_proba(X_aligned)[:, 1]
        lgb_prob = self.lgb_model.predict_proba(X_aligned)[:, 1]

        # Ensemble average
        ensemble_prob = (xgb_prob + lgb_prob) / 2.0
        prob = float(ensemble_prob[0])

        # Confidence: how far from 0.5 (uncertain)
        confidence = abs(prob - 0.5) * 2.0

        return prob, confidence

    def _save(self, symbol: str) -> None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        path = MODEL_DIR / f"{symbol}_{date_str}.pkl"
        with open(path, "wb") as f:
            pickle.dump({
                "xgb": self.xgb_model,
                "lgb": self.lgb_model,
                "features": self._feature_names,
            }, f)
        logger.info("Models saved: %s", path)

    def load(self, symbol: str, date_str: str | None = None) -> bool:
        """Load saved models. Returns True if successful."""
        if date_str:
            path = MODEL_DIR / f"{symbol}_{date_str}.pkl"
        else:
            # Find latest model for symbol
            paths = sorted(MODEL_DIR.glob(f"{symbol}_*.pkl"), reverse=True)
            if not paths:
                return False
            path = paths[0]

        if not path.exists():
            return False

        with open(path, "rb") as f:
            data = pickle.load(f)

        self.xgb_model = data["xgb"]
        self.lgb_model = data["lgb"]
        self._feature_names = data["features"]
        logger.info("Models loaded: %s", path)
        return True
