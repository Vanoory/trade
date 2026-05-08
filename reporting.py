from __future__ import annotations

from dataclasses import replace

from backtest_engine import run_period_backtests
from config import AppConfig, SymbolProfile
from market_data import OHLCVRequest, fetch_ohlcv


def resolve_period_result(period_results: list[dict], days: int) -> dict:
    for result in period_results:
        if int(result.get("period_days", 0)) == days:
            return result
    raise ValueError(f"Backtest result for {days} days is not available.")


def _profile_strategy(profile: SymbolProfile, risk_per_trade: float | None):
    if risk_per_trade is None:
        return profile.strategy
    return replace(profile.strategy, risk_per_trade=risk_per_trade)


def build_summary_rows(
    config: AppConfig,
    days: int = 30,
    risk_per_trade: float | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for profile in config.active_profiles():
        strategy = _profile_strategy(profile, risk_per_trade)
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
        rows.append(
            {
                "symbol": profile.symbol,
                "timeframe": profile.timeframe,
                "strategy": strategy.strategy_name,
                "return_pct": period_result["return_pct"],
                "profit_usd": period_result["net_profit"],
                "trades": period_result["trades"],
                "win_rate": period_result["win_rate"],
                "avg_rr": period_result["avg_rr"],
                "profit_factor": period_result["profit_factor"],
                "max_drawdown_pct": period_result["max_drawdown_pct"],
            }
        )
    rows.sort(key=lambda item: item["profit_usd"], reverse=True)
    return rows


def build_summary_stats(rows: list[dict], starting_balance: float) -> dict:
    total_profit = round(sum(float(row["profit_usd"]) for row in rows), 2)
    total_allocated = round(starting_balance * len(rows), 2)
    total_return_pct = round((total_profit / total_allocated) * 100, 2) if total_allocated else 0.0
    return {
        "symbol_count": len(rows),
        "total_profit": total_profit,
        "total_allocated": total_allocated,
        "total_return_pct": total_return_pct,
    }


def format_summary_report(
    rows: list[dict],
    stats: dict,
    days: int,
    risk_per_trade: float | None = None,
) -> str:
    headers = [
        ("Asset", 12),
        ("TF", 4),
        ("Strategy", 18),
        ("PnL %", 8),
        ("Profit $", 10),
        ("Trades", 8),
        ("Winrate", 8),
        ("Avg RR", 8),
        ("PF", 8),
        ("Max DD", 8),
    ]

    def fmt_value(header: str, row: dict) -> str:
        if header == "Asset":
            return str(row["symbol"])
        if header == "TF":
            return str(row["timeframe"])
        if header == "Strategy":
            return str(row["strategy"])
        if header == "PnL %":
            return f"{row['return_pct']:.2f}%"
        if header == "Profit $":
            return f"${row['profit_usd']:.2f}"
        if header == "Trades":
            return str(int(row["trades"]))
        if header == "Winrate":
            return f"{row['win_rate']:.2f}%"
        if header == "Avg RR":
            return f"{row['avg_rr']:.3f}"
        if header == "PF":
            return f"{row['profit_factor']:.3f}"
        if header == "Max DD":
            return f"{row['max_drawdown_pct']:.2f}%"
        return ""

    header_line = "  ".join(title.ljust(width) for title, width in headers)
    separator = "  ".join("-" * width for _, width in headers)
    lines = [header_line, separator]

    for row in rows:
        formatted = []
        for title, width in headers:
            value = fmt_value(title, row)
            if title in {"Asset", "TF", "Strategy"}:
                formatted.append(value.ljust(width))
            else:
                formatted.append(value.rjust(width))
        lines.append("  ".join(formatted))

    lines.append("")
    lines.append(
        f"{days}-day total with $100 per coin separately: +${stats['total_profit']:.2f} "
        f"on ${stats['total_allocated']:.2f} ({stats['total_return_pct']:.2f}%)."
    )
    if risk_per_trade is not None:
        lines.append(f"Risk per trade override: {risk_per_trade * 100:.2f}% of deposit.")
    lines.append(f"Report period: {days} days. Coins in report: {stats['symbol_count']}.")
    return "\n".join(lines)
