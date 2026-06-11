from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from btc_trading_bot.config import NewsFeed, Settings
from btc_trading_bot.models import Headline, MacroAnalysis, SentimentAnalysis

BITCOIN_PATTERN = re.compile(
    r"\b(bitcoin|btc)\b", re.IGNORECASE
)
MACRO_PATTERN = re.compile(
    r"\b("
    r"federal reserve|the fed|fomc|interest rates?|rate (?:cut|hike)|"
    r"cpi|consumer price index|inflation|central banks?|ecb|bank of japan|"
    r"jobs report|nonfarm payrolls?|unemployment|gdp|recession|"
    r"liquidations?|regulation|sec|tariffs?|geopolitical"
    r")\b",
    re.IGNORECASE,
)
NEGATIVE_RISK_PATTERN = re.compile(
    r"\b("
    r"hike|higher for longer|hotter than expected|surge|spike|crackdown|"
    r"ban|lawsuit|war|attack|recession|default|sell-?off|plunge|slump|"
    r"liquidat(?:e|ed|ion|ions)|hawkish|risk-?off|outflow"
    r")\b",
    re.IGNORECASE,
)


class NewsError(RuntimeError):
    """Raised when all configured news sources fail."""


class NewsAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.analyzer = SentimentIntensityAnalyzer()
        self.analyzer.lexicon.update(
            {
                "bullish": 2.5,
                "bearish": -2.5,
                "breakout": 1.8,
                "rally": 2.0,
                "surge": 1.3,
                "adoption": 1.7,
                "approval": 1.8,
                "inflow": 1.4,
                "outflow": -1.4,
                "liquidation": -2.1,
                "liquidations": -2.1,
                "hack": -2.8,
                "hacked": -2.8,
                "crackdown": -2.2,
                "selloff": -2.4,
                "plunge": -2.4,
                "slump": -1.8,
                "hawkish": -1.5,
                "dovish": 1.5,
            }
        )

    def fetch(self) -> tuple[tuple[Headline, ...], tuple[str, ...]]:
        headlines: list[Headline] = []
        errors: list[str] = []
        worker_count = min(6, max(1, len(self.settings.feeds)))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="rss-feed",
        ) as executor:
            futures = {
                executor.submit(self._fetch_feed, feed): feed
                for feed in self.settings.feeds
            }
            for future in as_completed(futures):
                feed = futures[future]
                try:
                    headlines.extend(future.result())
                except (requests.RequestException, ValueError) as exc:
                    errors.append(f"{feed.name}: {exc}")

        deduplicated = _deduplicate(headlines)
        if not deduplicated:
            raise NewsError("All news feeds failed or returned no recent headlines")
        return tuple(deduplicated), tuple(errors)

    def _fetch_feed(self, feed: NewsFeed) -> list[Headline]:
        session = _build_session(self.settings)
        try:
            response = session.get(
                feed.url,
                timeout=self.settings.request_timeout_seconds,
                headers={
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; BTC-Tri-Factor-Bot/1.0; "
                        "+https://github.com/)"
                    ),
                },
            )
        finally:
            session.close()
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        entries = soup.find_all(["item", "entry"])
        if not entries:
            raise ValueError("response was not a recognized RSS/Atom feed")

        now = datetime.now(timezone.utc)
        cutoff_seconds = self.settings.news_max_age_hours * 3600
        parsed: list[Headline] = []
        for entry in entries[:40]:
            title_tag = entry.find("title")
            if title_tag is None:
                continue
            title = _clean_text(title_tag.get_text(" ", strip=True))
            if feed.category == "crypto" and not BITCOIN_PATTERN.search(title):
                continue
            published = _entry_date(entry, now)
            age_seconds = max(0.0, (now - published).total_seconds())
            if age_seconds > cutoff_seconds:
                continue
            parsed.append(
                Headline(
                    title=title,
                    source=feed.name,
                    url=_entry_url(entry),
                    published_at=published,
                    category=feed.category,
                )
            )
        return parsed

    def analyze_sentiment(
        self, headlines: Iterable[Headline]
    ) -> SentimentAnalysis:
        now = datetime.now(timezone.utc)
        scored: list[Headline] = []
        weighted_sum = 0.0
        total_weight = 0.0
        for headline in headlines:
            if headline.category != "crypto":
                continue
            score = self.analyzer.polarity_scores(headline.title)["compound"]
            age_hours = max(
                0.0, (now - headline.published_at).total_seconds() / 3600
            )
            recency_weight = math.pow(0.5, age_hours / 24.0)
            weighted_sum += score * recency_weight
            total_weight += recency_weight
            scored.append(replace(headline, sentiment=score))

        average = weighted_sum / total_weight if total_weight else 0.0
        average = _clamp(average)
        scored.sort(key=lambda item: item.published_at, reverse=True)
        return SentimentAnalysis(
            score=average,
            label=_sentiment_label(average),
            headlines=tuple(scored[: self.settings.headline_limit]),
        )

    def analyze_macro(self, headlines: Iterable[Headline]) -> MacroAnalysis:
        relevant: list[Headline] = []
        negative_alerts: list[Headline] = []
        scores: list[float] = []

        for headline in headlines:
            if not MACRO_PATTERN.search(headline.title):
                continue
            score = self.analyzer.polarity_scores(headline.title)["compound"]
            scored = replace(headline, sentiment=score)
            relevant.append(scored)
            if score <= -0.20 or NEGATIVE_RISK_PATTERN.search(headline.title):
                negative_alerts.append(scored)
            scores.append(score)

        average = _clamp(sum(scores) / len(scores)) if scores else 0.0
        negative_alerts.sort(
            key=lambda item: (item.sentiment, -item.published_at.timestamp())
        )
        relevant.sort(key=lambda item: item.published_at, reverse=True)

        alert_count = len(negative_alerts)
        if alert_count >= 3 or any(item.sentiment <= -0.65 for item in negative_alerts):
            status = "HIGH RISK"
            multiplier = 0.50
        elif alert_count:
            status = "ELEVATED RISK"
            multiplier = self.settings.defensive_multiplier
        elif relevant:
            status = "WATCHING MACRO"
            multiplier = 1.0
        else:
            status = "NO MAJOR ALERTS"
            multiplier = 1.0

        displayed = negative_alerts if negative_alerts else relevant
        return MacroAnalysis(
            score=average,
            status=status,
            risk_multiplier=multiplier,
            alerts=tuple(displayed[:6]),
        )

    def close(self) -> None:
        pass


def neutral_sentiment() -> SentimentAnalysis:
    return SentimentAnalysis(score=0.0, label="Neutral", headlines=())


def neutral_macro() -> MacroAnalysis:
    return MacroAnalysis(
        score=0.0,
        status="UNAVAILABLE",
        risk_multiplier=1.0,
        alerts=(),
    )


def _build_session(settings: Settings) -> requests.Session:
    retry = Retry(
        total=settings.max_retries,
        connect=settings.max_retries,
        read=settings.max_retries,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _entry_date(entry: object, default: datetime) -> datetime:
    for name in ("pubDate", "published", "updated", "dc:date"):
        tag = entry.find(name)
        if tag is None:
            continue
        text = tag.get_text(strip=True)
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return default


def _entry_url(entry: object) -> str:
    link = entry.find("link")
    if link is None:
        return ""
    href = link.get("href")
    return str(href or link.get_text(strip=True))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _deduplicate(headlines: Iterable[Headline]) -> list[Headline]:
    unique: dict[str, Headline] = {}
    for headline in headlines:
        key = re.sub(r"[^a-z0-9]+", " ", headline.title.lower()).strip()
        previous = unique.get(key)
        if previous is None or headline.published_at > previous.published_at:
            unique[key] = headline
    return sorted(unique.values(), key=lambda item: item.published_at, reverse=True)


def _sentiment_label(score: float) -> str:
    if score >= 0.50:
        return "Extremely Bullish"
    if score >= 0.15:
        return "Bullish"
    if score <= -0.50:
        return "Extremely Bearish"
    if score <= -0.15:
        return "Bearish"
    return "Neutral"


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))
