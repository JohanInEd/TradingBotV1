from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import ccxt
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands

from btc_trading_bot.config import Settings
from btc_trading_bot.exchange import resolve_exchange_spec
from btc_trading_bot.indicators import _clamp, _ema_signal, _macd_signal, _rsi_signal
from btc_trading_bot.market_context import _structure_regime, _volatility_regime

CANDLE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
DEFAULT_HISTORY_TIMEFRAMES = ("1h", "4h", "1d")
DEFAULT_OUTCOME_HORIZONS = (4, 12, 24)
ANALYSIS_GROUPS = (
    "timeframe",
    "score_bucket",
    "market_regime",
    "volatility_regime",
    "trend_range_context",
    "future_4h_movement",
    "future_12h_movement",
    "future_24h_movement",
    "long_tp_sl_outcome",
    "short_tp_sl_outcome",
)


class HistoryStoreError(RuntimeError):
    """Raised when local candle history cannot be used."""


class HistorySyncError(RuntimeError):
    """Raised when public historical candles cannot be synchronized."""


@dataclass(frozen=True, slots=True)
class HistorySyncResult:
    exchange: str
    symbol: str
    timeframe: str
    fetched_count: int
    stored_count: int
    start_at: datetime | None
    end_at: datetime | None
    latest_at: datetime | None


@dataclass(frozen=True, slots=True)
class HistoryAnalysisSettings:
    stop_loss_percent: float = 0.015
    reward_to_risk: float = 2.0
    row_limit: int = 5000


@dataclass(frozen=True, slots=True)
class HistoryStats:
    sample_count: int
    movement_4h_percent: float | None
    movement_12h_percent: float | None
    movement_24h_percent: float | None
    long_tp_count: int
    long_sl_count: int
    long_open_count: int
    short_tp_count: int
    short_sl_count: int
    short_open_count: int
    expected_long_r: float | None
    expected_short_r: float | None
    expected_r: float | None


@dataclass(frozen=True, slots=True)
class HistoryReport:
    row_count: int
    sample_count: int
    pending_count: int
    overall: HistoryStats
    groups: dict[str, dict[str, HistoryStats]]


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.initialize_schema()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candles (
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (exchange, symbol, timeframe, timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_candles_lookup_timestamp
                ON candles (exchange, symbol, timeframe, timestamp);
            CREATE INDEX IF NOT EXISTS idx_candles_timestamp
                ON candles (timestamp);
            """
        )
        self.connection.commit()

    def upsert_candles(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame | Iterable[Sequence[Any]],
    ) -> int:
        frame = normalize_candles(candles)
        if frame.empty:
            return 0
        fetched_at = _now_ms()
        rows = [
            (
                exchange,
                symbol,
                timeframe,
                _timestamp_ms(row.timestamp),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
                fetched_at,
            )
            for row in frame.itertuples(index=False)
        ]
        self.connection.executemany(
            """
            INSERT INTO candles (
                exchange, symbol, timeframe, timestamp,
                open, high, low, close, volume, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, symbol, timeframe, timestamp) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                fetched_at = excluded.fetched_at
            """,
            rows,
        )
        self.connection.commit()
        return len(rows)

    def count_candles(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM candles
            WHERE exchange = ? AND symbol = ? AND timeframe = ?
            """,
            (exchange, symbol, timeframe),
        ).fetchone()
        return int(row["count"])

    def latest_timestamp(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> datetime | None:
        latest = self.latest_timestamp_ms(exchange, symbol, timeframe)
        return _datetime_from_ms(latest) if latest is not None else None

    def latest_timestamp_ms(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> int | None:
        row = self.connection.execute(
            """
            SELECT MAX(timestamp) AS timestamp
            FROM candles
            WHERE exchange = ? AND symbol = ? AND timeframe = ?
            """,
            (exchange, symbol, timeframe),
        ).fetchone()
        value = row["timestamp"]
        return int(value) if value is not None else None

    def load_candles(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        values: list[Any] = [exchange, symbol, timeframe]
        where = ["exchange = ?", "symbol = ?", "timeframe = ?"]
        if start is not None:
            where.append("timestamp >= ?")
            values.append(_timestamp_ms(start))
        if end is not None:
            where.append("timestamp <= ?")
            values.append(_timestamp_ms(end))

        base_query = (
            "SELECT timestamp, open, high, low, close, volume "
            "FROM candles WHERE "
            + " AND ".join(where)
        )
        if limit is not None and limit > 0:
            query = (
                "SELECT * FROM ("
                + base_query
                + " ORDER BY timestamp DESC LIMIT ?"
                + ") ORDER BY timestamp ASC"
            )
            values.append(limit)
        else:
            query = base_query + " ORDER BY timestamp ASC"

        rows = self.connection.execute(query, values).fetchall()
        return _rows_to_frame(rows)

    def missing_candle_windows(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        windows = self.missing_candle_windows_ms(
            exchange,
            symbol,
            timeframe,
            start_ms=_timestamp_ms(start),
            end_ms=_timestamp_ms(end),
        )
        return [(_datetime_from_ms(start_ms), _datetime_from_ms(end_ms)) for start_ms, end_ms in windows]

    def missing_candle_windows_ms(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> list[tuple[int, int]]:
        if end_ms < start_ms:
            return []
        timeframe_ms = timeframe_to_milliseconds(timeframe)
        rows = self.connection.execute(
            """
            SELECT timestamp
            FROM candles
            WHERE exchange = ?
                AND symbol = ?
                AND timeframe = ?
                AND timestamp >= ?
                AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (exchange, symbol, timeframe, start_ms, end_ms),
        ).fetchall()
        expected = start_ms
        windows: list[tuple[int, int]] = []
        for row in rows:
            timestamp = int(row["timestamp"])
            if timestamp < expected:
                continue
            if timestamp > expected:
                windows.append((expected, min(timestamp - timeframe_ms, end_ms)))
            expected = max(expected, timestamp + timeframe_ms)
        if expected <= end_ms:
            windows.append((expected, end_ms))
        return windows

    def close(self) -> None:
        self.connection.close()


def normalize_candles(
    candles: pd.DataFrame | Iterable[Sequence[Any]],
) -> pd.DataFrame:
    if isinstance(candles, pd.DataFrame):
        frame = candles.copy()
    else:
        frame = pd.DataFrame(candles, columns=CANDLE_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    missing = [column for column in CANDLE_COLUMNS if column not in frame.columns]
    if missing:
        raise HistoryStoreError(f"Candles are missing columns: {', '.join(missing)}")

    frame = frame.loc[:, CANDLE_COLUMNS].copy()
    frame["timestamp_ms"] = frame["timestamp"].apply(_timestamp_ms)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(
        subset=["timestamp_ms", "open", "high", "low", "close", "volume"]
    )
    frame = (
        frame.drop_duplicates("timestamp_ms", keep="last")
        .sort_values("timestamp_ms")
        .reset_index(drop=True)
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    return frame.loc[:, CANDLE_COLUMNS]


def recent_contiguous_candles(
    candles: pd.DataFrame,
    timeframe: str,
    *,
    tolerance_seconds: int = 60,
) -> pd.DataFrame:
    data = normalize_candles(candles)
    if len(data) < 2:
        return data
    expected = pd.Timedelta(milliseconds=timeframe_to_milliseconds(timeframe))
    tolerance = pd.Timedelta(seconds=tolerance_seconds)
    timestamps = list(pd.to_datetime(data["timestamp"], utc=True))
    cut_index = 0
    for index in range(len(timestamps) - 1, 0, -1):
        gap = timestamps[index] - timestamps[index - 1]
        if abs(gap - expected) > tolerance:
            cut_index = index
            break
    return data.iloc[cut_index:].reset_index(drop=True)


def compute_candle_features(candles: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    data = normalize_candles(candles)
    if data.empty:
        return data
    close = pd.to_numeric(data["close"], errors="coerce")
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")

    data["ema20"] = EMAIndicator(close=close, window=20).ema_indicator()
    data["ema50"] = EMAIndicator(close=close, window=50).ema_indicator()
    data["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd"] = macd.macd()
    data["macd_signal"] = macd.macd_signal()
    data["macd_histogram"] = macd.macd_diff()
    atr = AverageTrueRange(high=high, low=low, close=close, window=14)
    data["atr_percent"] = atr.average_true_range() / close * 100.0
    bands = BollingerBands(close=close, window=20, window_dev=2)
    band_mid = bands.bollinger_mavg()
    data["bollinger_width_percent"] = (
        (bands.bollinger_hband() - bands.bollinger_lband()) / band_mid * 100.0
    )
    periods_per_day = max(1.0, 24.0 / timeframe_to_hours(timeframe))
    data["realized_volatility_percent"] = (
        close.pct_change().rolling(20).std() * math.sqrt(periods_per_day) * 100.0
    )
    rolling_high = high.rolling(50).max()
    rolling_low = low.rolling(50).min()
    range_span = rolling_high - rolling_low
    data["range_position_percent"] = (
        ((close - rolling_low) / range_span * 100.0)
        .where(range_span > 0, 50.0)
        .clip(lower=0.0, upper=100.0)
    )
    data["trend_spread_percent"] = (data["ema20"] - data["ema50"]) / close * 100.0

    scores: list[float | None] = [None] * len(data)
    score_buckets: list[str] = ["unknown"] * len(data)
    volatility_regimes: list[str] = ["UNKNOWN"] * len(data)
    trend_contexts: list[str] = ["UNKNOWN"] * len(data)
    market_regimes: list[str] = ["UNKNOWN"] * len(data)

    for index in range(len(data)):
        row = data.iloc[index]
        if index > 0:
            previous = data.iloc[index - 1]
            score = _technical_score(row, previous)
            scores[index] = score
            score_buckets[index] = _score_bucket(score)
        volatility = _regime_value(
            row.get("atr_percent"), row.get("realized_volatility_percent")
        )
        structure = _structure_value(
            row.get("trend_spread_percent"),
            row.get("bollinger_width_percent"),
            row.get("range_position_percent"),
        )
        volatility_regimes[index] = volatility
        trend_contexts[index] = structure
        market_regimes[index] = f"{volatility} / {structure}"

    data["score"] = scores
    data["score_bucket"] = score_buckets
    data["volatility_regime"] = volatility_regimes
    data["trend_range_context"] = trend_contexts
    data["market_regime"] = market_regimes
    return data


def compute_feature_outcomes(
    candles: pd.DataFrame,
    timeframe: str,
    settings: HistoryAnalysisSettings | None = None,
) -> pd.DataFrame:
    settings = settings or HistoryAnalysisSettings()
    data = compute_candle_features(candles, timeframe)
    if data.empty:
        return data
    timeframe_hours = timeframe_to_hours(timeframe)
    data["timeframe"] = timeframe
    timestamp_ms = [_timestamp_ms(value) for value in data["timestamp"]]
    timestamp_index = {value: index for index, value in enumerate(timestamp_ms)}

    for horizon in DEFAULT_OUTCOME_HORIZONS:
        movements: list[float | None] = []
        buckets: list[str] = []
        for index, entry in enumerate(data["close"]):
            movement = _future_movement(
                data,
                timestamp_ms,
                timestamp_index,
                index,
                float(entry),
                timeframe_hours,
                horizon,
            )
            movements.append(movement)
            buckets.append(_movement_bucket(movement))
        data[f"movement_{horizon}h_percent"] = movements
        data[f"future_{horizon}h_movement"] = buckets

    long_results: list[str] = []
    short_results: list[str] = []
    long_r_values: list[float | None] = []
    short_r_values: list[float | None] = []
    expected_r_values: list[float | None] = []
    for index, entry in enumerate(data["close"]):
        future = _future_path(
            data,
            timestamp_ms,
            timestamp_index,
            index,
            timeframe_hours,
            24,
        )
        long_result, long_r = _path_outcome(
            future,
            float(entry),
            side="LONG",
            stop_loss_percent=settings.stop_loss_percent,
            reward_to_risk=settings.reward_to_risk,
        )
        short_result, short_r = _path_outcome(
            future,
            float(entry),
            side="SHORT",
            stop_loss_percent=settings.stop_loss_percent,
            reward_to_risk=settings.reward_to_risk,
        )
        score = data.iloc[index].get("score")
        score_value = _finite_or_none(score)
        if score_value is None or abs(score_value) < 0.10:
            expected_r = None
        else:
            expected_r = long_r if score_value > 0 else short_r
        long_results.append(long_result)
        short_results.append(short_result)
        long_r_values.append(long_r)
        short_r_values.append(short_r)
        expected_r_values.append(expected_r)

    data["long_tp_sl_outcome"] = long_results
    data["short_tp_sl_outcome"] = short_results
    data["long_r"] = long_r_values
    data["short_r"] = short_r_values
    data["expected_r"] = expected_r_values
    return data


def analyze_history_store(
    store: HistoryStore,
    *,
    exchange: str,
    symbol: str,
    timeframes: Sequence[str],
    settings: HistoryAnalysisSettings | None = None,
) -> HistoryReport:
    settings = settings or HistoryAnalysisSettings()
    frames: list[pd.DataFrame] = []
    row_count = 0
    for timeframe in timeframes:
        candles = store.load_candles(
            exchange,
            symbol,
            timeframe,
            limit=settings.row_limit,
        )
        row_count += len(candles)
        if candles.empty:
            continue
        frames.append(compute_feature_outcomes(candles, timeframe, settings))

    if not frames:
        empty = _history_stats(pd.DataFrame())
        return HistoryReport(
            row_count=row_count,
            sample_count=0,
            pending_count=0,
            overall=empty,
            groups={group: {} for group in ANALYSIS_GROUPS},
        )

    data = pd.concat(frames, ignore_index=True)
    featured = data[data["score"].notna()].copy()
    completed = featured[featured["movement_24h_percent"].notna()].copy()
    groups: dict[str, dict[str, HistoryStats]] = {}
    for group_name in ANALYSIS_GROUPS:
        grouped: dict[str, list[int]] = defaultdict(list)
        for index, row in completed.iterrows():
            grouped[str(row.get(group_name, "UNKNOWN"))].append(index)
        groups[group_name] = {
            label: _history_stats(completed.loc[indexes])
            for label, indexes in sorted(grouped.items())
        }

    return HistoryReport(
        row_count=row_count,
        sample_count=len(completed),
        pending_count=len(featured) - len(completed),
        overall=_history_stats(completed),
        groups=groups,
    )


def format_history_report(report: HistoryReport) -> str:
    lines = [
        f"Historical candle rows: {report.row_count}",
        f"Completed outcome samples: {report.sample_count} ({report.pending_count} pending)",
        _history_stats_line("Overall", report.overall),
    ]
    for group_name in ANALYSIS_GROUPS:
        group = report.groups.get(group_name, {})
        if not group:
            continue
        lines.append("")
        lines.append(f"By {group_name.replace('_', ' ')}:")
        for label, stats in group.items():
            lines.append(_history_stats_line(f"  {label}", stats))
    return "\n".join(lines)


def sync_history(
    store: HistoryStore,
    exchange_client: Any,
    *,
    exchange: str,
    symbol: str,
    timeframes: Sequence[str],
    since: datetime | None = None,
    until: datetime | None = None,
    batch_limit: int = 1000,
    max_batches: int = 20,
) -> list[HistorySyncResult]:
    return [
        sync_timeframe(
            store,
            exchange_client,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            until=until,
            batch_limit=batch_limit,
            max_batches=max_batches,
        )
        for timeframe in timeframes
    ]


def sync_timeframe(
    store: HistoryStore,
    exchange_client: Any,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    since: datetime | None = None,
    until: datetime | None = None,
    batch_limit: int = 1000,
    max_batches: int = 20,
) -> HistorySyncResult:
    if batch_limit <= 0 or max_batches <= 0:
        raise HistorySyncError("Batch limit and max batches must be positive")
    timeframe_ms = timeframe_to_milliseconds(timeframe)
    end_ms = _timestamp_ms(until or datetime.now(timezone.utc)) - timeframe_ms
    latest_ms = store.latest_timestamp_ms(exchange, symbol, timeframe)
    if since is None:
        if latest_ms is None:
            windows: list[tuple[int | None, int]] = [(None, end_ms)]
        else:
            start_ms = latest_ms + timeframe_ms
            windows = [(start_ms, end_ms)] if start_ms <= end_ms else []
    else:
        start_ms = _timestamp_ms(since)
        missing = store.missing_candle_windows_ms(
            exchange,
            symbol,
            timeframe,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        windows = [(start, end) for start, end in missing]

    fetched_count = 0
    stored_count = 0
    first_timestamp: int | None = None
    last_timestamp: int | None = None
    for window_start, window_end in windows:
        current_since = window_start
        for _ in range(max_batches):
            if current_since is not None and current_since > window_end:
                break
            rows = _fetch_ohlcv(
                exchange_client,
                symbol,
                timeframe,
                since=current_since,
                limit=batch_limit,
            )
            if not rows:
                break
            frame = normalize_candles(rows)
            if current_since is not None:
                frame = frame[frame["timestamp"].apply(_timestamp_ms) >= current_since]
            frame = frame[frame["timestamp"].apply(_timestamp_ms) <= window_end]
            if frame.empty:
                break

            fetched_count += len(frame)
            stored_count += store.upsert_candles(exchange, symbol, timeframe, frame)
            timestamps = [_timestamp_ms(value) for value in frame["timestamp"]]
            batch_first = min(timestamps)
            batch_last = max(timestamps)
            first_timestamp = (
                batch_first
                if first_timestamp is None
                else min(first_timestamp, batch_first)
            )
            last_timestamp = (
                batch_last if last_timestamp is None else max(last_timestamp, batch_last)
            )

            next_since = batch_last + timeframe_ms
            if current_since is None or next_since <= batch_last or len(rows) < batch_limit:
                break
            current_since = next_since

    latest_after = store.latest_timestamp(exchange, symbol, timeframe)
    return HistorySyncResult(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        fetched_count=fetched_count,
        stored_count=stored_count,
        start_at=_datetime_from_ms(first_timestamp) if first_timestamp is not None else None,
        end_at=_datetime_from_ms(last_timestamp) if last_timestamp is not None else None,
        latest_at=latest_after,
    )


def timeframe_to_milliseconds(timeframe: str) -> int:
    return int(timeframe_to_hours(timeframe) * 60 * 60 * 1000)


def timeframe_to_hours(timeframe: str) -> float:
    text = timeframe.strip().lower()
    if len(text) < 2:
        raise HistoryStoreError(f"Unsupported timeframe: {timeframe}")
    amount_text = text[:-1]
    unit = text[-1]
    try:
        amount = float(amount_text)
    except ValueError as exc:
        raise HistoryStoreError(f"Unsupported timeframe: {timeframe}") from exc
    if amount <= 0:
        raise HistoryStoreError(f"Unsupported timeframe: {timeframe}")
    if unit == "m":
        return amount / 60.0
    if unit == "h":
        return amount
    if unit == "d":
        return amount * 24.0
    if unit == "w":
        return amount * 24.0 * 7.0
    raise HistoryStoreError(f"Unsupported timeframe: {timeframe}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync and analyze public OHLCV candles in a local SQLite store"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite path (defaults to BOT_HISTORY_DB_PATH)",
    )
    parser.add_argument(
        "--exchange",
        default=os.getenv("BOT_EXCHANGE", "auto"),
        help="Public CCXT exchange id, e.g. binance-usdm",
    )
    parser.add_argument(
        "--symbol",
        default=os.getenv("BOT_SYMBOL", "BTC/USDT"),
        help="CCXT symbol, e.g. BTC/USDT:USDT",
    )
    parser.add_argument(
        "--timeframes",
        default=",".join(DEFAULT_HISTORY_TIMEFRAMES),
        help="Comma-separated timeframes, e.g. 1h,4h,1d",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Optional UTC start time for bootstrap or gap repair",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="Optional UTC end time, mainly for reproducible offline runs",
    )
    parser.add_argument(
        "--batch-limit",
        type=int,
        default=1000,
        help="Maximum candles per public exchange request",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=20,
        help="Maximum requests per timeframe",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze stored candles instead of fetching new history",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Recent rows per timeframe to load for analysis",
    )
    parser.add_argument(
        "--stop-loss-percent",
        type=float,
        default=Settings.from_env().stop_loss_percent,
        help="Paper stop distance for TP/SL first-hit analysis",
    )
    parser.add_argument(
        "--reward-to-risk",
        type=float,
        default=Settings.from_env().reward_to_risk,
        help="Paper target distance relative to stop",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = args.db_path or _env_path("BOT_HISTORY_DB_PATH")
    if db_path is None:
        print(
            "Set BOT_HISTORY_DB_PATH or pass --db-path to use local history.",
            file=sys.stderr,
        )
        return 2
    timeframes = _parse_timeframes(args.timeframes)
    try:
        exchange_key, symbol = _history_market_keys(args.exchange, args.symbol)
        with HistoryStore(db_path) as store:
            if args.analyze:
                report = analyze_history_store(
                    store,
                    exchange=exchange_key,
                    symbol=symbol,
                    timeframes=timeframes,
                    settings=HistoryAnalysisSettings(
                        stop_loss_percent=args.stop_loss_percent,
                        reward_to_risk=args.reward_to_risk,
                        row_limit=args.limit,
                    ),
                )
                print(format_history_report(report))
                return 0

            exchange_client = _connect_public_exchange(args.exchange, args.symbol)
            try:
                results = sync_history(
                    store,
                    exchange_client,
                    exchange=exchange_key,
                    symbol=symbol,
                    timeframes=timeframes,
                    since=_parse_datetime_arg(args.since),
                    until=_parse_datetime_arg(args.until),
                    batch_limit=args.batch_limit,
                    max_batches=args.max_batches,
                )
            finally:
                close = getattr(exchange_client, "close", None)
                if callable(close):
                    close()
        for result in results:
            print(_sync_result_line(result))
        return 0
    except (ccxt.BaseError, HistoryStoreError, HistorySyncError, ValueError) as exc:
        print(f"History sync failed: {exc}", file=sys.stderr)
        return 1


def _history_market_keys(exchange: str, symbol: str) -> tuple[str, str]:
    if exchange == "auto":
        raise HistorySyncError("Choose an explicit exchange for history sync")
    spec = resolve_exchange_spec(exchange, symbol.upper())
    return spec.ccxt_id, spec.symbol


def _connect_public_exchange(exchange: str, symbol: str) -> Any:
    exchange_key, resolved_symbol = _history_market_keys(exchange, symbol)
    exchange_class = getattr(ccxt, exchange_key, None)
    if exchange_class is None:
        raise HistorySyncError(f"{exchange_key} is not supported by CCXT")
    spec = resolve_exchange_spec(exchange, symbol.upper())
    client = exchange_class(
        {
            "enableRateLimit": True,
            "timeout": int(Settings.from_env().request_timeout_seconds * 1000),
            "options": spec.options,
        }
    )
    client.load_markets()
    markets = getattr(client, "markets", {})
    if resolved_symbol not in markets:
        raise HistorySyncError(f"{resolved_symbol} is not listed on {exchange_key}")
    if not getattr(client, "has", {}).get("fetchOHLCV"):
        raise HistorySyncError(f"{exchange_key} does not support public OHLCV")
    return client


def _parse_timeframes(value: str) -> tuple[str, ...]:
    timeframes = tuple(item.strip() for item in value.split(",") if item.strip())
    if not timeframes:
        raise HistorySyncError("At least one timeframe is required")
    for timeframe in timeframes:
        timeframe_to_milliseconds(timeframe)
    return timeframes


def _parse_datetime_arg(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sync_result_line(result: HistorySyncResult) -> str:
    return (
        f"{result.exchange} {result.symbol} {result.timeframe}: "
        f"stored {result.stored_count} public candles"
        f" (fetched {result.fetched_count}); "
        f"window {_iso(result.start_at)} to {_iso(result.end_at)}; "
        f"latest {_iso(result.latest_at)}"
    )


def _fetch_ohlcv(
    exchange_client: Any,
    symbol: str,
    timeframe: str,
    *,
    since: int | None,
    limit: int,
) -> list[Any]:
    try:
        return exchange_client.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            since=since,
            limit=limit,
        )
    except TypeError:
        if since is None:
            return exchange_client.fetch_ohlcv(symbol, timeframe, limit)
        return exchange_client.fetch_ohlcv(symbol, timeframe, since, limit)


def _future_movement(
    data: pd.DataFrame,
    timestamps: list[int],
    timestamp_index: dict[int, int],
    index: int,
    entry: float,
    timeframe_hours: float,
    horizon_hours: int,
) -> float | None:
    if entry <= 0:
        return None
    offset = horizon_hours / timeframe_hours
    if not offset.is_integer():
        return None
    target_timestamp = timestamps[index] + int(horizon_hours * 60 * 60 * 1000)
    target_index = timestamp_index.get(target_timestamp)
    if target_index is None:
        return None
    close = _finite_or_none(data.iloc[target_index].get("close"))
    if close is None:
        return None
    return (close / entry - 1.0) * 100.0


def _future_path(
    data: pd.DataFrame,
    timestamps: list[int],
    timestamp_index: dict[int, int],
    index: int,
    timeframe_hours: float,
    horizon_hours: int,
) -> pd.DataFrame:
    offset = horizon_hours / timeframe_hours
    if not offset.is_integer():
        return data.iloc[0:0]
    steps = int(offset)
    target_timestamp = timestamps[index] + int(horizon_hours * 60 * 60 * 1000)
    target_index = timestamp_index.get(target_timestamp)
    if target_index is None or target_index - index != steps:
        return data.iloc[0:0]
    return data.iloc[index + 1 : target_index + 1]


def _path_outcome(
    future: pd.DataFrame,
    entry: float,
    *,
    side: str,
    stop_loss_percent: float,
    reward_to_risk: float,
) -> tuple[str, float | None]:
    if future.empty:
        return "PENDING", None
    if entry <= 0 or stop_loss_percent <= 0 or reward_to_risk <= 0:
        return "UNKNOWN", None
    if side == "LONG":
        stop = entry * (1.0 - stop_loss_percent)
        target = entry + ((entry - stop) * reward_to_risk)
        stop_distance = entry - stop
        for row in future.itertuples(index=False):
            if float(row.low) <= stop:
                return "SL", -1.0
            if float(row.high) >= target:
                return "TP", reward_to_risk
        horizon_close = float(future["close"].iloc[-1])
        return "OPEN", _clamp_r((horizon_close - entry) / stop_distance, reward_to_risk)

    stop = entry * (1.0 + stop_loss_percent)
    target = entry - ((stop - entry) * reward_to_risk)
    stop_distance = stop - entry
    for row in future.itertuples(index=False):
        if float(row.high) >= stop:
            return "SL", -1.0
        if float(row.low) <= target:
            return "TP", reward_to_risk
    horizon_close = float(future["close"].iloc[-1])
    return "OPEN", _clamp_r((entry - horizon_close) / stop_distance, reward_to_risk)


def _technical_score(current: pd.Series, previous: pd.Series) -> float | None:
    values = (
        current.get("close"),
        current.get("ema20"),
        current.get("ema50"),
        current.get("rsi14"),
        current.get("macd"),
        current.get("macd_signal"),
        current.get("macd_histogram"),
        previous.get("ema20"),
        previous.get("ema50"),
        previous.get("macd"),
        previous.get("macd_signal"),
        previous.get("macd_histogram"),
    )
    if any(_finite_or_none(value) is None for value in values):
        return None
    _, ema_score = _ema_signal(current, previous)
    _, rsi_score = _rsi_signal(float(current["rsi14"]))
    _, macd_score = _macd_signal(current, previous)
    return _clamp(0.40 * ema_score + 0.25 * rsi_score + 0.35 * macd_score)


def _regime_value(atr_percent: Any, realized_volatility_percent: Any) -> str:
    atr = _finite_or_none(atr_percent)
    realized = _finite_or_none(realized_volatility_percent)
    if atr is None or realized is None:
        return "UNKNOWN"
    return _volatility_regime(atr, realized)


def _structure_value(
    trend_spread_percent: Any,
    bollinger_width_percent: Any,
    range_position_percent: Any,
) -> str:
    trend = _finite_or_none(trend_spread_percent)
    width = _finite_or_none(bollinger_width_percent)
    position = _finite_or_none(range_position_percent)
    if trend is None or width is None or position is None:
        return "UNKNOWN"
    return _structure_regime(
        trend_strength_percent=abs(trend),
        bollinger_width_percent=width,
        range_position_percent=position,
    )


def _history_stats(data: pd.DataFrame) -> HistoryStats:
    if data.empty:
        return HistoryStats(
            sample_count=0,
            movement_4h_percent=None,
            movement_12h_percent=None,
            movement_24h_percent=None,
            long_tp_count=0,
            long_sl_count=0,
            long_open_count=0,
            short_tp_count=0,
            short_sl_count=0,
            short_open_count=0,
            expected_long_r=None,
            expected_short_r=None,
            expected_r=None,
        )
    return HistoryStats(
        sample_count=len(data),
        movement_4h_percent=_mean(data.get("movement_4h_percent")),
        movement_12h_percent=_mean(data.get("movement_12h_percent")),
        movement_24h_percent=_mean(data.get("movement_24h_percent")),
        long_tp_count=_count_value(data, "long_tp_sl_outcome", "TP"),
        long_sl_count=_count_value(data, "long_tp_sl_outcome", "SL"),
        long_open_count=_count_value(data, "long_tp_sl_outcome", "OPEN"),
        short_tp_count=_count_value(data, "short_tp_sl_outcome", "TP"),
        short_sl_count=_count_value(data, "short_tp_sl_outcome", "SL"),
        short_open_count=_count_value(data, "short_tp_sl_outcome", "OPEN"),
        expected_long_r=_mean(data.get("long_r")),
        expected_short_r=_mean(data.get("short_r")),
        expected_r=_mean(data.get("expected_r")),
    )


def _history_stats_line(label: str, stats: HistoryStats) -> str:
    return (
        f"{label}: n={stats.sample_count}"
        f" move4h={_signed_pct(stats.movement_4h_percent)}"
        f" move12h={_signed_pct(stats.movement_12h_percent)}"
        f" move24h={_signed_pct(stats.movement_24h_percent)}"
        f" expectedR={_signed(stats.expected_r)}"
        f" longR={_signed(stats.expected_long_r)}"
        f" shortR={_signed(stats.expected_short_r)}"
        f" long TP/SL/open={stats.long_tp_count}/{stats.long_sl_count}/{stats.long_open_count}"
        f" short TP/SL/open={stats.short_tp_count}/{stats.short_sl_count}/{stats.short_open_count}"
    )


def _movement_bucket(value: float | None) -> str:
    if value is None:
        return "pending"
    if value >= 0.25:
        return "up >= +0.25%"
    if value <= -0.25:
        return "down <= -0.25%"
    return "flat +/-0.25%"


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.65:
        return ">= +0.65"
    if score >= 0.25:
        return "+0.25 to +0.65"
    if score > -0.25:
        return "-0.25 to +0.25"
    if score > -0.65:
        return "-0.65 to -0.25"
    return "<= -0.65"


def _rows_to_frame(rows: Sequence[sqlite3.Row]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    frame = pd.DataFrame([dict(row) for row in rows])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame.loc[:, CANDLE_COLUMNS]


def _timestamp_ms(value: Any) -> int:
    if isinstance(value, pd.Timestamp):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(timezone.utc)
        else:
            timestamp = timestamp.tz_convert(timezone.utc)
        return int(timestamp.timestamp() * 1000)
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return int(timestamp.astimezone(timezone.utc).timestamp() * 1000)
    if isinstance(value, str):
        return _timestamp_ms(pd.to_datetime(value, utc=True))
    number = float(value)
    if not math.isfinite(number):
        raise HistoryStoreError("Invalid candle timestamp")
    return int(number if number > 100_000_000_000 else number * 1000)


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _now_ms() -> int:
    return _timestamp_ms(datetime.now(timezone.utc))


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser()


def _iso(value: datetime | None) -> str:
    return "none" if value is None else value.astimezone(timezone.utc).isoformat()


def _mean(values: Any) -> float | None:
    if values is None:
        return None
    numbers = [_finite_or_none(value) for value in values]
    clean = [value for value in numbers if value is not None]
    return sum(clean) / len(clean) if clean else None


def _count_value(data: pd.DataFrame, column: str, value: str) -> int:
    if column not in data:
        return 0
    return int((data[column] == value).sum())


def _clamp_r(value: float, reward_to_risk: float) -> float:
    return max(-1.0, min(reward_to_risk, value))


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _signed(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}"


def _signed_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
