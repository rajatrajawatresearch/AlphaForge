"""Ensemble scoring — combines LLM sentiment, ML prediction, and technical signals."""

import logging
from dataclasses import dataclass

logger = logging.getLogger("alphaforge.ai")


@dataclass(frozen=True, slots=True)
class EnsembleScore:
    composite: float  # 0.0 to 1.0
    direction: str  # "bullish", "bearish", "neutral"
    llm_score: float
    ml_score: float
    technical_score: float


class EnsembleScorer:
    """Combines three signal sources into a composite trading score."""

    def __init__(
        self,
        llm_weight: float = 0.3,
        ml_weight: float = 0.4,
        technical_weight: float = 0.3,
        threshold: float = 0.65,
    ):
        self.llm_weight = llm_weight
        self.ml_weight = ml_weight
        self.technical_weight = technical_weight
        self.threshold = threshold

    def score(
        self,
        llm_sentiment: float = 0.0,      # -1.0 to 1.0
        ml_probability: float = 0.5,      # 0.0 to 1.0 (probability of up)
        technical_signal: float = 0.0,    # -1.0 to 1.0
    ) -> EnsembleScore:
        """Compute ensemble score from three signal sources.

        Args:
            llm_sentiment: Claude sentiment score (-1 bearish to +1 bullish).
            ml_probability: ML model's probability of price going up (0 to 1).
            technical_signal: Technical indicator signal (-1 to +1).

        Returns:
            EnsembleScore with composite score and direction.
        """
        # Normalize all to 0-1 range
        llm_norm = (llm_sentiment + 1.0) / 2.0  # -1..1 → 0..1
        ml_norm = ml_probability                  # already 0..1
        tech_norm = (technical_signal + 1.0) / 2.0  # -1..1 → 0..1

        composite = (
            self.llm_weight * llm_norm
            + self.ml_weight * ml_norm
            + self.technical_weight * tech_norm
        )

        if composite > self.threshold:
            direction = "bullish"
        elif composite < (1.0 - self.threshold):
            direction = "bearish"
        else:
            direction = "neutral"

        return EnsembleScore(
            composite=round(composite, 4),
            direction=direction,
            llm_score=round(llm_norm, 4),
            ml_score=round(ml_norm, 4),
            technical_score=round(tech_norm, 4),
        )

    def should_trade(self, score: EnsembleScore) -> bool:
        """Check if the ensemble score warrants a trade."""
        return score.direction != "neutral"
