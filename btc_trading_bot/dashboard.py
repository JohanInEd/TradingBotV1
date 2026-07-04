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
        Layout(_market_context_panel(evaluation), name="market_context", size=9),
        Layout(_score_panel(evaluation), name="score", size=9),
    )
    layout["right"].split_column(
        Layout(_sentiment_panel(evaluation), name="sentiment", ratio=1),
        Layout(_macro_panel(evaluation), name="macro", ratio=1),
        Layout(_shakeout_panel(evaluation), name="shakeout", size=12),
    )
    return layout


def build_static_report(evaluation: Evaluation) -> Group:
    """Build an unconstrained report for --once and redirected output."""
    return Group(
        _header(evaluation),
        _technical_panel(evaluation),
        _market_context_panel(evaluation),
        _sentiment_panel(evaluation),
        _macro_panel(evaluation),
        _shakeout_panel(evaluation),
        _scanner_panel(evaluation),
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


def _market_context_panel(evaluation: Evaluation) -> Panel:
    context = evaluation.market_context
    if context is None:
        return Panel(
            Text("Market context is waiting for completed candle history.", style="dim"),
            title="[bold]Market Context[/bold]",
            border_style="white",
            box=box.ROUNDED,
        )

    volatility_style = (
        "bold red"
        if context.volatility_regime == "HIGH VOLATILITY"
        else "bold yellow"
        if context.volatility_regime == "ELEVATED VOLATILITY"
        else "cyan"
        if context.volatility_regime == "COMPRESSED VOLATILITY"
        else "green"
    )
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Volatility", context.volatility_regime, style=volatility_style)
    table.add_row("Structure", context.structure_regime)
    table.add_row("ATR / realized", f"{context.atr_percent:.2f}% / {context.realized_volatility_percent:.2f}%")
    table.add_row("Bollinger width", f"{context.bollinger_width_percent:.2f}%")
    table.add_row("Range position", f"{context.range_position_percent:.0f}%")
    table.add_row("Trend spread", f"{context.trend_strength_percent:.2f}%")
    table.add_row("Reason", context.reason)
    return Panel(
        table,
        title="[bold]Market Context[/bold]",
        border_style=volatility_style,
        box=box.ROUNDED,
    )


def _sentiment_panel(evaluation: Evaluation) -> Panel:
    sentiment = evaluation.sentiment
    heading = Text()
    heading.append(f"Average: {sentiment.score:+.3f}  ", style="bold")
    heading.append(sentiment.label, style=_score_style(sentiment.score))
    items: list[RenderableType] = [heading, Text("")]
    if sentiment.sources:
        for source in sentiment.sources:
            line = Text("- ")
            line.append(source.name, style="bold")
            line.append(f": {source.score:+.3f} ")
            line.append(source.label, style=_score_style(source.score))
            line.append(f"  {source.detail}", style="dim")
            items.append(line)
        items.append(Text(""))
    if sentiment.events:
        items.append(Text("Event buckets", style="bold cyan"))
        for event in sentiment.events[:5]:
            line = Text("- ")
            line.append(event.event_type, style="bold")
            line.append(f": {event.count} ")
            line.append(event.direction, style=_score_style(event.average_sentiment))
            line.append(
                f" {event.average_sentiment:+.2f}",
                style=_score_style(event.average_sentiment),
            )
            if event.representative_title:
                line.append(f"  {event.representative_title}", style="dim")
            items.append(line)
        items.append(Text(""))
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
    if macro.calendar is not None:
        calendar = macro.calendar
        items.append(
            Text(
                f"Calendar: {calendar.status}  {calendar.reason}",
                style="bold cyan",
            )
        )
        for event in (*calendar.active_events, *calendar.upcoming_events[:3]):
            line = Text("- ")
            line.append(event.name, style="bold")
            line.append(
                f"  {event.scheduled_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                style="dim",
            )
            line.append(f"  {event.impact}")
            items.append(line)
        items.append(Text(""))
    if macro.events:
        items.append(Text("Macro event buckets", style="bold cyan"))
        for event in macro.events[:4]:
            line = Text("- ")
            line.append(event.event_type, style="bold")
            line.append(f": {event.count} ")
            line.append(event.direction, style=_score_style(event.average_sentiment))
            line.append(
                f" {event.average_sentiment:+.2f}",
                style=_score_style(event.average_sentiment),
            )
            items.append(line)
        items.append(Text(""))
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


def _shakeout_panel(evaluation: Evaluation) -> Panel:
    shakeout = evaluation.shakeout
    if shakeout is None:
        content = Text(
            "Shakeout risk is available in Binance USD-M mode after public "
            "depth, trade, and liquidation streams begin publishing.",
            style="dim",
        )
        return Panel(
            content,
            title="[bold]Shakeout Risk[/bold]",
            border_style="white",
            box=box.ROUNDED,
        )

    style = (
        "bold red"
        if shakeout.status == "HIGH"
        else "bold yellow"
        if shakeout.status == "MEDIUM"
        else "cyan"
        if shakeout.status == "LOW"
        else "green"
    )
    table = Table(box=None, expand=True, show_header=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Status", shakeout.status, style=style)
    table.add_row("Direction", shakeout.direction)
    table.add_row("Score", f"{shakeout.score:.2f}")
    table.add_row("Signal context", _shakeout_signal_context(evaluation))
    if shakeout.order_book_imbalance is not None:
        table.add_row("Book imbalance", f"{shakeout.order_book_imbalance:+.2f}")
    if shakeout.bid_depth_usd is not None and shakeout.ask_depth_usd is not None:
        table.add_row(
            "Depth bid/ask",
            f"{_compact_usd(shakeout.bid_depth_usd)} / {_compact_usd(shakeout.ask_depth_usd)}",
        )
    table.add_row(
        "Taker buy/sell",
        f"{_compact_usd(shakeout.taker_buy_usd)} / {_compact_usd(shakeout.taker_sell_usd)}",
    )
    table.add_row(
        "Liq buy/sell",
        f"{_compact_usd(shakeout.liquidation_buy_usd)} / {_compact_usd(shakeout.liquidation_sell_usd)}",
    )
    if shakeout.open_interest_change_percent is not None:
        table.add_row("OI change", f"{shakeout.open_interest_change_percent:+.2f}%")
    stress = _shakeout_stress_line(shakeout)
    if stress:
        table.add_row("Vs baseline", stress)
    if shakeout.stream_health:
        table.add_row("Streams", _stream_health_line(shakeout.stream_health))
    table.add_row("Reason", shakeout.reason)
    return Panel(
        table,
        title="[bold]Shakeout Risk[/bold]",
        border_style=style,
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
    paper_setup = evaluation.paper_setup
    if paper_setup is not None:
        futures_style = "bold green" if paper_setup.side == "LONG" else "bold red"
        recommendation = Text(justify="center")
        recommendation.append(
            f"paper setup: {paper_setup.action}",
            style=futures_style,
        )
        recommendation.append(
            f" | Entry {paper_setup.entry_price:,.2f}"
            f" | Stop {paper_setup.stop_loss:,.2f}"
            f" | TP {paper_setup.take_profit:,.2f}"
            f" | R/R {paper_setup.reward_to_risk:.2f}"
            f" | Pos {paper_setup.quantity_btc:.6f} BTC"
            f" | Max loss ${paper_setup.max_loss:,.2f}",
            style="bold",
        )
        content.append(recommendation)
        content.append(
            Text(
                "paper setup only; no order placed; not financial advice",
                style="dim",
                justify="center",
            )
        )
    elif futures is not None:
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
                "No paper setup for this closed candle; no order placed; not financial advice.",
                style="dim",
                justify="center",
            )
        )
    if evaluation.probability_forecast is not None:
        probability = evaluation.probability_forecast
        odds_line = Text(justify="center")
        odds_line.append(
            f"{probability.horizon_hours}h backtest odds: ",
            style="bold cyan",
        )
        odds_line.append(
            f"Up {_probability_pct(probability.up_probability)}"
            f" | Down {_probability_pct(probability.down_probability)}"
            f" | Long TP/SL "
            f"{_probability_pct(probability.long_tp_before_sl_probability)}/"
            f"{_probability_pct(probability.long_sl_before_tp_probability)}"
            f" | Short TP/SL "
            f"{_probability_pct(probability.short_tp_before_sl_probability)}/"
            f"{_probability_pct(probability.short_sl_before_tp_probability)}",
            style="bold",
        )
        odds_line.append(
            f" | Exp R L {probability.expected_long_r:+.2f}"
            f" / S {probability.expected_short_r:+.2f}"
            f" | {probability.sample_size}/{probability.candidate_count}"
            f" samples {probability.confidence}",
            style="dim",
        )
        content.append(odds_line)
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
    if evaluation.scalping is not None:
        scalp = evaluation.scalping
        scalp_line = Text(justify="center")
        scalp_line.append("5m Scalp: ", style="bold cyan")
        setup = scalp.paper_setup
        if setup is not None:
            scalp_style = "bold green" if setup.side == "LONG" else "bold red"
            scalp_line.append(setup.action, style=scalp_style)
            scalp_line.append(
                f" | Entry {setup.entry_price:,.2f}"
                f" | Stop {setup.stop_loss:,.2f}"
                f" | TP {setup.take_profit:,.2f}"
                f" | R/R {setup.reward_to_risk:.2f}",
                style="bold",
            )
        else:
            scalp_line.append(scalp.futures.action, style="dim")
            if scalp.futures.reason:
                scalp_line.append(f" | {scalp.futures.reason}", style="dim")
        content.append(scalp_line)
    if evaluation.scanner is not None and evaluation.scanner.candidates:
        top = [
            candidate
            for candidate in evaluation.scanner.candidates
            if candidate.action in {"GO LONG", "GO SHORT"}
        ][:3]
        if top:
            scanner_line = Text(justify="center")
            scanner_line.append("Scanner: ", style="bold cyan")
            scanner_line.append(
                " | ".join(
                    f"{item.symbol} {item.action} {item.confidence:.2f}"
                    for item in top
                ),
                style="bold",
            )
            content.append(scanner_line)
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


def _scanner_panel(evaluation: Evaluation) -> Panel:
    scanner = evaluation.scanner
    if scanner is None:
        return Panel(
            Text("Set BOT_SYMBOLS to scan a comma-separated futures universe.", style="dim"),
            title="[bold]Long / Short Scanner[/bold]",
            border_style="white",
            box=box.ROUNDED,
        )

    table = Table(box=None, expand=True, show_header=True)
    table.add_column("Symbol", style="bold")
    table.add_column("Action")
    table.add_column("Conf", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("24h", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Context")
    for candidate in scanner.candidates[:12]:
        action_style = (
            "green"
            if candidate.action == "GO LONG"
            else "red"
            if candidate.action == "GO SHORT"
            else "yellow"
            if candidate.action == "STAY FLAT"
            else "dim"
        )
        price = "-" if candidate.price is None else f"{candidate.price:,.4f}"
        change = "-" if candidate.change_24h is None else f"{candidate.change_24h:+.2f}%"
        context = candidate.error or candidate.reason
        table.add_row(
            candidate.symbol,
            Text(candidate.action, style=action_style),
            f"{candidate.confidence:.2f}",
            price,
            change,
            f"{candidate.score:+.3f}",
            context,
        )
    title = (
        f"[bold]Long / Short Scanner[/bold] "
        f"[dim]({len(scanner.candidates)}/{len(scanner.symbols)} symbols)[/dim]"
    )
    return Panel(table, title=title, border_style="bright_blue", box=box.ROUNDED)


def _shakeout_signal_context(evaluation: Evaluation) -> str:
    shakeout = evaluation.shakeout
    if shakeout is None or shakeout.status == "CALM":
        return "Context only; no shakeout pressure against the main signal."
    signal = evaluation.signal.signal
    if "UPSIDE" in shakeout.direction:
        risk_side = "BUY"
    elif "DOWNSIDE" in shakeout.direction:
        risk_side = "SELL"
    else:
        return f"Context only; two-sided risk while signal is {signal}."
    if signal == "STRONG BUY" and risk_side == "BUY":
        return "Context only; agrees with the bullish main signal."
    if signal == "STRONG SELL" and risk_side == "SELL":
        return "Context only; agrees with the bearish main signal."
    if signal in {"STRONG BUY", "STRONG SELL"}:
        return f"Context only; conflicts with the {signal} main signal."
    return "Context only; main signal is neutral, so this is not a trigger."


def _shakeout_stress_line(shakeout) -> str:
    parts: list[str] = []
    for label, value in (
        ("Depth", shakeout.depth_stress_ratio),
        ("Flow", shakeout.taker_flow_stress_ratio),
        ("Large", shakeout.large_trade_stress_ratio),
        ("Liq", shakeout.liquidation_stress_ratio),
    ):
        if value is not None:
            parts.append(f"{label} {value:.1f}x")
    return "  ".join(parts)


def _stream_health_line(streams) -> str:
    parts: list[str] = []
    for stream in streams:
        age = "-" if stream.last_event_age_seconds is None else f"{stream.last_event_age_seconds:.0f}s"
        parts.append(f"{stream.name}:{stream.status} {age}/{stream.event_count}")
    return "  ".join(parts)


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
    if metrics.top_trader_long_short_ratio is not None:
        line.append(f"  Top acct {metrics.top_trader_long_short_ratio:.2f}")
    if metrics.taker_buy_sell_ratio is not None:
        line.append(f"  Taker {metrics.taker_buy_sell_ratio:.2f}")
    if metrics.crowding_label is not None and metrics.crowding_score is not None:
        line.append(
            f"  {metrics.crowding_label} {metrics.crowding_score:+.2f}",
            style=_score_style(metrics.crowding_score),
        )
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


def _probability_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _compact_usd(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"
