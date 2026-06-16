from __future__ import annotations

from datetime import datetime, timezone

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from btc_trading_bot.models import Evaluation, Headline, RefreshHealth


def build_dashboard(evaluation: Evaluation) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_header(evaluation), name="header", size=6),
        Layout(name="body"),
        Layout(_signal_panel(evaluation), name="signal", size=10),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(_technical_panel(evaluation), name="technical", ratio=1),
        Layout(_score_panel(evaluation), name="score", size=9),
    )
    layout["right"].split_column(
        Layout(_sentiment_panel(evaluation), name="sentiment", ratio=1),
        Layout(_macro_panel(evaluation), name="macro", ratio=1),
    )
    return layout


def build_static_report(evaluation: Evaluation) -> Group:
    """Build an unconstrained report for --once and redirected output."""
    return Group(
        _header(evaluation),
        _technical_panel(evaluation),
        _sentiment_panel(evaluation),
        _macro_panel(evaluation),
        _score_panel(evaluation),
        _signal_panel(evaluation),
    )


def _header(evaluation: Evaluation) -> Panel:
    market = evaluation.market
    change = market.change_24h
    change_text = Text("N/A", style="dim")
    if change is not None:
        style = "bold green" if change >= 0 else "bold red"
        change_text = Text(f"{change:+.2f}%", style=style)
    line = Text()
    line.append(f"  {market.symbol}  ", style="bold white")
    line.append(f"${market.price:,.2f}", style="bold cyan")
    line.append("   24h: ")
    line.append_text(change_text)
    line.append("\n")
    if market.bid is not None and market.ask is not None:
        line.append(
            f"Bid/Ask: {market.bid:,.2f}/{market.ask:,.2f}   ",
            style="dim",
        )
    stream_style = (
        "bold green"
        if evaluation.stream_status == "LIVE"
        else "bold yellow"
    )
    line.append(f"{market.exchange}   ", style="dim")
    line.append(evaluation.stream_status, style=stream_style)
    line.append(f" via {market.source}", style="dim")
    if evaluation.futures_metrics is not None:
        line.append("\n")
        line.append_text(_futures_metrics_line(evaluation))
    line.append("\n")
    line.append_text(_refresh_health_line(evaluation))
    return Panel(
        Align.center(line),
        title="[bold]BTC TRI-FACTOR SIGNAL ENGINE[/bold]",
        border_style="bright_blue",
        box=box.ROUNDED,
    )


def _technical_panel(evaluation: Evaluation) -> Panel:
    technical = evaluation.technical
    table = Table(box=None, expand=True, show_header=True)
    table.add_column("Indicator", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Status")
    table.add_row(
        "EMA 20 / 50",
        f"{technical.ema20:,.2f} / {technical.ema50:,.2f}",
        _styled_status(technical.ema_status),
    )
    table.add_row(
        "RSI (14)",
        f"{technical.rsi14:.2f}",
        _styled_status(technical.rsi_status),
    )
    table.add_row(
        "MACD",
        f"{technical.macd:,.2f}",
        _styled_status(technical.macd_status),
    )
    table.add_row("Signal line", f"{technical.macd_signal:,.2f}", "")
    table.add_row("Histogram", f"{technical.macd_histogram:+,.2f}", "")
    if technical.base_score is not None:
        table.add_row(
            "4h base score",
            f"{technical.base_score:+.3f}",
            _score_text(technical.base_score),
        )
    if technical.daily_trend is not None:
        table.add_row(
            "Daily trend",
            f"{technical.daily_trend.score:+.3f}",
            _styled_status(technical.daily_trend.status),
        )
    if technical.hourly_entry is not None:
        table.add_row(
            "1h entry timing",
            f"{technical.hourly_entry.score:+.3f}",
            _styled_status(technical.hourly_entry.status),
        )
    live = evaluation.live_technical
    if live is not None:
        table.add_section()
        live_base_score = live.base_score or 0.0
        table.add_row(
            "LIVE 4h preview",
            f"{live_base_score:+.3f}",
            _score_text(live_base_score),
        )
        if live.daily_trend is not None:
            table.add_row(
                "LIVE daily trend",
                f"{live.daily_trend.score:+.3f}",
                _styled_status(live.daily_trend.status),
            )
        if live.hourly_entry is not None:
            table.add_row(
                "LIVE 1h timing",
                f"{live.hourly_entry.score:+.3f}",
                _styled_status(live.hourly_entry.status),
            )
        table.add_row(
            "LIVE MTF preview",
            f"{live.score:+.3f}",
            _score_text(live.score),
        )
    table.add_row(
        "MTF technical score",
        f"{technical.score:+.3f}",
        _score_text(technical.score),
    )
    candle = technical.candle_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"[bold]4h Technical Analysis[/bold] [dim](closed {candle})[/dim]"
    if live is not None:
        title += " [yellow](live rows provisional)[/yellow]"
    return Panel(
        table,
        title=title,
        border_style="cyan",
        box=box.ROUNDED,
    )


def _sentiment_panel(evaluation: Evaluation) -> Panel:
    sentiment = evaluation.sentiment
    heading = Text()
    heading.append(f"Average: {sentiment.score:+.3f}  ", style="bold")
    heading.append(sentiment.label, style=_score_style(sentiment.score))
    items: list[RenderableType] = [heading, Text("")]
    if sentiment.headlines:
        items.extend(_headline_line(item, include_score=True) for item in sentiment.headlines)
    else:
        items.append(Text("No current Bitcoin headlines available.", style="dim"))
    return Panel(
        Group(*items),
        title=(
            "[bold]Bitcoin News Sentiment[/bold]"
            + _updated_suffix(evaluation.news_updated_at)
        ),
        border_style="magenta",
        box=box.ROUNDED,
    )


def _macro_panel(evaluation: Evaluation) -> Panel:
    macro = evaluation.macro
    status_style = (
        "bold red"
        if "RISK" in macro.status
        else "bold yellow"
        if macro.status == "WATCHING MACRO"
        else "bold green"
    )
    heading = Text()
    heading.append(f"{macro.status}  ", style=status_style)
    heading.append(f"Score {macro.score:+.3f}", style="bold")
    if macro.risk_multiplier < 1:
        heading.append(f"  Defensive multiplier {macro.risk_multiplier:.2f}x", style="red")
    items: list[RenderableType] = [heading, Text("")]
    if macro.alerts:
        items.extend(_headline_line(item, include_score=True) for item in macro.alerts)
    else:
        items.append(Text("No high-impact macro headlines detected.", style="dim"))
    return Panel(
        Group(*items),
        title=(
            "[bold]Macro Risk Filter[/bold]"
            + _updated_suffix(evaluation.news_updated_at)
        ),
        border_style="yellow",
        box=box.ROUNDED,
    )


def _score_panel(evaluation: Evaluation) -> Panel:
    signal = evaluation.signal
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Factor")
    table.add_column("Contribution", justify="right")
    table.add_row("Technical × 40%", f"{signal.technical_contribution:+.3f}")
    table.add_row("News sentiment × 30%", f"{signal.sentiment_contribution:+.3f}")
    table.add_row("Macro factor × 30%", f"{signal.macro_contribution:+.3f}")
    table.add_row("Raw confluence", f"{signal.raw_score:+.3f}", style="bold")
    return Panel(
        table,
        title="[bold]Weighted Matrix[/bold]",
        border_style="blue",
        box=box.ROUNDED,
    )


def _signal_panel(evaluation: Evaluation) -> Panel:
    signal = evaluation.signal
    futures = evaluation.futures
    style = (
        "bold white on green"
        if signal.signal == "STRONG BUY"
        else "bold white on red"
        if signal.signal == "STRONG SELL"
        else "bold black on yellow"
    )
    title = Text(f"  {signal.signal}  ", style=style, justify="center")
    detail = Text(
        f"Closed-candle score: {signal.score:+.3f}   "
        f"Buy > +0.650 | Sell < -0.650   "
        f"Next multi-timeframe evaluation: {_countdown(evaluation.next_analysis_at)}",
        justify="center",
        style="bold",
    )
    content: list[RenderableType] = [title, detail]
    if futures is not None:
        futures_style = (
            "bold green"
            if futures.side == "LONG"
            else "bold red"
            if futures.side == "SHORT"
            else "bold yellow"
        )
        recommendation = Text(justify="center")
        recommendation.append(
            f"FUTURES: {futures.action}",
            style=futures_style,
        )
        if futures.entry_price is not None:
            recommendation.append(
                f" | Ref entry {futures.entry_price:,.2f}"
                f" | Stop {futures.stop_loss:,.2f}"
                f" | Target {futures.take_profit:,.2f}"
                f" | Size {futures.quantity_btc:.6f} BTC"
                f" | Max loss ${futures.max_loss:,.2f}",
                style="bold",
            )
        else:
            recommendation.append(f" | {futures.reason}", style="dim")
        content.append(recommendation)
        content.append(
            Text(
                "Paper guidance only. Closed candles; no order is placed.",
                style="dim",
                justify="center",
            )
        )
    if evaluation.price_range is not None:
        price_range = evaluation.price_range
        range_line = Text(justify="center")
        range_line.append(
            f"{price_range.horizon_hours}h historical range: ",
            style="bold cyan",
        )
        range_line.append(
            f"Low ${price_range.expected_low:,.2f}"
            f" ({price_range.downside_percent:+.2f}%)"
            f" | High ${price_range.expected_high:,.2f}"
            f" ({price_range.upside_percent:+.2f}%)",
            style="bold",
        )
        range_line.append(
            f" | Confidence {price_range.confidence}",
            style="dim",
        )
        content.append(range_line)
    if evaluation.errors:
        content.append(
            Text(
                "Degraded data: " + " | ".join(evaluation.errors),
                style="yellow",
                justify="center",
                overflow="ellipsis",
            )
        )
    return Panel(
        Group(*content),
        title="[bold]MARKET SIGNAL[/bold]",
        border_style=_score_style(signal.score),
        box=box.DOUBLE,
    )


def _headline_line(headline: Headline, include_score: bool) -> Text:
    age = _format_age(headline.published_at)
    line = Text("• ")
    line.append(headline.title, style="white")
    line.append(f"  [{headline.source}, {age}]", style="dim")
    if include_score:
        line.append(
            f" {headline.sentiment:+.2f}",
            style=_score_style(headline.sentiment),
        )
    return line


def _styled_status(value: str) -> Text:
    lower = value.lower()
    if "bullish" in lower or "oversold" in lower:
        return Text(value, style="green")
    if "bearish" in lower or "overbought" in lower:
        return Text(value, style="red")
    return Text(value, style="yellow")


def _score_text(score: float) -> Text:
    label = "Bullish" if score > 0.1 else "Bearish" if score < -0.1 else "Neutral"
    return Text(label, style=_score_style(score))


def _score_style(score: float) -> str:
    if score > 0.1:
        return "green"
    if score < -0.1:
        return "red"
    return "yellow"


def _format_age(value: datetime) -> str:
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m ago"
    return f"{seconds // 3600}h ago"


def _countdown(target: datetime) -> str:
    seconds = max(0, int((target - datetime.now(timezone.utc)).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m"


def _updated_suffix(value: datetime | None) -> str:
    if value is None:
        return ""
    return f" [dim](updated {_format_age(value)})[/dim]"


def _futures_metrics_line(evaluation: Evaluation) -> Text:
    metrics = evaluation.futures_metrics
    line = Text("USD-M  ", style="bold cyan")
    if metrics is None:
        line.append("metrics unavailable", style="dim")
        return line

    if metrics.mark_price is not None:
        line.append(f"Mark {metrics.mark_price:,.2f}")
    if metrics.index_price is not None:
        line.append(f"  Index {metrics.index_price:,.2f}")
    if metrics.mark_price is not None and metrics.index_price not in (None, 0):
        basis = (
            (metrics.mark_price - metrics.index_price)
            / metrics.index_price
            * 100
        )
        line.append(f"  Basis {basis:+.3f}%", style=_score_style(basis))
    if metrics.funding_rate is not None:
        funding_percent = metrics.funding_rate * 100
        line.append(
            f"  Funding {funding_percent:+.4f}%",
            style=_score_style(-funding_percent),
        )
        if metrics.next_funding_at is not None:
            line.append(f" in {_countdown(metrics.next_funding_at)}", style="dim")
    if metrics.open_interest_amount is not None:
        line.append(f"  OI {metrics.open_interest_amount:,.0f} BTC")
    if metrics.open_interest_value is not None:
        line.append(f" ({_compact_usd(metrics.open_interest_value)})", style="dim")
    if metrics.long_short_ratio is not None:
        line.append(f"  L/S {metrics.long_short_ratio:.2f}")
    return line


def _refresh_health_line(evaluation: Evaluation) -> Text:
    line = Text("Health  ", style="bold")
    for index, (label, health) in enumerate(
        (
            ("Market", evaluation.market_health),
            ("Futures", evaluation.futures_health),
            ("News", evaluation.news_health),
        )
    ):
        if index:
            line.append("  |  ", style="dim")
        line.append(f"{label} ")
        line.append(health.status, style=_health_style(health.status))
        if health.last_success_at is not None:
            line.append(f" {_health_age(health.last_success_at)}", style="dim")
        if health.next_refresh_at is not None:
            line.append(f" next {_countdown(health.next_refresh_at)}", style="dim")
    return line


def _health_style(status: str) -> str:
    if status in {"OK", "LIVE", "REST"}:
        return "bold green"
    if status in {"FAILED", "RECONNECTING"}:
        return "bold red"
    if status in {"DEGRADED", "REFRESHING"}:
        return "bold yellow"
    return "dim"


def _health_age(value: datetime) -> str:
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _compact_usd(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"
