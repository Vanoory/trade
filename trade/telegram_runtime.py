from __future__ import annotations

import time
from dataclasses import replace
from threading import Event, Thread

from backtest_engine import run_period_backtests
from config import AppConfig
from market_data import OHLCVRequest, fetch_ohlcv
from paper_profile import PaperProfile
from realtime_bot import (
    SignalRuntimeState,
    collect_current_signals,
    run_signal_scan_cycle,
    snapshot_open_signals,
)
from reporting import build_summary_rows, build_summary_stats, format_summary_report, resolve_period_result
from telegram_notifier import TelegramNotifier


def parse_risk_value(raw: str) -> float:
    cleaned = raw.strip().replace("%", "")
    value = float(cleaned)
    if value > 1:
        value /= 100.0
    if value <= 0 or value > 1:
        raise ValueError("Risk must be between 0 and 100 percent.")
    return value


def normalize_symbol(raw: str, available_symbols: list[str]) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().upper()
    if cleaned in available_symbols:
        return cleaned
    if "/" not in cleaned:
        if cleaned.endswith("USDT"):
            candidate = f"{cleaned[:-4]}/USDT"
        else:
            candidate = f"{cleaned}/USDT"
        if candidate in available_symbols:
            return candidate
    for symbol in available_symbols:
        if symbol.split("/")[0] == cleaned:
            return symbol
    return None


def format_symbol_report(config: AppConfig, symbol: str, days: int, risk_per_trade: float | None) -> str:
    profile = next((item for item in config.active_profiles() if item.symbol == symbol), None)
    if not profile:
        raise ValueError(f"Symbol {symbol} is not configured.")

    strategy = replace(profile.strategy, risk_per_trade=risk_per_trade) if risk_per_trade is not None else profile.strategy
    data = fetch_ohlcv(
        OHLCVRequest(
            exchange_id=config.exchange_id,
            symbol=profile.symbol,
            timeframe=profile.timeframe,
            limit=profile.lookback_bars,
        )
    )
    period_result = resolve_period_result(
        run_period_backtests(data, strategy, profile.symbol, config.starting_balance, [days]),
        days,
    )

    direction = "long+short"
    if strategy.allow_long and not strategy.allow_short:
        direction = "long-only"
    if strategy.allow_short and not strategy.allow_long:
        direction = "short-only"

    lines = [
        f"{profile.symbol} | {profile.timeframe} | {strategy.strategy_name}",
        f"Period: {days}d",
        f"PnL: {period_result['return_pct']:.2f}% (${period_result['net_profit']:.2f} on ${config.starting_balance:.0f})",
        f"Trades: {period_result['trades']} | Winrate: {period_result['win_rate']:.2f}%",
        f"Avg RR: {period_result['avg_rr']:.3f} | PF: {period_result['profit_factor']:.3f}",
        f"Max DD: {period_result['max_drawdown_pct']:.2f}% | Sharpe: {period_result['sharpe']:.3f}",
        f"Mode: {direction} | Risk: {strategy.risk_per_trade * 100:.2f}%",
        (
            f"EMA {strategy.fast_ema}/{strategy.slow_ema}, ADX {strategy.adx_min}, "
            f"RSI L/S {strategy.rsi_long_min}/{strategy.rsi_short_max}"
        ),
        (
            f"ATR stop/target/trail: {strategy.stop_atr}/{strategy.target_atr}/{strategy.trail_atr}"
        ),
    ]
    return "\n".join(lines)


def format_signal_snapshot(config: AppConfig) -> str:
    signals = collect_current_signals(config)
    if not signals:
        return "Сейчас активных сигналов нет."

    lines = []
    for item in signals:
        signal = item["signal"]
        stats = item["stats"]
        lines.append(
            (
                f"{item['symbol']} {signal['side']} | {item['timeframe']}\n"
                f"Entry {signal['entry']} | Stop {signal['stop']} | Target {signal['target']} | RR {signal['rr']}\n"
                f"Size {stats['size']} | Risk ${stats['risk_amount']} | Fees ${stats['fee_estimate']}"
            )
        )
    return "\n\n".join(lines)


def format_open_positions(state: SignalRuntimeState) -> str:
    tracked = snapshot_open_signals(state)
    if not tracked:
        return "Сейчас бот не ведёт открытых сигналов."

    lines = []
    for symbol, signal in tracked.items():
        lines.append(
            (
                f"{symbol} {signal['side']} | Entry {signal['entry']} | "
                f"Stop {signal['stop']} | Target {signal['target']} | "
                f"Size {signal.get('size', 0)} | Max loss ${signal.get('expected_loss', 0)}"
            )
        )
    return "\n".join(lines)


class TelegramCommandRuntime:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
        self.state = SignalRuntimeState()
        self.paper_profile = PaperProfile(
            storage_path=config.paper_profile_path,
            initial_balance=config.paper_start_balance,
            risk_per_trade=config.paper_risk_per_trade,
            leverage=config.paper_leverage,
        )
        self.paper_profile.restore_runtime_state(self.state)
        self.stop_event = Event()
        self.update_offset: int | None = None
        self.started_at = time.time()

    def run(self) -> None:
        if not self.notifier.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

        self._prime_offset()
        scanner_thread = Thread(target=self._scanner_loop, name="telegram-scan", daemon=True)
        scanner_thread.start()

        if self.notifier.chat_id:
            self.notifier.send(
                "Telegram runtime started.\n"
                "Commands: /help, /summary, /coin XRP, /profile, /trades, /positions, /status"
            )

        try:
            self._poll_commands()
        finally:
            self.stop_event.set()
            scanner_thread.join(timeout=2)

    def _scanner_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                run_signal_scan_cycle(self.config, self.notifier, self.state, paper_profile=self.paper_profile)
            except Exception as exc:
                self.notifier.send(f"Realtime scanner error: {type(exc).__name__}: {exc}")
            self.stop_event.wait(self.config.realtime_scan_interval_seconds)

    def _prime_offset(self) -> None:
        updates = self.notifier.get_updates(timeout=0)
        if updates:
            self.update_offset = int(updates[-1]["update_id"]) + 1

    def _poll_commands(self) -> None:
        while not self.stop_event.is_set():
            updates = self.notifier.get_updates(
                offset=self.update_offset,
                timeout=self.config.telegram_poll_timeout_seconds,
            )
            for update in updates:
                self.update_offset = int(update["update_id"]) + 1
                self._handle_update(update)

    def _accept_chat(self, chat_id: str) -> bool:
        if self.notifier.chat_id:
            return str(self.notifier.chat_id) == str(chat_id)
        self.notifier.chat_id = str(chat_id)
        return True

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        if not text:
            return

        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        if not chat_id or not self._accept_chat(chat_id):
            return

        parts = text.split()
        command = parts[0].split("@")[0].lower()
        args = parts[1:]

        try:
            if command in {"/start", "/help"}:
                self.notifier.send(self._help_text(), chat_id=chat_id)
                return
            if command == "/summary":
                self._send_summary(chat_id=chat_id, days=30, risk_per_trade=None)
                return
            if command == "/summary4":
                self._send_summary(chat_id=chat_id, days=30, risk_per_trade=0.04)
                return
            if command == "/backtest":
                days = int(args[0]) if args else 30
                risk_per_trade = parse_risk_value(args[1]) if len(args) >= 2 else None
                self._send_summary(chat_id=chat_id, days=days, risk_per_trade=risk_per_trade)
                return
            if command == "/coin":
                if not args:
                    self.notifier.send("Usage: /coin XRP 30 4", chat_id=chat_id)
                    return
                symbol = normalize_symbol(args[0], [profile.symbol for profile in self.config.active_profiles()])
                if not symbol:
                    self.notifier.send("Symbol is not in the active basket.", chat_id=chat_id)
                    return
                days = int(args[1]) if len(args) >= 2 else 30
                risk_per_trade = parse_risk_value(args[2]) if len(args) >= 3 else None
                self.notifier.send("Running symbol backtest. This can take 10-15 seconds.", chat_id=chat_id)
                self.notifier.send_preformatted(
                    format_symbol_report(self.config, symbol, days, risk_per_trade),
                    chat_id=chat_id,
                )
                return
            if command == "/profile":
                self.notifier.send_preformatted(self.paper_profile.format_profile_report(), chat_id=chat_id)
                return
            if command == "/trades":
                limit = int(args[0]) if args else 10
                self.notifier.send_preformatted(self.paper_profile.format_recent_trades(limit=limit), chat_id=chat_id)
                return
            if command == "/resetprofile":
                self.paper_profile.reset()
                self.paper_profile.restore_runtime_state(self.state)
                self.notifier.send("Paper profile reset to defaults: $100, 5% risk, 40x leverage.", chat_id=chat_id)
                return
            if command == "/scan":
                self.notifier.send("Checking current signals.", chat_id=chat_id)
                self.notifier.send_preformatted(format_signal_snapshot(self.config), chat_id=chat_id)
                return
            if command == "/positions":
                self.notifier.send_preformatted(format_open_positions(self.state), chat_id=chat_id)
                return
            if command == "/status":
                uptime_minutes = int((time.time() - self.started_at) // 60)
                tracked_count = len(snapshot_open_signals(self.state))
                profile_stats = self.paper_profile.summary_stats()
                self.notifier.send(
                    (
                        f"Runtime active\n"
                        f"Profiles: {len(self.config.active_profiles())}\n"
                        f"Scan interval: {self.config.realtime_scan_interval_seconds}s\n"
                        f"Tracked signals: {tracked_count}\n"
                        f"Paper balance: ${profile_stats['balance']:.2f}\n"
                        f"Paper trades: {profile_stats['closed_trades']} | Winrate: {profile_stats['win_rate']:.2f}%\n"
                        f"Uptime: {uptime_minutes} min"
                    ),
                    chat_id=chat_id,
                )
                return
            self.notifier.send("Unknown command. Use /help", chat_id=chat_id)
        except Exception as exc:
            self.notifier.send(f"Command error {command}: {type(exc).__name__}: {exc}", chat_id=chat_id)

    def _send_summary(self, chat_id: str, days: int, risk_per_trade: float | None) -> None:
        self.notifier.send("Running basket backtest. This can take about a minute.", chat_id=chat_id)
        rows = build_summary_rows(self.config, days=days, risk_per_trade=risk_per_trade)
        stats = build_summary_stats(rows, self.config.starting_balance)
        report = format_summary_report(rows, stats, days=days, risk_per_trade=risk_per_trade)
        self.notifier.send_preformatted(report, chat_id=chat_id)

    def _help_text(self) -> str:
        return (
            "Commands:\n"
            "/summary - basket backtest for 30 days\n"
            "/summary4 - basket backtest for 30 days with 4% risk\n"
            "/backtest 60 4 - basket backtest for 60 days with 4% risk\n"
            "/coin XRP - one symbol backtest for 30 days\n"
            "/coin XRP 30 4 - one symbol backtest with 4% risk\n"
            "/profile - paper profile stats\n"
            "/trades 10 - latest closed paper trades\n"
            "/resetprofile - reset paper profile to defaults\n"
            "/scan - check signals right now\n"
            "/positions - currently tracked open signals\n"
            "/status - runtime status\n"
            "/help - command list"
        )


def run_telegram_bot(config: AppConfig) -> None:
    TelegramCommandRuntime(config).run()
