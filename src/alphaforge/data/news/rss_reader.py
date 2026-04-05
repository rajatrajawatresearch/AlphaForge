"""RSS feed reader for financial news."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import feedparser

from ...utils.time import IST

logger = logging.getLogger("alphaforge.data")


@dataclass(frozen=True, slots=True)
class NewsArticle:
    title: str
    summary: str
    link: str
    source: str
    published: datetime
    id: str = ""


class RSSReader:
    """Reads financial news from RSS feeds."""

    def __init__(self, feed_urls: list[str]):
        self.feed_urls = feed_urls
        self._seen_ids: set[str] = set()

    def fetch_new(self) -> list[NewsArticle]:
        """Fetch new articles from all feeds. Returns only unseen articles."""
        articles = []
        for url in self.feed_urls:
            try:
                feed = feedparser.parse(url)
                source = feed.feed.get("title", url)
                for entry in feed.entries:
                    article_id = entry.get("id", entry.get("link", entry.get("title", "")))
                    if article_id in self._seen_ids:
                        continue

                    self._seen_ids.add(article_id)

                    published = datetime.now(IST)
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            published = datetime(*entry.published_parsed[:6], tzinfo=IST)
                        except (ValueError, TypeError):
                            pass

                    articles.append(NewsArticle(
                        title=entry.get("title", ""),
                        summary=entry.get("summary", entry.get("description", "")),
                        link=entry.get("link", ""),
                        source=source,
                        published=published,
                        id=article_id,
                    ))
            except Exception as e:
                logger.error("RSS fetch error for %s: %s", url, e)

        if articles:
            logger.info("Fetched %d new articles from %d feeds", len(articles), len(self.feed_urls))
        return articles

    def reset(self) -> None:
        """Reset seen articles (e.g., start of new day)."""
        self._seen_ids.clear()
