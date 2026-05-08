from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import ccxt
import pandas as pd


TIMEFRAME_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


@dataclass(slots=True)
class OHLCVRequest:
    exchange_id: str
    symbol: str
    timeframe: str
    limit: int


def build_exchange(exchange_id: str) -> Any:
    exchange_cls = getattr(ccxt, exchange_id)
    exchange = exchange_cls(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
    )
    return exchange


def fetch_ohlcv(request: OHLCVRequest) -> pd.DataFrame:
    exchange = build_exchange(request.exchange_id)
    candles = exchange.fetch_ohlcv(request.symbol, timeframe=request.timeframe, limit=request.limit)
    if not candles:
        raise ValueError(f"No candles returned for {request.symbol}")

    frame = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("datetime")
    frame = frame[["open", "high", "low", "close", "volume"]].astype(float)
    return frame


def fetch_many(exchange_id: str, symbols: list[str], timeframe: str, limit: int) -> dict[str, pd.DataFrame]:
    datasets: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        datasets[symbol] = fetch_ohlcv(
            OHLCVRequest(exchange_id=exchange_id, symbol=symbol, timeframe=timeframe, limit=limit)
        )
    return datasets
