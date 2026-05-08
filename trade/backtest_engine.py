from __future__ import annotations

from dataclasses import asdict
from math import isnan

import backtrader as bt
import pandas as pd

from config import StrategyConfig
from strategy import resolve_strategy_class


class PandasFeed(bt.feeds.PandasData):
    params = (("openinterest", None),)


def nested_get(data: dict, *keys: str, default: float = 0.0) -> float:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def run_backtest(
    data: pd.DataFrame,
    strategy_config: StrategyConfig,
    symbol: str,
    cash: float,
    include_trade_log: bool = True,
) -> dict:
    cerebro = bt.Cerebro(stdstats=False)
    strategy_cls = resolve_strategy_class(strategy_config.strategy_name)
    cerebro.addstrategy(strategy_cls, symbol=symbol, **asdict(strategy_config))
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=strategy_config.commission, leverage=strategy_config.leverage)
    cerebro.adddata(PandasFeed(dataname=data))
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    results = cerebro.run()
    strat = results[0]
    trade_analysis = strat.analyzers.trades.get_analysis()
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    drawdown_analysis = strat.analyzers.drawdown.get_analysis()
    returns_analysis = strat.analyzers.returns.get_analysis()

    total_closed = int(nested_get(trade_analysis, "total", "closed", default=0))
    wins = int(nested_get(trade_analysis, "won", "total", default=0))
    losses = int(nested_get(trade_analysis, "lost", "total", default=0))
    gross_profit = float(nested_get(trade_analysis, "won", "pnl", "total", default=0.0))
    gross_loss = abs(float(nested_get(trade_analysis, "lost", "pnl", "total", default=0.0)))
    avg_win = float(nested_get(trade_analysis, "won", "pnl", "average", default=0.0))
    avg_loss = abs(float(nested_get(trade_analysis, "lost", "pnl", "average", default=0.0)))

    if avg_loss > 0:
        avg_rr = round(avg_win / avg_loss, 3)
    elif avg_win > 0:
        avg_rr = 9.999
    else:
        avg_rr = 0.0

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 3)
    elif gross_profit > 0:
        profit_factor = 9.999
    else:
        profit_factor = 0.0
    win_rate = round((wins / total_closed) * 100, 2) if total_closed else 0.0
    net_profit = cerebro.broker.getvalue() - cash
    total_return_pct = round((net_profit / cash) * 100, 2) if cash else 0.0
    sharpe = sharpe_analysis.get("sharperatio", 0.0) or 0.0
    if isinstance(sharpe, float) and isnan(sharpe):
        sharpe = 0.0
    opened_trades = sum(1 for item in strat.trade_log if item["event"].startswith("entry_"))

    result = {
        "symbol": symbol,
        "starting_balance": cash,
        "ending_balance": round(cerebro.broker.getvalue(), 2),
        "net_profit": round(net_profit, 2),
        "return_pct": total_return_pct,
        "opened_trades": opened_trades,
        "trades": total_closed,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_rr": avg_rr,
        "profit_factor": profit_factor,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "configured_rr": round(strategy_config.target_atr / strategy_config.stop_atr, 3)
        if strategy_config.stop_atr
        else 0.0,
        "max_drawdown_pct": round(nested_get(drawdown_analysis, "max", "drawdown", default=0.0), 2),
        "sharpe": round(sharpe, 3),
        "annual_return_pct": round((returns_analysis.get("rnorm100", 0.0) or 0.0), 2),
    }
    if include_trade_log:
        result["trade_log"] = strat.trade_log
    return result


def slice_recent_days(data: pd.DataFrame, days: int) -> pd.DataFrame:
    if data.empty:
        return data
    end_ts = data.index.max()
    start_ts = end_ts - pd.Timedelta(days=days)
    return data[data.index >= start_ts].copy()


def run_period_backtests(
    data: pd.DataFrame,
    strategy_config: StrategyConfig,
    symbol: str,
    cash: float,
    periods: list[int],
) -> list[dict]:
    period_results: list[dict] = []
    for days in periods:
        sliced = slice_recent_days(data, days)
        if sliced.empty:
            continue
        period_result = run_backtest(
            sliced,
            strategy_config,
            symbol,
            cash,
            include_trade_log=False,
        )
        period_result["period_days"] = days
        period_results.append(period_result)
    return period_results
