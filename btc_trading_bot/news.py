from __future__ import annotations

import math
import re
import csv
import json
import calendar as calendar_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from btc_trading_bot.config import NewsFeed, Settings
from btc_trading_bot.models import (
    AssetSentiment,
    EconomicCalendarEvent,
    EconomicCalendarRisk,
    FuturesMetrics,
    Headline,
    MacroAnalysis,
    NewsEventSummary,
    SentimentAnalysis,
    SentimentSource,
)

BITCOIN_PATTERN = re.compile(
    r"\b(bitcoin|btc)\b", re.IGNORECASE
)
# Per-asset headline tagging. Full names match case-insensitively; short
# tickers match case-sensitively to avoid common-word false positives
# (e.g. "sui generis", "polka dot", "ada").
ASSET_NAME_RULES: dict[str, str] = {
    "BTC": r"\b(bitcoin|btc)\b",
    "ETH": r"\b(ethereum|ether)\b",
    "SOL": r"\bsolana\b",
    "BNB": r"\b(bnb|binance coin)\b",
    "XRP": r"\b(xrp|ripple)\b",
    "DOGE": r"\bdogecoin\b",
    "ADA": r"\bcardano\b",
    "LINK": r"\bchainlink\b",
    "AVAX": r"\bavalanche\b",
    "DOT": r"\bpolkadot\b",
    "SUI": r"\bsui network\b",
}
CASE_SENSITIVE_TICKER_ASSETS = frozenset(
    {"ETH", "SOL", "DOGE", "ADA", "LINK", "AVAX", "DOT", "SUI"}
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
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
POLYMARKET_SEARCH_URL = "https://gamma-api.polymarket.com/search"
DERIVATIVES_SOURCE_NAME = "Derivatives crowding"
NEWS_SOURCE_NAME = "Bitcoin headlines"
FEAR_GREED_SOURCE_NAME = "Crypto Fear & Greed"
POLYMARKET_SOURCE_NAME = "Polymarket Bitcoin markets"
SENTIMENT_SOURCE_WEIGHTS = {
    NEWS_SOURCE_NAME: 0.65,
    FEAR_GREED_SOURCE_NAME: 0.20,
    DERIVATIVES_SOURCE_NAME: 0.15,
    POLYMARKET_SOURCE_NAME: 0.10,
}
EVENT_RULES = (
    (
        "ETF flows",
        re.compile(r"\b(etf|exchange-traded fund|ibit|fbtc|gbtc|arkb)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Fed/rates",
        re.compile(r"\b(federal reserve|the fed|fomc|rate cut|rate hike|interest rates?|hawkish|dovish)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "CPI/inflation",
        re.compile(r"\b(cpi|consumer price index|inflation|disinflation|core prices?)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Jobs report",
        re.compile(r"\b(jobs report|nonfarm payrolls?|nfp|unemployment|labor market)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "SEC/regulation",
        re.compile(r"\b(sec|regulat(?:e|ion|or|ory)|lawsuit|settlement|approval|crackdown|ban)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Exchange security",
        re.compile(r"\b(exchange|wallet|bridge|protocol).*\b(hack|hacked|exploit|breach|stolen)\b|\b(hack|hacked|exploit|breach|stolen)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Liquidation cascade",
        re.compile(r"\b(liquidation|liquidations|liquidated|cascade|short squeeze|long squeeze)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Whale transfer",
        re.compile(r"\b(whale|large transfer|wallet transfer|moves? bitcoin|btc transfer)\b", re.IGNORECASE),
        "MEDIUM",
    ),
    (
        "Stablecoin risk",
        re.compile(r"\b(stablecoin|usdt|usdc|tether|depeg|reserve|attestation)\b", re.IGNORECASE),
        "HIGH",
    ),
)
POSITIVE_EVENT_PATTERN = re.compile(
    r"\b(approval|approve|inflow|record inflow|rate cut|dovish|cooler than expected|"
    r"beats expectations|adoption|rally|surge|breakout)\b",
    re.IGNORECASE,
)
BUILT_IN_CALENDAR_TYPES = {
    "CPI/inflation": "CPI/inflation",
    "PPI/inflation": "CPI/inflation",
    "Jobs report": "Jobs report",
    "Fed/rates": "Fed/rates",
}


def base_asset(symbol: str) -> str:
    """Return the base asset code for a CCXT symbol, e.g. ETH/USDT:USDT -> ETH."""
    return symbol.split("/", 1)[0].split(":", 1)[0].strip().upper()


@lru_cache(maxsize=None)
def _asset_patterns(asset: str) -> tuple[re.Pattern[str], ...]:
    asset = asset.strip().upper()
    patterns: list[re.Pattern[str]] = []
    name_rule = ASSET_NAME_RULES.get(asset)
    if name_rule is not None:
        patterns.append(re.compile(name_rule, re.IGNORECASE))
    if asset in CASE_SENSITIVE_TICKER_ASSETS or name_rule is None:
        ticker_flags = 0 if asset in CASE_SENSITIVE_TICKER_ASSETS else re.IGNORECASE
        patterns.append(re.compile(rf"\b{re.escape(asset)}\b", ticker_flags))
    return tuple(patterns)


def tracked_assets(settings: Settings) -> tuple[str, ...]:
    assets: list[str] = ["BTC"]
    for symbol in (settings.symbol, *settings.scanner_symbols):
        asset = base_asset(symbol)
        if asset and asset not in assets:
            assets.append(asset)
    return tuple(assets)


def tag_assets(title: str, assets: Iterable[str]) -> tuple[str, ...]:
    matched: list[str] = []
    for asset in assets:
        if any(pattern.search(title) for pattern in _asset_patterns(asset)):
            matched.append(asset)
    return tuple(matched)


class NewsError(RuntimeError):
    """Raised when all configured news sources fail."""


class NewsAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tracked_assets = tracked_assets(settings)
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
        worker_count = min(7, max(1, len(self.settings.feeds) + 1))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="rss-feed",
        ) as executor:
            futures = {
                executor.submit(self._fetch_feed, feed): feed
                for feed in self.settings.feeds
            }
            gdelt_future = executor.submit(self._fetch_gdelt_headlines)
            futures[gdelt_future] = NewsFeed("GDELT", "", "macro")
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

    def fetch_sentiment_sources(
        self,
    ) -> tuple[tuple[SentimentSource, ...], tuple[str, ...]]:
        sources: list[SentimentSource] = []
        errors: list[str] = []
        try:
            sources.append(self._fetch_fear_greed_source())
        except (requests.RequestException, ValueError, KeyError) as exc:
            errors.append(f"{FEAR_GREED_SOURCE_NAME}: {exc}")
        if self.settings.polymarket_sentiment_enabled:
            try:
                sources.append(self._fetch_polymarket_source())
            except (requests.RequestException, ValueError, KeyError) as exc:
                errors.append(f"{POLYMARKET_SOURCE_NAME}: {exc}")
        return tuple(sources), tuple(errors)

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
            assets = tag_assets(title, self.tracked_assets)
            if feed.category == "crypto" and not assets:
                continue
            published = _entry_date(entry, now)
            age_seconds = max(0.0, (now - published).total_seconds())
            if age_seconds > cutoff_seconds:
                continue
            parsed.append(
                classify_headline(
                    Headline(
                        title=title,
                        source=feed.name,
                        url=_entry_url(entry),
                        published_at=published,
                        category=feed.category,
                        assets=assets,
                    )
                )
            )
        return parsed

    def _fetch_gdelt_headlines(self) -> list[Headline]:
        session = _build_session(self.settings)
        query = (
            "(bitcoin OR btc OR cryptocurrency OR crypto OR "
            "\"Federal Reserve\" OR FOMC OR CPI OR inflation OR SEC OR ETF OR "
            "regulation OR liquidation) sourcelang:english"
        )
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": "40",
            "sort": "HybridRel",
        }
        try:
            response = session.get(
                f"{GDELT_DOC_URL}?{urlencode(params)}",
                timeout=self.settings.request_timeout_seconds,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; BTC-Tri-Factor-Bot/1.0; "
                        "+https://github.com/)"
                    ),
                },
            )
        finally:
            session.close()
        response.raise_for_status()
        return gdelt_headlines_from_payload(
            response.json(),
            now=datetime.now(timezone.utc),
            max_age_hours=max(self.settings.news_max_age_hours, 48),
            assets=self.tracked_assets,
        )

    def _fetch_fear_greed_source(self) -> SentimentSource:
        session = _build_session(self.settings)
        try:
            response = session.get(
                FEAR_GREED_URL,
                params={"limit": 1, "format": "json"},
                timeout=self.settings.request_timeout_seconds,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; BTC-Tri-Factor-Bot/1.0; "
                        "+https://github.com/)"
                    ),
                },
            )
        finally:
            session.close()
        response.raise_for_status()
        return fear_greed_source_from_payload(response.json())

    def _fetch_polymarket_source(self) -> SentimentSource:
        session = _build_session(self.settings)
        try:
            response = session.get(
                POLYMARKET_SEARCH_URL,
                params={
                    "q": self.settings.polymarket_search_query,
                    "events_status": "active",
                    "limit_per_type": self.settings.polymarket_market_limit,
                    "search_profiles": "false",
                    "keep_closed_markets": 0,
                },
                timeout=self.settings.request_timeout_seconds,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; BTC-Tri-Factor-Bot/1.0; "
                        "+https://github.com/)"
                    ),
                },
            )
        finally:
            session.close()
        response.raise_for_status()
        return polymarket_source_from_payload(
            response.json(),
            now=datetime.now(timezone.utc),
            limit=self.settings.polymarket_market_limit,
        )

    def analyze_sentiment(
        self,
        headlines: Iterable[Headline],
        sources: Iterable[SentimentSource] = (),
    ) -> SentimentAnalysis:
        now = datetime.now(timezone.utc)
        scored: list[Headline] = []
        btc_weighted_sum = 0.0
        btc_total_weight = 0.0
        btc_count = 0
        asset_totals: dict[str, list[float]] = {}
        for headline in headlines:
            if headline.category != "crypto":
                continue
            if not headline.assets:
                headline = replace(
                    headline,
                    assets=tag_assets(headline.title, self.tracked_assets),
                )
            score = self.analyzer.polarity_scores(headline.title)["compound"]
            age_hours = max(
                0.0, (now - headline.published_at).total_seconds() / 3600
            )
            recency_weight = math.pow(0.5, age_hours / 24.0)
            if "BTC" in headline.assets:
                btc_weighted_sum += score * recency_weight
                btc_total_weight += recency_weight
                btc_count += 1
            for asset in headline.assets:
                totals = asset_totals.setdefault(asset, [0.0, 0.0, 0.0])
                totals[0] += score * recency_weight
                totals[1] += recency_weight
                totals[2] += 1.0
            scored.append(classify_headline(replace(headline, sentiment=score)))

        headline_average = (
            btc_weighted_sum / btc_total_weight if btc_total_weight else 0.0
        )
        headline_average = _clamp(headline_average)
        asset_sentiment = tuple(
            AssetSentiment(
                asset=asset,
                score=_clamp(totals[0] / totals[1]) if totals[1] else 0.0,
                label=_sentiment_label(
                    _clamp(totals[0] / totals[1]) if totals[1] else 0.0
                ),
                headline_count=int(totals[2]),
                updated_at=now,
            )
            for asset, totals in sorted(asset_totals.items())
        )
        source_breakdown = [
            SentimentSource(
                name=NEWS_SOURCE_NAME,
                score=headline_average,
                label=_sentiment_label(headline_average),
                detail=f"{btc_count} recent Bitcoin headlines",
                updated_at=now,
            )
        ]
        source_breakdown.extend(sources)
        average = _weighted_source_score(source_breakdown)
        scored.sort(key=lambda item: item.published_at, reverse=True)
        return SentimentAnalysis(
            score=average,
            label=_sentiment_label(average),
            headlines=tuple(scored[: self.settings.headline_limit]),
            sources=tuple(source_breakdown),
            events=event_summaries(scored),
            asset_sentiment=asset_sentiment,
        )

    def analyze_macro(
        self,
        headlines: Iterable[Headline],
        calendar: EconomicCalendarRisk | None = None,
    ) -> MacroAnalysis:
        relevant: list[Headline] = []
        negative_alerts: list[Headline] = []
        scores: list[float] = []

        for headline in headlines:
            if not MACRO_PATTERN.search(headline.title):
                continue
            score = self.analyzer.polarity_scores(headline.title)["compound"]
            scored = classify_headline(replace(headline, sentiment=score))
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

        if calendar is not None and calendar.risk_multiplier < 1.0:
            multiplier = min(multiplier, calendar.risk_multiplier)
            if status == "NO MAJOR ALERTS":
                status = calendar.status
            elif status != "HIGH RISK" and calendar.status == "HIGH EVENT RISK":
                status = "HIGH RISK"

        displayed = negative_alerts if negative_alerts else relevant
        return MacroAnalysis(
            score=average,
            status=status,
            risk_multiplier=multiplier,
            alerts=tuple(displayed[:6]),
            events=event_summaries(relevant),
            calendar=calendar,
        )

    def analyze_economic_calendar(
        self,
        now: datetime | None = None,
    ) -> EconomicCalendarRisk | None:
        if not self.settings.economic_calendar_enabled:
            return None
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        events = [
            *self._load_configured_calendar_events(now),
            *_built_in_calendar_events(now, self.settings.economic_calendar_lookahead_hours),
        ]
        lookahead_until = now + timedelta(
            hours=self.settings.economic_calendar_lookahead_hours
        )
        pre = timedelta(hours=self.settings.economic_calendar_pre_event_window_hours)
        post = timedelta(hours=self.settings.economic_calendar_post_event_window_hours)
        active = tuple(
            event
            for event in events
            if event.scheduled_at - pre <= now <= event.scheduled_at + post
        )
        upcoming = tuple(
            event
            for event in events
            if now < event.scheduled_at <= lookahead_until and event not in active
        )
        if active:
            high_impact = any(event.impact == "HIGH" for event in active)
            status = "HIGH EVENT RISK" if high_impact else "ELEVATED EVENT RISK"
            multiplier = 0.55 if high_impact else 0.75
            names = ", ".join(event.name for event in active[:3])
            reason = f"Inside configured event window for {names}."
        elif upcoming:
            status = "EVENT WATCH"
            multiplier = 1.0
            next_event = min(upcoming, key=lambda event: event.scheduled_at)
            hours = (next_event.scheduled_at - now).total_seconds() / 3600.0
            reason = f"Next high-impact calendar event: {next_event.name} in {hours:.1f}h."
        else:
            status = "NO SCHEDULED EVENTS"
            multiplier = 1.0
            reason = "No configured high-impact events inside the lookahead window."
        return EconomicCalendarRisk(
            status=status,
            risk_multiplier=multiplier,
            active_events=tuple(sorted(active, key=lambda event: event.scheduled_at)),
            upcoming_events=tuple(sorted(upcoming, key=lambda event: event.scheduled_at)[:8]),
            reason=reason,
        )

    def _load_configured_calendar_events(
        self,
        now: datetime,
    ) -> tuple[EconomicCalendarEvent, ...]:
        path = self.settings.economic_calendar_path
        if path is None or not path.exists():
            return ()
        rows: list[dict[str, object]]
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                rows = payload.get("events", [])
            else:
                rows = []
        else:
            with path.open("r", encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
        events: list[EconomicCalendarEvent] = []
        lower_bound = now - timedelta(
            hours=self.settings.economic_calendar_post_event_window_hours
        )
        upper_bound = now + timedelta(
            hours=self.settings.economic_calendar_lookahead_hours
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = _calendar_event_from_row(row)
            if event is None:
                continue
            if lower_bound <= event.scheduled_at <= upper_bound:
                events.append(event)
        return tuple(events)

    def close(self) -> None:
        pass


def neutral_sentiment() -> SentimentAnalysis:
    return SentimentAnalysis(score=0.0, label="Neutral", headlines=())


def sentiment_for_asset(
    sentiment: SentimentAnalysis,
    asset: str,
    *,
    min_headlines: int = 2,
) -> tuple[SentimentAnalysis, bool]:
    """Rebuild the sentiment score with asset-specific headlines when available.

    Returns the (possibly adjusted) analysis and whether an asset-specific
    headline score replaced the Bitcoin headline component. Market-wide
    sources such as Fear & Greed and derivatives crowding keep their weights.
    """
    asset = asset.strip().upper()
    if asset == "BTC":
        return sentiment, False
    entry = next(
        (
            item
            for item in sentiment.asset_sentiment
            if item.asset == asset and item.headline_count >= min_headlines
        ),
        None,
    )
    if entry is None:
        return sentiment, False

    sources = tuple(
        replace(
            source,
            score=entry.score,
            label=_sentiment_label(entry.score),
            detail=f"{entry.headline_count} recent {asset} headlines",
        )
        if source.name == NEWS_SOURCE_NAME
        else source
        for source in sentiment.sources
    )
    if not any(source.name == NEWS_SOURCE_NAME for source in sources):
        sources = (
            SentimentSource(
                name=NEWS_SOURCE_NAME,
                score=entry.score,
                label=_sentiment_label(entry.score),
                detail=f"{entry.headline_count} recent {asset} headlines",
                updated_at=entry.updated_at,
            ),
            *sources,
        )
    score = _weighted_source_score(sources)
    return (
        replace(
            sentiment,
            score=score,
            label=_sentiment_label(score),
            sources=sources,
        ),
        True,
    )


def blend_derivatives_crowding(
    sentiment: SentimentAnalysis,
    metrics: FuturesMetrics | None,
) -> SentimentAnalysis:
    sources = tuple(
        source
        for source in sentiment.sources
        if source.name != DERIVATIVES_SOURCE_NAME
    )
    source = derivatives_crowding_source(metrics)
    if source is not None:
        sources = (*sources, source)
    if not sources:
        return sentiment
    score = _weighted_source_score(sources)
    return SentimentAnalysis(
        score=score,
        label=_sentiment_label(score),
        headlines=sentiment.headlines,
        sources=sources,
        events=sentiment.events,
        asset_sentiment=sentiment.asset_sentiment,
    )


def derivatives_crowding_source(
    metrics: FuturesMetrics | None,
) -> SentimentSource | None:
    if metrics is None:
        return None
    if metrics.crowding_score is not None:
        score = _clamp(metrics.crowding_score)
    else:
        values = []
        if metrics.funding_rate is not None:
            values.append(_clamp(metrics.funding_rate / 0.0005))
        for ratio in (
            metrics.long_short_ratio,
            metrics.top_trader_long_short_ratio,
            metrics.top_trader_position_ratio,
            metrics.taker_buy_sell_ratio,
        ):
            ratio_score = _ratio_score(ratio)
            if ratio_score is not None:
                values.append(ratio_score)
        if not values:
            return None
        score = _clamp(sum(values) / len(values))
    label = metrics.crowding_label or _sentiment_label(score)
    detail = metrics.crowding_reason or _derivatives_detail(metrics)
    return SentimentSource(
        name=DERIVATIVES_SOURCE_NAME,
        score=score,
        label=label,
        detail=detail,
        updated_at=metrics.updated_at,
    )


def neutral_macro() -> MacroAnalysis:
    return MacroAnalysis(
        score=0.0,
        status="UNAVAILABLE",
        risk_multiplier=1.0,
        alerts=(),
    )


def fear_greed_source_from_payload(payload: dict) -> SentimentSource:
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError("response did not include Fear & Greed data")
    latest = rows[0]
    value = float(latest["value"])
    score = _clamp((value - 50.0) / 50.0)
    classification = str(latest.get("value_classification") or _sentiment_label(score))
    timestamp = latest.get("timestamp")
    updated_at = None
    if timestamp is not None:
        updated_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    return SentimentSource(
        name=FEAR_GREED_SOURCE_NAME,
        score=score,
        label=classification,
        detail=f"Index {value:.0f}/100",
        updated_at=updated_at,
    )


def polymarket_source_from_payload(
    payload: object,
    *,
    now: datetime,
    limit: int = 12,
) -> SentimentSource:
    scored: list[tuple[float, float, str, float]] = []
    for market in _iter_polymarket_markets(payload):
        market_score = _polymarket_market_score(market)
        if market_score is None:
            continue
        score, weight, question, yes_price = market_score
        scored.append((score, weight, question, yes_price))
        if len(scored) >= limit:
            break
    if not scored:
        raise ValueError("response did not include usable active Bitcoin markets")
    weighted_sum = sum(score * weight for score, weight, _, _ in scored)
    total_weight = sum(weight for _, weight, _, _ in scored)
    score = _clamp(weighted_sum / total_weight) if total_weight else 0.0
    top = max(scored, key=lambda item: item[1])
    return SentimentSource(
        name=POLYMARKET_SOURCE_NAME,
        score=score,
        label=_sentiment_label(score),
        detail=(
            f"{len(scored)} active directional markets; "
            f"top Yes {top[3]:.0%}: {_truncate(top[2], 72)}"
        ),
        updated_at=now,
    )


def gdelt_headlines_from_payload(
    payload: dict,
    *,
    now: datetime,
    max_age_hours: int,
    assets: Iterable[str] = ("BTC",),
) -> list[Headline]:
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise ValueError("response did not include GDELT articles")
    cutoff_seconds = max_age_hours * 3600
    tracked = tuple(assets)
    headlines: list[Headline] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = _clean_text(str(article.get("title") or ""))
        if not title:
            continue
        published = _parse_gdelt_date(article.get("seendate"), now)
        if (now - published).total_seconds() > cutoff_seconds:
            continue
        domain = str(article.get("domain") or "GDELT")
        matched = tag_assets(title, tracked)
        category = "crypto" if matched else "macro"
        headlines.append(
            classify_headline(
                Headline(
                    title=title,
                    source=f"GDELT: {domain}",
                    url=str(article.get("url") or ""),
                    published_at=published,
                    category=category,
                    assets=matched,
                )
            )
        )
    if not headlines:
        raise ValueError("GDELT returned no recent matching articles")
    return headlines


def classify_headline(headline: Headline) -> Headline:
    event_type = "general"
    impact = "LOW"
    confidence = 0.0
    for candidate_type, pattern, candidate_impact in EVENT_RULES:
        if pattern.search(headline.title):
            event_type = candidate_type
            impact = candidate_impact
            confidence = 0.85 if candidate_impact == "HIGH" else 0.65
            break
    direction = _event_direction(headline.title, headline.sentiment)
    return replace(
        headline,
        event_type=event_type,
        event_impact=impact,
        event_direction=direction,
        event_confidence=confidence,
    )


def event_summaries(headlines: Iterable[Headline]) -> tuple[NewsEventSummary, ...]:
    grouped: dict[str, list[Headline]] = {}
    for headline in headlines:
        if headline.event_type == "general":
            continue
        grouped.setdefault(headline.event_type, []).append(headline)
    summaries: list[NewsEventSummary] = []
    for event_type, items in grouped.items():
        latest = max(items, key=lambda item: item.published_at)
        average = sum(item.sentiment for item in items) / len(items)
        impact = _max_impact(item.event_impact for item in items)
        summaries.append(
            NewsEventSummary(
                event_type=event_type,
                count=len(items),
                average_sentiment=_clamp(average),
                impact=impact,
                direction=_event_direction(latest.title, average),
                latest_at=latest.published_at,
                representative_title=latest.title,
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                {"HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(item.impact, 0),
                item.latest_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
    )


def _event_direction(title: str, sentiment: float) -> str:
    if NEGATIVE_RISK_PATTERN.search(title):
        return "BEARISH"
    if POSITIVE_EVENT_PATTERN.search(title):
        return "BULLISH"
    if sentiment >= 0.15:
        return "BULLISH"
    if sentiment <= -0.15:
        return "BEARISH"
    return "NEUTRAL"


def _max_impact(values: Iterable[str]) -> str:
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    return max(values, key=lambda value: rank.get(value, 0), default="LOW")


def _calendar_event_from_row(row: dict[str, object]) -> EconomicCalendarEvent | None:
    name = str(row.get("name") or row.get("event") or "").strip()
    raw_time = row.get("scheduled_at") or row.get("time") or row.get("datetime")
    if not name or raw_time is None:
        return None
    try:
        scheduled_at = _parse_calendar_datetime(raw_time)
    except (TypeError, ValueError):
        return None
    event_type = str(row.get("event_type") or row.get("type") or name).strip()
    event_type = BUILT_IN_CALENDAR_TYPES.get(event_type, event_type)
    impact = str(row.get("impact") or "HIGH").strip().upper()
    if impact not in {"LOW", "MEDIUM", "HIGH"}:
        impact = "HIGH"
    source = str(row.get("source") or "configured").strip() or "configured"
    return EconomicCalendarEvent(
        name=name,
        event_type=event_type,
        scheduled_at=scheduled_at,
        impact=impact,
        source=source,
    )


def _built_in_calendar_events(
    now: datetime,
    lookahead_hours: int,
) -> tuple[EconomicCalendarEvent, ...]:
    start = (now - timedelta(hours=12)).date()
    end = (now + timedelta(hours=lookahead_hours)).date()
    days = (end - start).days + 1
    events: list[EconomicCalendarEvent] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if _is_first_friday(day):
            events.append(
                _ny_event(
                    "U.S. jobs report / NFP",
                    "Jobs report",
                    day.year,
                    day.month,
                    day.day,
                    8,
                    30,
                )
            )
        if _is_second_weekday(day, weekday=2):
            events.append(
                _ny_event(
                    "U.S. CPI inflation release",
                    "CPI/inflation",
                    day.year,
                    day.month,
                    day.day,
                    8,
                    30,
                )
            )
        if _is_second_weekday(day, weekday=3):
            events.append(
                _ny_event(
                    "U.S. PPI inflation release",
                    "CPI/inflation",
                    day.year,
                    day.month,
                    day.day,
                    8,
                    30,
                )
            )
        if day.month in {1, 3, 4, 6, 7, 9, 10, 12} and _is_last_weekday(day, 2):
            events.append(
                _ny_event(
                    "FOMC rate decision watch",
                    "Fed/rates",
                    day.year,
                    day.month,
                    day.day,
                    14,
                    0,
                )
            )
    return tuple(
        event
        for event in events
        if now - timedelta(hours=12)
        <= event.scheduled_at
        <= now + timedelta(hours=lookahead_hours)
    )


def _ny_event(
    name: str,
    event_type: str,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
) -> EconomicCalendarEvent:
    scheduled_at = datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(timezone.utc)
    return EconomicCalendarEvent(
        name=name,
        event_type=event_type,
        scheduled_at=scheduled_at,
        impact="HIGH",
        source="built-in recurring watch",
    )


def _parse_calendar_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_first_friday(day) -> bool:
    return day.weekday() == 4 and 1 <= day.day <= 7


def _is_second_weekday(day, *, weekday: int) -> bool:
    return day.weekday() == weekday and 8 <= day.day <= 14


def _is_last_weekday(day, weekday: int) -> bool:
    _, days_in_month = calendar_module.monthrange(day.year, day.month)
    return day.weekday() == weekday and day.day + 7 > days_in_month


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


def _parse_gdelt_date(value: object, default: datetime) -> datetime:
    if not value:
        return default
    text = str(value)
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return default


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


def _weighted_source_score(sources: Iterable[SentimentSource]) -> float:
    weighted_sum = 0.0
    total_weight = 0.0
    for source in sources:
        weight = SENTIMENT_SOURCE_WEIGHTS.get(source.name, 0.10)
        weighted_sum += source.score * weight
        total_weight += weight
    return _clamp(weighted_sum / total_weight) if total_weight else 0.0


def _ratio_score(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return _clamp(math.log(value) / math.log(2.0))


def _derivatives_detail(metrics: FuturesMetrics) -> str:
    parts: list[str] = []
    if metrics.funding_rate is not None:
        parts.append(f"funding {metrics.funding_rate:+.4%}")
    if metrics.long_short_ratio is not None:
        parts.append(f"global L/S {metrics.long_short_ratio:.2f}")
    if metrics.top_trader_long_short_ratio is not None:
        parts.append(f"top account L/S {metrics.top_trader_long_short_ratio:.2f}")
    if metrics.top_trader_position_ratio is not None:
        parts.append(f"top position L/S {metrics.top_trader_position_ratio:.2f}")
    if metrics.taker_buy_sell_ratio is not None:
        parts.append(f"taker buy/sell {metrics.taker_buy_sell_ratio:.2f}")
    return ", ".join(parts) if parts else "No usable derivatives crowding inputs"


def _iter_polymarket_markets(payload: object) -> Iterable[dict[str, object]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(payload, dict):
        return
    markets = payload.get("markets")
    if isinstance(markets, list):
        for market in markets:
            if isinstance(market, dict):
                yield market
    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            event_markets = event.get("markets")
            if isinstance(event_markets, list):
                for market in event_markets:
                    if isinstance(market, dict):
                        yield market


def _polymarket_market_score(
    market: dict[str, object],
) -> tuple[float, float, str, float] | None:
    if market.get("closed") is True or market.get("active") is False:
        return None
    question = _clean_text(
        str(
            market.get("question")
            or market.get("title")
            or market.get("slug")
            or ""
        )
    )
    if not question or not BITCOIN_PATTERN.search(question):
        return None
    direction = _polymarket_question_direction(question)
    if direction is None:
        return None
    yes_price = _polymarket_yes_price(market)
    if yes_price is None:
        return None
    volume = _float_field(market, "volume24hr", "volume24hrClob", "volumeNum", "volume")
    liquidity = _float_field(market, "liquidityClob", "liquidityNum", "liquidity")
    weight = max(1.0, min(8.0, math.log10(max(volume, liquidity, 0.0) + 10.0)))
    score = _clamp(direction * ((yes_price - 0.5) * 2.0))
    return score, weight, question, yes_price


def _polymarket_question_direction(question: str) -> int | None:
    text = question.lower()
    bullish = (
        "above",
        "over",
        "greater than",
        "at or above",
        "reach",
        "hit",
        "all-time high",
        "ath",
        "new high",
        "higher than",
    )
    bearish = (
        "below",
        "under",
        "less than",
        "at or below",
        "drop",
        "crash",
        "dip",
        "lower than",
    )
    has_bullish = any(term in text for term in bullish)
    has_bearish = any(term in text for term in bearish)
    if has_bullish and not has_bearish:
        return 1
    if has_bearish and not has_bullish:
        return -1
    return None


def _polymarket_yes_price(market: dict[str, object]) -> float | None:
    outcomes = _json_list(market.get("outcomes"))
    prices = _json_list(market.get("outcomePrices"))
    if not prices:
        return None
    if outcomes:
        for index, outcome in enumerate(outcomes):
            if str(outcome).strip().lower() == "yes" and index < len(prices):
                return _price_or_none(prices[index])
    return _price_or_none(prices[0])


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _price_or_none(value: object) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= price <= 1.0:
        return price
    return None


def _float_field(market: dict[str, object], *names: str) -> float:
    for name in names:
        try:
            return float(market.get(name) or 0.0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max(0, max_length - 3)].rstrip() + "..."


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))
