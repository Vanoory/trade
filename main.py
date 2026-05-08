from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from backtest_engine import run_backtest, run_period_backtests
from config import load_config
from market_data import fetch_ohlcv, OHLCVRequest
from optimizer import optimize_strategy
from realtime_bot import run_realtime_scan
from reporting import build_summary_rows, build_summary_stats, format_summary_report
from telegram_runtime import run_telegram_bot


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-asset crypto setup scanner with backtesting.")
    parser.add_argument("--mode", choices=["backtest", "optimize", "realtime", "summary", "telegram"], default="optimize")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--risk-per-trade", type=float, default=None)
    args = parser.parse_args()

    config = load_config()
    profiles = config.active_profiles()

    if args.mode == "backtest":
        results = []
        for profile in profiles:
            data = fetch_ohlcv(
                OHLCVRequest(
                    exchange_id=config.exchange_id,
                    symbol=profile.symbol,
                    timeframe=profile.timeframe,
                    limit=profile.lookback_bars,
                )
            )
            full_result = run_backtest(
                data,
                profile.strategy,
                profile.symbol,
                config.starting_balance,
                include_trade_log=False,
            )
            period_results = run_period_backtests(
                data,
                profile.strategy,
                profile.symbol,
                config.starting_balance,
                config.backtest_periods,
            )
            results.append(
                {
                    "symbol": profile.symbol,
                    "timeframe": profile.timeframe,
                    "strategy_config": asdict(profile.strategy),
                    "full_backtest": full_result,
                    "period_backtests": period_results,
                }
            )
        print(json.dumps(results, default=str, indent=2))
        return

    if args.mode == "optimize":
        results = []
        for profile in profiles:
            data = fetch_ohlcv(
                OHLCVRequest(
                    exchange_id=config.exchange_id,
                    symbol=profile.symbol,
                    timeframe=profile.timeframe,
                    limit=profile.lookback_bars,
                )
            )
            optimized = optimize_strategy(
                data,
                profile.symbol,
                profile.timeframe,
                profile.strategy,
                config.starting_balance,
            )
            results.append(
                {
                    "symbol": profile.symbol,
                    "timeframe": profile.timeframe,
                    "best_score": optimized["best_score"],
                    "best_config": asdict(optimized["best_config"]),
                    "best_result": optimized["best_result"],
                    "best_full_result": optimized["best_full_result"],
                    "best_period_results": optimized["best_period_results"],
                }
            )
        print(json.dumps(results, default=str, indent=2))
        return

    if args.mode == "summary":
        rows = build_summary_rows(config, days=args.days, risk_per_trade=args.risk_per_trade)
        stats = build_summary_stats(rows, config.starting_balance)
        print(
            format_summary_report(
                rows,
                stats,
                days=args.days,
                risk_per_trade=args.risk_per_trade,
            )
        )
        return

    if args.mode == "realtime":
        run_realtime_scan(config)
        return

    if args.mode == "telegram":
        run_telegram_bot(config)


if __name__ == "__main__":
    main()
