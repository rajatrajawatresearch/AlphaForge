"""Claude API-powered financial sentiment analysis."""

import json
import logging
from dataclasses import dataclass

import anthropic

logger = logging.getLogger("alphaforge.ai")

SYSTEM_PROMPT = """You are a financial sentiment analyzer for Indian stock markets (NSE/BSE).
Analyze the given news headline and body text. Return ONLY valid JSON with these fields:
{
  "sentiment": <float from -1.0 (very bearish) to 1.0 (very bullish)>,
  "confidence": <float from 0.0 to 1.0>,
  "impact": "<low|medium|high>",
  "affected_symbols": ["<SYMBOL1>", "<SYMBOL2>"],
  "reasoning": "<one sentence explanation>"
}
Do not include any text outside the JSON."""


@dataclass(frozen=True, slots=True)
class SentimentResult:
    sentiment: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    impact: str  # low, medium, high
    affected_symbols: list[str]
    reasoning: str
    raw_text: str = ""


class SentimentAnalyzer:
    """Analyzes financial news sentiment using Claude API."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514", max_tokens: int = 256):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def analyze(self, headline: str, body: str = "", symbol: str = "") -> SentimentResult:
        """Analyze sentiment of a news article.

        Args:
            headline: News headline.
            body: Article body (truncated to 2000 chars).
            symbol: Primary symbol context.

        Returns:
            SentimentResult with sentiment score and metadata.
        """
        content = f"Symbol: {symbol}\nHeadline: {headline}"
        if body:
            content += f"\nBody: {body[:2000]}"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )

            text = response.content[0].text.strip()
            return self._parse_response(text)

        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            return SentimentResult(
                sentiment=0.0, confidence=0.0, impact="low",
                affected_symbols=[], reasoning=f"API error: {e}",
            )
        except Exception as e:
            logger.error("Sentiment analysis error: %s", e)
            return SentimentResult(
                sentiment=0.0, confidence=0.0, impact="low",
                affected_symbols=[], reasoning=f"Error: {e}",
            )

    def analyze_batch(self, articles: list[dict]) -> list[SentimentResult]:
        """Analyze multiple articles. Each dict: {"headline": str, "body": str, "symbol": str}"""
        return [
            self.analyze(
                headline=a.get("headline", ""),
                body=a.get("body", ""),
                symbol=a.get("symbol", ""),
            )
            for a in articles
        ]

    def _parse_response(self, text: str) -> SentimentResult:
        """Parse Claude's JSON response into SentimentResult."""
        try:
            # Handle potential markdown code blocks
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]

            data = json.loads(text)
            return SentimentResult(
                sentiment=max(-1.0, min(1.0, float(data.get("sentiment", 0)))),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0)))),
                impact=data.get("impact", "low"),
                affected_symbols=data.get("affected_symbols", []),
                reasoning=data.get("reasoning", ""),
                raw_text=text,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse sentiment response: %s", e)
            return SentimentResult(
                sentiment=0.0, confidence=0.0, impact="low",
                affected_symbols=[], reasoning=f"Parse error: {e}",
                raw_text=text,
            )
