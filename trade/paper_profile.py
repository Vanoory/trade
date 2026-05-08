from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from realtime_bot import SignalRuntimeState


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class PaperProfile:
    def __init__(
        self,
        storage_path: Path,
        initial_balance: float,
        risk_per_trade: float,
        leverage: float,
    ) -> None:
        self.storage_path = storage_path
        self.default_initial_balance = float(initial_balance)
        self.default_risk_per_trade = float(risk_per_trade)
        self.default_leverage = float(leverage)
        self.lock = Lock()
        self.state = self._load_state()

    def _default_state(self) -> dict:
        balance = round(self.default_initial_balance, 2)
        return {
            "initial_balance": balance,
            "balance": balance,
            "risk_per_trade": self.default_risk_per_trade,
            "leverage": self.default_leverage,
            "wins": 0,
            "losses": 0,
            "closed_trades": 0,
            "realized_pnl": 0.0,
            "total_fees": 0.0,
            "peak_balance": balance,
            "max_drawdown_pct": 0.0,
            "open_positions": {},
            "closed_history": [],
            "updated_at": utc_now(),
        }

    def _load_state(self) -> dict:
        if self.storage_path.exists():
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
            loaded.setdefault("risk_per_trade", self.default_risk_per_trade)
            loaded.setdefault("leverage", self.default_leverage)
            loaded.setdefault("open_positions", {})
            loaded.setdefault("closed_history", [])
            loaded.setdefault("wins", 0)
            loaded.setdefault("losses", 0)
            loaded.setdefault("closed_trades", 0)
            loaded.setdefault("realized_pnl", round(float(loaded.get("balance", 0.0)) - float(loaded.get("initial_balance", 0.0)), 2))
            loaded.setdefault("total_fees", 0.0)
            loaded.setdefault("peak_balance", float(loaded.get("balance", self.default_initial_balance)))
            loaded.setdefault("max_drawdown_pct", 0.0)
            loaded.setdefault("updated_at", utc_now())
            return loaded

        state = self._default_state()
        self._save_state(state)
        return state

    def _save_state(self, state: dict | None = None) -> None:
        payload = state or self.state
        payload["updated_at"] = utc_now()
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def restore_runtime_state(self, runtime_state: SignalRuntimeState) -> None:
        with self.lock, runtime_state.lock:
            runtime_state.sent_keys = set()
            runtime_state.open_signals = {
                symbol: deepcopy(position)
                for symbol, position in self.state.get("open_positions", {}).items()
            }
            for symbol, position in runtime_state.open_signals.items():
                runtime_state.sent_keys.add(f"{symbol}:{position['side']}:{position['entry']}")

    def reset(self) -> dict:
        with self.lock:
            self.state = self._default_state()
            self._save_state()
            return deepcopy(self.state)

    def snapshot(self) -> dict:
        with self.lock:
            return deepcopy(self.state)

    def _available_margin(self) -> float:
        used_margin = sum(float(position.get("margin_used", 0.0)) for position in self.state["open_positions"].values())
        return max(0.0, float(self.state["balance"]) - used_margin)

    def _compute_size(self, entry: float, stop: float, commission: float) -> dict:
        stop_distance = abs(entry - stop)
        balance = float(self.state["balance"])
        risk_per_trade = float(self.state["risk_per_trade"])
        leverage = float(self.state["leverage"])
        available_margin = self._available_margin()

        if stop_distance <= 0 or balance <= 0 or entry <= 0 or available_margin <= 0:
            return {
                "size": 0.0,
                "risk_amount": 0.0,
                "margin_used": 0.0,
                "fee_estimate": 0.0,
                "available_margin": round(available_margin, 2),
            }

        risk_amount = balance * risk_per_trade
        size_by_risk = risk_amount / stop_distance
        fee_buffer = 1.0 + max(commission, 0.0) * 2.0
        size_by_margin = (available_margin * leverage) / (entry * fee_buffer)
        size = max(0.0, min(size_by_risk, size_by_margin) * 0.995)
        margin_used = (size * entry) / leverage if leverage > 0 else 0.0
        fee_estimate = size * entry * commission * 2.0
        return {
            "size": round(size, 6),
            "risk_amount": round(risk_amount, 2),
            "margin_used": round(margin_used, 2),
            "fee_estimate": round(fee_estimate, 4),
            "available_margin": round(available_margin, 2),
        }

    def open_position(self, symbol: str, timeframe: str, signal: dict, commission: float) -> dict | None:
        with self.lock:
            if symbol in self.state["open_positions"]:
                return deepcopy(self.state["open_positions"][symbol])

            sizing = self._compute_size(signal["entry"], signal["stop"], commission)
            if sizing["size"] <= 0:
                return None

            target_distance = abs(signal["target"] - signal["entry"])
            position = {
                **signal,
                **sizing,
                "symbol": symbol,
                "timeframe": timeframe,
                "commission": commission,
                "status": "OPEN",
                "opened_at": utc_now(),
                "profile_balance_at_entry": round(float(self.state["balance"]), 2),
                "profile_risk_pct": float(self.state["risk_per_trade"]),
                "profile_leverage": float(self.state["leverage"]),
                "expected_profit": round((target_distance * sizing["size"]) - sizing["fee_estimate"], 2),
                "expected_loss": round((abs(signal["entry"] - signal["stop"]) * sizing["size"]) + sizing["fee_estimate"], 2),
            }
            self.state["open_positions"][symbol] = position
            self._save_state()
            return deepcopy(position)

    def close_position(self, symbol: str, outcome: str) -> dict | None:
        with self.lock:
            position = self.state["open_positions"].pop(symbol, None)
            if not position:
                return None

            entry = float(position["entry"])
            exit_price = float(position["target"] if outcome == "TAKE" else position["stop"])
            size = float(position["size"])
            fee = float(position["fee_estimate"])

            if position["side"] == "LONG":
                gross_pnl = (exit_price - entry) * size
            else:
                gross_pnl = (entry - exit_price) * size

            net_pnl = round(gross_pnl - fee, 2)
            self.state["balance"] = round(float(self.state["balance"]) + net_pnl, 2)
            self.state["realized_pnl"] = round(float(self.state["balance"]) - float(self.state["initial_balance"]), 2)
            self.state["total_fees"] = round(float(self.state["total_fees"]) + fee, 4)
            self.state["closed_trades"] = int(self.state["closed_trades"]) + 1
            if net_pnl >= 0:
                self.state["wins"] = int(self.state["wins"]) + 1
            else:
                self.state["losses"] = int(self.state["losses"]) + 1

            peak_balance = max(float(self.state["peak_balance"]), float(self.state["balance"]))
            self.state["peak_balance"] = round(peak_balance, 2)
            if peak_balance > 0:
                current_drawdown = ((peak_balance - float(self.state["balance"])) / peak_balance) * 100.0
                self.state["max_drawdown_pct"] = round(
                    max(float(self.state["max_drawdown_pct"]), current_drawdown),
                    2,
                )

            trade_record = {
                "symbol": symbol,
                "timeframe": position["timeframe"],
                "side": position["side"],
                "entry": position["entry"],
                "exit": round(exit_price, 4),
                "outcome": outcome,
                "size": position["size"],
                "margin_used": position["margin_used"],
                "pnl": net_pnl,
                "fee": round(fee, 4),
                "opened_at": position["opened_at"],
                "closed_at": utc_now(),
                "balance_after": self.state["balance"],
            }
            history = self.state["closed_history"]
            history.append(trade_record)
            self.state["closed_history"] = history[-100:]
            self._save_state()

            return {
                "trade": trade_record,
                "stats": self.summary_stats(),
            }

    def summary_stats(self) -> dict:
        closed_trades = int(self.state["closed_trades"])
        wins = int(self.state["wins"])
        losses = int(self.state["losses"])
        win_rate = round((wins / closed_trades) * 100.0, 2) if closed_trades else 0.0
        open_positions = self.state["open_positions"]
        total_open_margin = round(
            sum(float(position.get("margin_used", 0.0)) for position in open_positions.values()),
            2,
        )
        total_open_risk = round(
            sum(float(position.get("expected_loss", 0.0)) for position in open_positions.values()),
            2,
        )
        return {
            "initial_balance": round(float(self.state["initial_balance"]), 2),
            "balance": round(float(self.state["balance"]), 2),
            "realized_pnl": round(float(self.state["realized_pnl"]), 2),
            "closed_trades": closed_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "open_positions": len(open_positions),
            "open_margin_used": total_open_margin,
            "open_risk_estimate": total_open_risk,
            "available_margin": round(self._available_margin(), 2),
            "risk_per_trade": float(self.state["risk_per_trade"]),
            "leverage": float(self.state["leverage"]),
            "total_fees": round(float(self.state["total_fees"]), 4),
            "peak_balance": round(float(self.state["peak_balance"]), 2),
            "max_drawdown_pct": round(float(self.state["max_drawdown_pct"]), 2),
        }

    def format_profile_report(self) -> str:
        stats = self.summary_stats()
        return "\n".join(
            [
                "Paper profile",
                f"Balance: ${stats['balance']:.2f} | Start: ${stats['initial_balance']:.2f}",
                f"Realized PnL: ${stats['realized_pnl']:.2f}",
                f"Trades: {stats['closed_trades']} | Wins: {stats['wins']} | Losses: {stats['losses']}",
                f"Winrate: {stats['win_rate']:.2f}% | Max DD: {stats['max_drawdown_pct']:.2f}%",
                f"Open positions: {stats['open_positions']} | Open risk: ${stats['open_risk_estimate']:.2f}",
                f"Margin used: ${stats['open_margin_used']:.2f} | Free margin: ${stats['available_margin']:.2f}",
                f"Risk per trade: {stats['risk_per_trade'] * 100:.2f}% | Leverage: {stats['leverage']:.0f}x",
                f"Fees paid: ${stats['total_fees']:.4f}",
            ]
        )

    def format_recent_trades(self, limit: int = 10) -> str:
        with self.lock:
            history = list(self.state["closed_history"][-limit:])
        if not history:
            return "Closed trades history is empty."

        lines: list[str] = []
        for item in reversed(history):
            lines.append(
                (
                    f"{item['symbol']} {item['side']} {item['outcome']} | "
                    f"PnL ${item['pnl']:.2f} | Balance ${item['balance_after']:.2f}"
                )
            )
        return "\n".join(lines)
