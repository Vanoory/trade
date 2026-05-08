from __future__ import annotations

import time
from dataclasses import dataclass, field
from dataclasses import asdict
from threading import Lock
from typing import TYPE_CHECKING

import pandas as pd

from backtest_engine import run_backtest
from config import AppConfig, StrategyConfig
from market_data import fetch_ohlcv, OHLCVRequest
from strategy import calculate_position_size
from telegram_notifier import TelegramNotifier

if TYPE_CHECKING:
    from paper_profile import PaperProfile


@dataclass(slots=True)
class SignalRuntimeState:
    sent_keys: set[str] = field(default_factory=set)
    open_signals: dict[str, dict] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock, repr=False)


def latest_signal(data: pd.DataFrame, strategy: StrategyConfig) -> dict | None:
    minimum_bars = max(strategy.slow_ema, strategy.volume_window, strategy.atr_period) + 5
    if strategy.strategy_name == "momentum_breakout":
        minimum_bars = max(minimum_bars, strategy.breakout_window + 2)
    if len(data) < minimum_bars:
        return None

    enriched = data.copy()
    enriched["ema_fast"] = enriched["close"].ewm(span=strategy.fast_ema, adjust=False).mean()
    enriched["ema_slow"] = enriched["close"].ewm(span=strategy.slow_ema, adjust=False).mean()
    delta = enriched["close"].diff()
    gain = delta.clip(lower=0).rolling(strategy.rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(strategy.rsi_period).mean()
    rs = gain / loss.replace(0, pd.NA)
    enriched["rsi"] = 100 - (100 / (1 + rs))
    tr = pd.concat(
        [
            enriched["high"] - enriched["low"],
            (enriched["high"] - enriched["close"].shift()).abs(),
            (enriched["low"] - enriched["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    enriched["atr"] = tr.rolling(strategy.atr_period).mean()
    enriched["volume_ma"] = enriched["volume"].rolling(strategy.volume_window).mean()

    plus_dm = (enriched["high"].diff()).clip(lower=0)
    minus_dm = (-enriched["low"].diff()).clip(lower=0)
    tr_sum = tr.rolling(strategy.adx_period).sum()
    plus_di = 100 * (plus_dm.rolling(strategy.adx_period).sum() / tr_sum.replace(0, pd.NA))
    minus_di = 100 * (minus_dm.rolling(strategy.adx_period).sum() / tr_sum.replace(0, pd.NA))
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
    enriched["adx"] = dx.rolling(strategy.adx_period).mean()

    row = enriched.iloc[-1]
    price = float(row["close"])
    atr = float(row["atr"])
    if pd.isna(atr) or atr <= 0:
        return None

    if strategy.strategy_name == "momentum_breakout":
        breakout_high = float(enriched["high"].shift(1).rolling(strategy.breakout_window).max().iloc[-1])
        breakout_low = float(enriched["low"].shift(1).rolling(strategy.breakout_window).min().iloc[-1])
        bullish = (
            strategy.allow_long
            and row["ema_fast"] > row["ema_slow"]
            and price > breakout_high
            and row["rsi"] >= strategy.rsi_long_min
            and row["adx"] >= strategy.adx_min
            and row["volume"] >= row["volume_ma"] * strategy.volume_factor
        )
        bearish = (
            strategy.allow_short
            and row["ema_fast"] < row["ema_slow"]
            and price < breakout_low
            and row["rsi"] <= strategy.rsi_short_max
            and row["adx"] >= strategy.adx_min
            and row["volume"] >= row["volume_ma"] * strategy.volume_factor
        )
    else:
        bullish = (
            strategy.allow_long
            and row["ema_fast"] > row["ema_slow"]
            and price > row["ema_fast"]
            and row["rsi"] >= strategy.rsi_long_min
            and row["adx"] >= strategy.adx_min
            and row["volume"] >= row["volume_ma"] * strategy.volume_factor
        )
        bearish = (
            strategy.allow_short
            and row["ema_fast"] < row["ema_slow"]
            and price < row["ema_fast"]
            and row["rsi"] <= strategy.rsi_short_max
            and row["adx"] >= strategy.adx_min
            and row["volume"] >= row["volume_ma"] * strategy.volume_factor
        )

    if bullish:
        return {
            "side": "LONG",
            "entry": round(price, 4),
            "stop": round(price - atr * strategy.stop_atr, 4),
            "target": round(price + atr * strategy.target_atr, 4),
            "rr": round(strategy.target_atr / strategy.stop_atr, 2),
        }
    if bearish:
        return {
            "side": "SHORT",
            "entry": round(price, 4),
            "stop": round(price + atr * strategy.stop_atr, 4),
            "target": round(price - atr * strategy.target_atr, 4),
            "rr": round(strategy.target_atr / strategy.stop_atr, 2),
        }
    return None


def simulate_open_signal(signal: dict, strategy: StrategyConfig, balance: float) -> dict:
    stop_distance = abs(signal["entry"] - signal["stop"])
    if stop_distance <= 0:
        return {"size": 0.0, "risk_amount": 0.0}
    risk_amount = balance * strategy.risk_per_trade
    size = calculate_position_size(
        equity=balance,
        price=signal["entry"],
        stop_distance=stop_distance,
        risk_per_trade=strategy.risk_per_trade,
        leverage=strategy.leverage,
        commission=strategy.commission,
    )
    fee_estimate = size * signal["entry"] * strategy.commission * 2
    return {
        "size": round(size, 6),
        "risk_amount": round(risk_amount, 2),
        "fee_estimate": round(fee_estimate, 4),
    }


def check_signal_outcome(signal: dict, latest_price: float, strategy: StrategyConfig) -> tuple[str | None, float]:
    size = signal["size"]
    entry = signal["entry"]
    fee = signal["fee_estimate"]

    if signal["side"] == "LONG":
        if latest_price >= signal["target"]:
            gross = (signal["target"] - entry) * size
            return "TAKE", gross - fee
        if latest_price <= signal["stop"]:
            gross = (signal["stop"] - entry) * size
            return "STOP", gross - fee
    else:
        if latest_price <= signal["target"]:
            gross = (entry - signal["target"]) * size
            return "TAKE", gross - fee
        if latest_price >= signal["stop"]:
            gross = (entry - signal["stop"]) * size
            return "STOP", gross - fee

    return None, 0.0


def format_signal_message(
    symbol: str,
    timeframe: str,
    signal: dict,
    stats: dict,
    backtest_summary: str = "",
    profile_note: str = "",
) -> str:
    return (
        f"{symbol} {signal['side']} signal\n"
        f"Entry: {signal['entry']}\n"
        f"Stop: {signal['stop']}\n"
        f"Target: {signal['target']}\n"
        f"Timeframe: {timeframe}\n"
        f"RR: {signal['rr']}\n"
        f"Size: {stats['size']}\n"
        f"Risk: {stats['risk_amount']}$\n"
        f"Est. fees: {stats['fee_estimate']}$"
        f"{profile_note}"
        f"{backtest_summary}"
    )


def format_signal_close_message(
    symbol: str,
    tracked: dict,
    outcome: str,
    pnl: float,
    profile_note: str = "",
) -> str:
    return (
        f"{symbol} {outcome}\n"
        f"Entry: {tracked['entry']}\n"
        f"Exit price: {tracked['target'] if outcome == 'TAKE' else tracked['stop']}\n"
        f"Trade PnL: {round(pnl, 2)}$"
        f"{profile_note}"
    )


def collect_current_signals(config: AppConfig) -> list[dict]:
    items: list[dict] = []
    for profile in config.active_profiles():
        data = fetch_ohlcv(
            OHLCVRequest(
                exchange_id=config.exchange_id,
                symbol=profile.symbol,
                timeframe=profile.timeframe,
                limit=profile.lookback_bars,
            )
        )
        signal = latest_signal(data, profile.strategy)
        if not signal:
            continue
        stats = simulate_open_signal(signal, profile.strategy, config.starting_balance)
        items.append(
            {
                "symbol": profile.symbol,
                "timeframe": profile.timeframe,
                "signal": signal,
                "stats": stats,
            }
        )
    return items


def snapshot_open_signals(state: SignalRuntimeState) -> dict[str, dict]:
    with state.lock:
        return {symbol: tracked.copy() for symbol, tracked in state.open_signals.items()}


def run_signal_scan_cycle(
    config: AppConfig,
    notifier: TelegramNotifier,
    state: SignalRuntimeState,
    optimized_lookup: dict[str, dict] | None = None,
    paper_profile: "PaperProfile | None" = None,
) -> None:
    profiles = config.active_profiles()

    for profile in profiles:
        symbol = profile.symbol
        strategy = profile.strategy
        data = fetch_ohlcv(
            OHLCVRequest(
                exchange_id=config.exchange_id,
                symbol=symbol,
                timeframe=profile.timeframe,
                limit=profile.lookback_bars,
            )
        )
        latest_price = float(data["close"].iloc[-1])

        tracked_signal = None
        with state.lock:
            tracked_signal = state.open_signals.get(symbol)

        if tracked_signal:
            outcome, pnl = check_signal_outcome(tracked_signal, latest_price, strategy)
            if outcome:
                with state.lock:
                    tracked = state.open_signals.pop(symbol, tracked_signal)
                profile_note = ""
                if paper_profile:
                    close_summary = paper_profile.close_position(symbol, outcome)
                    if close_summary:
                        stats = close_summary["stats"]
                        profile_note = (
                            f"\nProfile balance: ${stats['balance']:.2f}"
                            f"\nTrades: {stats['closed_trades']} | Winrate: {stats['win_rate']:.2f}%"
                        )
                notifier.send(format_signal_close_message(symbol, tracked, outcome, pnl, profile_note=profile_note))

        signal = latest_signal(data, strategy)
        if not signal:
            continue

        key = f"{symbol}:{signal['side']}:{signal['entry']}"
        should_send = False
        stats = simulate_open_signal(signal, strategy, config.starting_balance)
        tracked_entry = {**signal, **stats}
        with state.lock:
            if symbol in state.open_signals:
                pass
            elif key not in state.sent_keys:
                profile_stats = None
                if paper_profile:
                    opened = paper_profile.open_position(symbol, profile.timeframe, signal, strategy.commission)
                    if not opened:
                        continue
                    tracked_entry = opened
                    profile_stats = opened
                else:
                    profile_stats = tracked_entry
                state.sent_keys.add(key)
                state.open_signals[symbol] = tracked_entry
                should_send = True
                stats = {
                    "size": profile_stats["size"],
                    "risk_amount": profile_stats["risk_amount"],
                    "fee_estimate": profile_stats["fee_estimate"],
                }

        if not should_send:
            continue

        backtest_summary = ""
        optimized_result = (optimized_lookup or {}).get(symbol)
        if optimized_result:
            best = optimized_result["best_result"]
            backtest_summary = (
                f"\nBacktest: winrate {best['win_rate']}%, RR {best['avg_rr']}, PF {best['profit_factor']}, PnL {best['return_pct']}%"
            )

        profile_note = ""
        if paper_profile:
            profile_note = (
                f"\nProfile balance: ${tracked_entry['profile_balance_at_entry']:.2f}"
                f"\nProfile risk: {tracked_entry['profile_risk_pct'] * 100:.2f}% | Leverage: {tracked_entry['profile_leverage']:.0f}x"
                f"\nMargin used: ${tracked_entry['margin_used']:.2f} | Max loss: ${tracked_entry['expected_loss']:.2f}"
                f"\nExpected profit: ${tracked_entry['expected_profit']:.2f}"
            )

        notifier.send(
            format_signal_message(
                symbol=symbol,
                timeframe=profile.timeframe,
                signal=signal,
                stats=stats,
                backtest_summary=backtest_summary,
                profile_note=profile_note,
            )
        )


def run_realtime_scan(config: AppConfig, optimized_lookup: dict[str, dict] | None = None) -> None:
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    state = SignalRuntimeState()

    while True:
        run_signal_scan_cycle(config, notifier, state, optimized_lookup)
        time.sleep(config.realtime_scan_interval_seconds)
