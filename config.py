from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(slots=True)
class StrategyConfig:
    strategy_name: str = "trend_pullback"
    allow_long: bool = True
    allow_short: bool = True
    fast_ema: int = 8
    slow_ema: int = 120
    adx_period: int = 14
    adx_min: float = 16.0
    rsi_period: int = 14
    rsi_long_min: float = 52.0
    rsi_short_max: float = 46.0
    atr_period: int = 14
    stop_atr: float = 1.2
    target_atr: float = 3.2
    trail_atr: float = 0.6
    break_even_atr: float = 0.0
    cooldown_bars: int = 0
    breakout_window: int = 20
    volume_window: int = 20
    volume_factor: float = 1.03
    risk_per_trade: float = 0.01
    leverage: float = 2.0
    commission: float = 0.0006


@dataclass(slots=True)
class SymbolProfile:
    symbol: str
    timeframe: str
    lookback_bars: int
    strategy: StrategyConfig


@dataclass(slots=True)
class AppConfig:
    exchange_id: str = os.getenv("EXCHANGE_ID", "binance")
    timeframe: str = os.getenv("TIMEFRAME", "1h")
    lookback_bars: int = int(os.getenv("LOOKBACK_BARS", "2400"))
    realtime_scan_interval_seconds: int = int(os.getenv("REALTIME_SCAN_INTERVAL_SECONDS", "60"))
    telegram_poll_timeout_seconds: int = int(os.getenv("TELEGRAM_POLL_TIMEOUT_SECONDS", "15"))
    paper_start_balance: float = float(os.getenv("PAPER_START_BALANCE", "100"))
    paper_risk_per_trade: float = float(os.getenv("PAPER_RISK_PER_TRADE", "0.05"))
    paper_leverage: float = float(os.getenv("PAPER_LEVERAGE", "40"))
    paper_profile_path: Path = Path(os.getenv("PAPER_PROFILE_PATH", BASE_DIR / "paper_profile.json"))
    symbols: list[str] = field(
        default_factory=lambda: [
            "SOL/USDT",
            "XRP/USDT",
            "LINK/USDT",
            "DOGE/USDT",
            "TON/USDT",
            "ONDO/USDT",
            "GALA/USDT",
            "JTO/USDT",
            "ALGO/USDT",
            "ICP/USDT",
            "PENDLE/USDT",
            "ADA/USDT",
        ]
    )
    starting_balance: float = 100.0
    backtest_periods: list[int] = field(default_factory=lambda: [30, 60, 90])
    telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = os.getenv("TELEGRAM_CHAT_ID")
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    symbol_profiles: dict[str, SymbolProfile] = field(
        default_factory=lambda: {
            "BTC/USDT": SymbolProfile(
                symbol="BTC/USDT",
                timeframe="30m",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=True,
                    fast_ema=27,
                    slow_ema=97,
                    adx_min=24.0,
                    rsi_long_min=52.0,
                    rsi_short_max=42.0,
                    stop_atr=1.6,
                    target_atr=2.4,
                    trail_atr=1.2,
                    cooldown_bars=2,
                    volume_factor=1.03,
                    risk_per_trade=0.01,
                    leverage=2.0,
                ),
            ),
            "ETH/USDT": SymbolProfile(
                symbol="ETH/USDT",
                timeframe="1h",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=50,
                    slow_ema=162,
                    adx_min=12.0,
                    rsi_long_min=50.0,
                    rsi_short_max=44.0,
                    stop_atr=1.2,
                    target_atr=3.8,
                    trail_atr=0.2,
                    volume_factor=0.92,
                    cooldown_bars=1,
                    risk_per_trade=0.01,
                    leverage=2.0,
                ),
            ),
            "SOL/USDT": SymbolProfile(
                symbol="SOL/USDT",
                timeframe="1h",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="momentum_breakout",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=8,
                    slow_ema=89,
                    adx_min=18.0,
                    rsi_long_min=52.0,
                    rsi_short_max=44.0,
                    stop_atr=1.0,
                    target_atr=3.8,
                    trail_atr=0.2,
                    volume_factor=1.06,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "XRP/USDT": SymbolProfile(
                symbol="XRP/USDT",
                timeframe="1h",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    allow_long=False,
                    allow_short=True,
                    fast_ema=8,
                    slow_ema=21,
                    adx_min=22.0,
                    rsi_long_min=54.0,
                    rsi_short_max=52.0,
                    stop_atr=1.0,
                    target_atr=2.4,
                    trail_atr=0.8,
                    cooldown_bars=3,
                    volume_factor=1.09,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "LINK/USDT": SymbolProfile(
                symbol="LINK/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    allow_long=True,
                    allow_short=False,
                    fast_ema=42,
                    slow_ema=149,
                    adx_min=22.0,
                    rsi_long_min=52.0,
                    rsi_short_max=46.0,
                    stop_atr=0.6,
                    target_atr=2.0,
                    trail_atr=0.4,
                    volume_factor=1.0,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "DOGE/USDT": SymbolProfile(
                symbol="DOGE/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=11,
                    slow_ema=89,
                    adx_min=20.0,
                    rsi_long_min=56.0,
                    rsi_short_max=44.0,
                    stop_atr=0.8,
                    target_atr=4.2,
                    trail_atr=0.8,
                    cooldown_bars=0,
                    volume_factor=1.0,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "TON/USDT": SymbolProfile(
                symbol="TON/USDT",
                timeframe="1h",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=8,
                    slow_ema=68,
                    adx_min=20.0,
                    rsi_long_min=56.0,
                    rsi_short_max=44.0,
                    stop_atr=0.8,
                    target_atr=4.2,
                    trail_atr=0.6,
                    cooldown_bars=1,
                    volume_factor=1.0,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "ONDO/USDT": SymbolProfile(
                symbol="ONDO/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=11,
                    slow_ema=89,
                    adx_min=18.0,
                    rsi_long_min=56.0,
                    rsi_short_max=44.0,
                    stop_atr=0.6,
                    target_atr=4.2,
                    trail_atr=1.0,
                    cooldown_bars=0,
                    volume_factor=1.1,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "GALA/USDT": SymbolProfile(
                symbol="GALA/USDT",
                timeframe="1h",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=11,
                    slow_ema=68,
                    adx_min=20.0,
                    rsi_long_min=56.0,
                    rsi_short_max=44.0,
                    stop_atr=0.8,
                    target_atr=4.2,
                    trail_atr=0.6,
                    cooldown_bars=1,
                    volume_factor=1.0,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "JTO/USDT": SymbolProfile(
                symbol="JTO/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=5,
                    slow_ema=107,
                    adx_min=18.0,
                    rsi_long_min=48.0,
                    rsi_short_max=44.0,
                    stop_atr=0.4,
                    target_atr=4.2,
                    trail_atr=0.2,
                    cooldown_bars=3,
                    volume_factor=0.95,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "ALGO/USDT": SymbolProfile(
                symbol="ALGO/USDT",
                timeframe="30m",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=True,
                    fast_ema=26,
                    slow_ema=84,
                    adx_min=24.0,
                    rsi_long_min=54.0,
                    rsi_short_max=38.0,
                    stop_atr=1.0,
                    target_atr=2.0,
                    trail_atr=1.2,
                    break_even_atr=0.8,
                    cooldown_bars=1,
                    volume_factor=1.1,
                    risk_per_trade=0.01,
                    leverage=2.0,
                ),
            ),
            "ICP/USDT": SymbolProfile(
                symbol="ICP/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=11,
                    slow_ema=76,
                    adx_min=20.0,
                    rsi_long_min=60.0,
                    rsi_short_max=44.0,
                    stop_atr=0.4,
                    target_atr=4.2,
                    trail_atr=0.6,
                    cooldown_bars=3,
                    volume_factor=1.0,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "PENDLE/USDT": SymbolProfile(
                symbol="PENDLE/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    strategy_name="momentum_breakout",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=13,
                    slow_ema=89,
                    adx_min=16.0,
                    rsi_long_min=56.0,
                    rsi_short_max=44.0,
                    stop_atr=0.4,
                    target_atr=4.5,
                    trail_atr=0.8,
                    breakout_window=30,
                    volume_factor=0.95,
                    risk_per_trade=0.01,
                    leverage=2.5,
                ),
            ),
            "ADA/USDT": SymbolProfile(
                symbol="ADA/USDT",
                timeframe="4h",
                lookback_bars=1800,
                strategy=StrategyConfig(
                    allow_long=True,
                    allow_short=False,
                    fast_ema=8,
                    slow_ema=21,
                    adx_min=12.0,
                    rsi_long_min=54.0,
                    rsi_short_max=48.0,
                    stop_atr=0.4,
                    target_atr=2.8,
                    trail_atr=0.2,
                    cooldown_bars=1,
                    volume_factor=1.0,
                    risk_per_trade=0.0075,
                    leverage=1.5,
                ),
            ),
            "AVAX/USDT": SymbolProfile(
                symbol="AVAX/USDT",
                timeframe="1h",
                lookback_bars=2400,
                strategy=StrategyConfig(
                    strategy_name="trend_pullback",
                    allow_long=True,
                    allow_short=False,
                    fast_ema=11,
                    slow_ema=34,
                    adx_min=12.0,
                    rsi_long_min=54.0,
                    rsi_short_max=48.0,
                    stop_atr=0.6,
                    target_atr=2.0,
                    trail_atr=0.2,
                    cooldown_bars=2,
                    volume_factor=1.03,
                    risk_per_trade=0.0075,
                    leverage=1.5,
                ),
            ),
        }
    )

    def active_profiles(self) -> list[SymbolProfile]:
        profiles: list[SymbolProfile] = []
        for symbol in self.symbols:
            profile = self.symbol_profiles.get(symbol)
            if profile:
                profiles.append(profile)
            else:
                profiles.append(
                    SymbolProfile(
                        symbol=symbol,
                        timeframe=self.timeframe,
                        lookback_bars=self.lookback_bars,
                        strategy=self.strategy,
                    )
                )
        return profiles


def load_config() -> AppConfig:
    return AppConfig()
