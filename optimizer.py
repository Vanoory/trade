from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace

import pandas as pd

from backtest_engine import run_backtest, run_period_backtests
from config import StrategyConfig


PERIOD_WEIGHTS = {30: 0.6, 60: 0.25, 90: 0.15}
STRATEGY_NAMES = ["trend_pullback", "momentum_breakout"]
FAST_EMA_ANCHORS = [5, 8, 11, 13, 18, 21, 27, 34, 42, 55, 72, 89]
SLOW_EMA_ANCHORS = [21, 29, 34, 55, 76, 89, 107, 120, 133, 149, 168, 200]
ADX_ANCHORS = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
RSI_LONG_ANCHORS = [48.0, 50.0, 52.0, 54.0, 56.0, 58.0, 60.0]
RSI_SHORT_ANCHORS = [38.0, 40.0, 42.0, 44.0, 46.0, 48.0, 50.0, 52.0, 54.0]
STOP_ATR_ANCHORS = [0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2]
TARGET_ATR_ANCHORS = [1.6, 1.8, 2.0, 2.4, 2.8, 3.2, 3.6, 4.0, 4.5, 5.0]
TRAIL_ATR_ANCHORS = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
BREAK_EVEN_ANCHORS = [0.0, 0.8, 1.0, 1.2, 1.5]
BREAKOUT_WINDOW_ANCHORS = [10, 14, 20, 30, 40, 55]
VOLUME_FACTOR_ANCHORS = [0.9, 0.92, 0.95, 0.98, 1.0, 1.03, 1.06, 1.1]
COOLDOWN_ANCHORS = [0, 1, 2, 3]


def timeframe_trade_targets(timeframe: str, days: int) -> tuple[float, float, float]:
    scale = max(days, 1) / 30.0
    if timeframe == "1h":
        return 6.0 * scale, 10.0 * scale, 16.0 * scale
    if timeframe == "30m":
        return 6.0 * scale, 12.0 * scale, 20.0 * scale
    if timeframe == "4h":
        return 2.0 * scale, 4.0 * scale, 7.0 * scale
    return 1.0 * scale, 3.0 * scale, 6.0 * scale


def trade_count_score(trades: int, timeframe: str, days: int) -> float:
    low, ideal, high = timeframe_trade_targets(timeframe, days)
    if trades <= 0:
        return -18.0
    if trades < low:
        return -((low - trades) ** 1.2) * 2.4
    if trades > high:
        return -((trades - high) ** 1.08) * 2.1
    return 7.5 - abs(trades - ideal) * 0.75


def score_period_result(result: dict, timeframe: str) -> float:
    days = int(result["period_days"])
    capped_rr = min(result["avg_rr"], 4.0)
    capped_pf = min(result["profit_factor"], 4.0)
    score = (
        result["return_pct"] * 2.8
        + result["win_rate"] * 0.55
        + capped_rr * 10.0
        + capped_pf * 12.0
        + result["sharpe"] * 8.0
        - result["max_drawdown_pct"] * 1.35
        + trade_count_score(result["trades"], timeframe, days)
    )

    if result["return_pct"] < 0:
        score += result["return_pct"] * 4.5
    if result["win_rate"] < 45.0:
        score -= (45.0 - result["win_rate"]) * 2.4
    if capped_pf < 1.15:
        score -= (1.15 - capped_pf) * 30.0
    if capped_rr < 1.25:
        score -= (1.25 - capped_rr) * 18.0
    return round(score, 3)


def nearest_anchor_values(current: float, anchors: list[float], extra: list[float], limit: int = 5) -> list[float]:
    candidates = set(anchors)
    candidates.add(current)
    candidates.update(current + delta for delta in extra)
    ordered = sorted(candidates, key=lambda value: (abs(value - current), value))
    return sorted(ordered[:limit])


def nearest_int_values(current: int, anchors: list[int], extra: list[int], limit: int = 5) -> list[int]:
    candidates = set(anchors)
    candidates.add(current)
    candidates.update(current + delta for delta in extra)
    filtered = sorted({value for value in candidates if value > 0}, key=lambda value: (abs(value - current), value))
    return sorted(filtered[:limit])


def strategy_key(config: StrategyConfig) -> tuple:
    return tuple(sorted(asdict(config).items()))


def evaluate_config(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
    config: StrategyConfig,
    cash: float,
    cache: dict[tuple, dict],
) -> dict:
    key = strategy_key(config)
    cached = cache.get(key)
    if cached:
        return cached

    period_results = run_period_backtests(data, config, symbol, cash, sorted(PERIOD_WEIGHTS))
    period_lookup = {item["period_days"]: item for item in period_results}
    full_result = run_backtest(data, config, symbol, cash, include_trade_log=False)
    recent_result = period_lookup.get(30, full_result)

    weighted_score = 0.0
    for days, weight in PERIOD_WEIGHTS.items():
        result = period_lookup.get(days)
        if not result:
            continue
        weighted_score += score_period_result(result, timeframe) * weight

    evaluation = {
        "score": round(weighted_score, 3),
        "full_result": full_result,
        "recent_result": recent_result,
        "period_results": period_results,
    }
    cache[key] = evaluation
    return evaluation


def candidate_values(param_name: str, config: StrategyConfig) -> list:
    if param_name == "strategy_name":
        return STRATEGY_NAMES
    if param_name == "trade_mode":
        return [
            (True, True),
            (True, False),
            (False, True),
        ]
    if param_name == "fast_ema":
        limit = max(5, config.slow_ema - 5)
        return [value for value in nearest_int_values(config.fast_ema, FAST_EMA_ANCHORS, [-8, -5, 5, 8]) if value < limit]
    if param_name == "slow_ema":
        minimum = config.fast_ema + 5
        return [value for value in nearest_int_values(config.slow_ema, SLOW_EMA_ANCHORS, [-21, -13, 13, 21]) if value > minimum]
    if param_name == "adx_min":
        return nearest_anchor_values(config.adx_min, ADX_ANCHORS, [-2.0, 2.0], limit=5)
    if param_name == "rsi_long_min":
        return nearest_anchor_values(config.rsi_long_min, RSI_LONG_ANCHORS, [-2.0, 2.0], limit=5)
    if param_name == "rsi_short_max":
        return nearest_anchor_values(config.rsi_short_max, RSI_SHORT_ANCHORS, [-2.0, 2.0], limit=5)
    if param_name == "stop_atr":
        return nearest_anchor_values(config.stop_atr, STOP_ATR_ANCHORS, [-0.2, 0.2], limit=5)
    if param_name == "target_atr":
        return nearest_anchor_values(config.target_atr, TARGET_ATR_ANCHORS, [-0.4, 0.4], limit=5)
    if param_name == "trail_atr":
        return nearest_anchor_values(config.trail_atr, TRAIL_ATR_ANCHORS, [-0.2, 0.2], limit=5)
    if param_name == "break_even_atr":
        return sorted(set(BREAK_EVEN_ANCHORS + [round(config.break_even_atr, 2)]))
    if param_name == "breakout_window":
        return sorted(set(BREAKOUT_WINDOW_ANCHORS + [config.breakout_window]))
    if param_name == "cooldown_bars":
        return sorted(set(COOLDOWN_ANCHORS + [config.cooldown_bars]))
    if param_name == "volume_factor":
        return nearest_anchor_values(config.volume_factor, VOLUME_FACTOR_ANCHORS, [-0.03, 0.03], limit=5)
    return []


def apply_candidate(config: StrategyConfig, param_name: str, value) -> StrategyConfig:
    if param_name == "trade_mode":
        allow_long, allow_short = value
        return replace(config, allow_long=allow_long, allow_short=allow_short)

    if param_name == "fast_ema":
        slow_ema = max(config.slow_ema, value + 5)
        return replace(config, fast_ema=int(value), slow_ema=slow_ema)
    if param_name == "slow_ema":
        slow_ema = max(int(value), config.fast_ema + 5)
        return replace(config, slow_ema=slow_ema)
    return replace(config, **{param_name: value})


def optimize_strategy(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
    starting_config: StrategyConfig,
    cash: float,
    passes: int = 2,
) -> dict:
    cache: dict[tuple, dict] = {}
    best_config = deepcopy(starting_config)
    best_eval = evaluate_config(data, symbol, timeframe, best_config, cash, cache)
    history = [
        {
            "iteration": 0,
            "parameter": "baseline",
            "score": best_eval["score"],
            "recent_result": best_eval["recent_result"],
            "config": replace(best_config),
        }
    ]

    parameter_order = [
        "strategy_name",
        "trade_mode",
        "fast_ema",
        "slow_ema",
        "adx_min",
        "rsi_long_min",
        "rsi_short_max",
        "stop_atr",
        "target_atr",
        "trail_atr",
        "break_even_atr",
        "breakout_window",
        "cooldown_bars",
        "volume_factor",
    ]

    iteration = 1
    for _ in range(passes):
        improved = False
        for param_name in parameter_order:
            local_best_config = best_config
            local_best_eval = best_eval

            for value in candidate_values(param_name, best_config):
                candidate_config = apply_candidate(best_config, param_name, value)
                if strategy_key(candidate_config) == strategy_key(best_config):
                    continue

                evaluation = evaluate_config(data, symbol, timeframe, candidate_config, cash, cache)
                history.append(
                    {
                        "iteration": iteration,
                        "parameter": param_name,
                        "value": value,
                        "score": evaluation["score"],
                        "recent_result": evaluation["recent_result"],
                        "config": replace(candidate_config),
                    }
                )
                iteration += 1

                if evaluation["score"] > local_best_eval["score"]:
                    local_best_config = deepcopy(candidate_config)
                    local_best_eval = evaluation

            if local_best_eval["score"] > best_eval["score"]:
                best_config = local_best_config
                best_eval = local_best_eval
                improved = True

        if not improved:
            break

    return {
        "symbol": symbol,
        "best_score": best_eval["score"],
        "best_result": best_eval["recent_result"],
        "best_full_result": best_eval["full_result"],
        "best_period_results": best_eval["period_results"],
        "best_config": best_config,
        "history": history,
    }
