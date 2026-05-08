from __future__ import annotations

import backtrader as bt


COMMON_PARAMS = (
    ("symbol", "UNKNOWN"),
    ("strategy_name", "trend_pullback"),
    ("allow_long", True),
    ("allow_short", True),
    ("fast_ema", 34),
    ("slow_ema", 89),
    ("adx_period", 14),
    ("adx_min", 18.0),
    ("rsi_period", 14),
    ("rsi_long_min", 52.0),
    ("rsi_short_max", 48.0),
    ("atr_period", 14),
    ("stop_atr", 1.6),
    ("target_atr", 3.2),
    ("trail_atr", 1.1),
    ("break_even_atr", 0.0),
    ("cooldown_bars", 0),
    ("breakout_window", 20),
    ("volume_window", 20),
    ("volume_factor", 1.05),
    ("risk_per_trade", 0.02),
    ("leverage", 2.0),
    ("commission", 0.0006),
)


def calculate_position_size(
    equity: float,
    price: float,
    stop_distance: float,
    risk_per_trade: float,
    leverage: float,
    commission: float,
) -> float:
    if stop_distance <= 0 or price <= 0 or equity <= 0:
        return 0.0

    risk_amount = equity * risk_per_trade
    raw_size = risk_amount / stop_distance
    leveraged_size = raw_size * leverage

    # Reserve a small fee buffer so Backtrader does not reject entries at the cash limit.
    fee_buffer = 1.0 + max(commission, 0.0) * 2.0
    max_size_by_cash = ((equity * leverage) / (price * fee_buffer)) * 0.995
    return max(0.0, min(leveraged_size, max_size_by_cash))


class BaseManagedStrategy(bt.Strategy):
    params = COMMON_PARAMS

    def __init__(self) -> None:
        self.ema_fast = bt.ind.EMA(period=self.p.fast_ema)
        self.ema_slow = bt.ind.EMA(period=self.p.slow_ema)
        self.rsi = bt.ind.RSI(period=self.p.rsi_period)
        self.atr = bt.ind.ATR(period=self.p.atr_period)
        self.adx = bt.ind.ADX(period=self.p.adx_period)
        self.volume_ma = bt.indicators.SimpleMovingAverage(self.data.volume, period=self.p.volume_window)

        self.entry_price: float | None = None
        self.stop_price: float | None = None
        self.target_price: float | None = None
        self.entry_atr: float | None = None
        self.direction: str | None = None
        self.order = None
        self.trade_log: list[dict] = []
        self.cooldown_until = 0
        self.pending_exit_reason: str | None = None

    def log_trade(self, event: str, price: float, pnl: float = 0.0) -> None:
        self.trade_log.append(
            {
                "datetime": self.data.datetime.datetime(0),
                "symbol": self.p.symbol,
                "event": event,
                "price": price,
                "pnl": pnl,
                "equity": self.broker.getvalue(),
            }
        )

    def calculate_size(self, stop_distance: float) -> float:
        equity = self.broker.getvalue()
        price = float(self.data.close[0])
        return calculate_position_size(
            equity=equity,
            price=price,
            stop_distance=stop_distance,
            risk_per_trade=self.p.risk_per_trade,
            leverage=self.p.leverage,
            commission=self.p.commission,
        )

    def minimum_bars(self) -> int:
        return max(self.p.slow_ema, self.p.volume_window, self.p.atr_period) + 5

    def long_entry_ok(self) -> bool:
        return False

    def short_entry_ok(self) -> bool:
        return False

    def next(self) -> None:
        if self.order:
            return

        price = float(self.data.close[0])
        atr = float(self.atr[0])

        if self.position:
            if self.direction == "long":
                if self.p.break_even_atr > 0 and self.entry_price is not None and self.entry_atr is not None:
                    if price - self.entry_price >= self.entry_atr * self.p.break_even_atr:
                        self.stop_price = max(self.stop_price or self.entry_price, self.entry_price)
                trailing_stop = price - atr * self.p.trail_atr
                self.stop_price = max(self.stop_price or trailing_stop, trailing_stop)
                if price <= (self.stop_price or 0):
                    self.pending_exit_reason = "stop"
                    self.order = self.close()
                elif price >= (self.target_price or price):
                    self.pending_exit_reason = "target"
                    self.order = self.close()
            elif self.direction == "short":
                if self.p.break_even_atr > 0 and self.entry_price is not None and self.entry_atr is not None:
                    if self.entry_price - price >= self.entry_atr * self.p.break_even_atr:
                        self.stop_price = min(self.stop_price or self.entry_price, self.entry_price)
                trailing_stop = price + atr * self.p.trail_atr
                self.stop_price = min(self.stop_price or trailing_stop, trailing_stop)
                if price >= (self.stop_price or 10**12):
                    self.pending_exit_reason = "stop"
                    self.order = self.close()
                elif price <= (self.target_price or price):
                    self.pending_exit_reason = "target"
                    self.order = self.close()
            return

        if len(self) < self.cooldown_until:
            return
        if len(self.data) < self.minimum_bars():
            return

        stop_distance = atr * self.p.stop_atr
        if stop_distance <= 0:
            return

        if self.long_entry_ok():
            size = self.calculate_size(stop_distance)
            if size > 0:
                self.order = self.buy(size=size)
        elif self.short_entry_ok():
            size = self.calculate_size(stop_distance)
            if size > 0:
                self.order = self.sell(size=size)

    def notify_order(self, order: bt.Order) -> None:
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            price = float(order.executed.price)
            atr = float(self.atr[0])
            if order.isbuy() and self.position.size > 0:
                self.entry_price = price
                self.stop_price = price - atr * self.p.stop_atr
                self.target_price = price + atr * self.p.target_atr
                self.entry_atr = atr
                self.direction = "long"
                self.log_trade("entry_long", price)
            elif order.issell() and self.position.size < 0:
                self.entry_price = price
                self.stop_price = price + atr * self.p.stop_atr
                self.target_price = price - atr * self.p.target_atr
                self.entry_atr = atr
                self.direction = "short"
                self.log_trade("entry_short", price)
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log_trade("order_failed", float(self.data.close[0]))

        self.order = None

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            reason = self.pending_exit_reason or "closed"
            exit_label = f"closed_{self.direction or 'flat'}_{reason}"
            self.log_trade(exit_label, float(self.data.close[0]), trade.pnlcomm)
            self.entry_price = None
            self.stop_price = None
            self.target_price = None
            self.entry_atr = None
            self.direction = None
            self.cooldown_until = len(self) + self.p.cooldown_bars
            self.pending_exit_reason = None


class TrendPullbackStrategy(BaseManagedStrategy):
    params = COMMON_PARAMS

    def long_entry_ok(self) -> bool:
        if not self.p.allow_long:
            return False
        close = float(self.data.close[0])
        return (
            self.ema_fast[0] > self.ema_slow[0]
            and close > self.ema_fast[0]
            and self.rsi[0] >= self.p.rsi_long_min
            and self.adx[0] >= self.p.adx_min
            and self.data.volume[0] >= self.volume_ma[0] * self.p.volume_factor
        )

    def short_entry_ok(self) -> bool:
        if not self.p.allow_short:
            return False
        close = float(self.data.close[0])
        return (
            self.ema_fast[0] < self.ema_slow[0]
            and close < self.ema_fast[0]
            and self.rsi[0] <= self.p.rsi_short_max
            and self.adx[0] >= self.p.adx_min
            and self.data.volume[0] >= self.volume_ma[0] * self.p.volume_factor
        )


class MomentumBreakoutStrategy(BaseManagedStrategy):
    params = COMMON_PARAMS

    def __init__(self) -> None:
        super().__init__()
        self.highest_high = bt.ind.Highest(self.data.high(-1), period=self.p.breakout_window)
        self.lowest_low = bt.ind.Lowest(self.data.low(-1), period=self.p.breakout_window)

    def minimum_bars(self) -> int:
        return max(super().minimum_bars(), self.p.breakout_window + 2)

    def long_entry_ok(self) -> bool:
        if not self.p.allow_long:
            return False
        close = float(self.data.close[0])
        breakout_level = float(self.highest_high[0])
        return (
            self.ema_fast[0] > self.ema_slow[0]
            and close > breakout_level
            and self.rsi[0] >= self.p.rsi_long_min
            and self.adx[0] >= self.p.adx_min
            and self.data.volume[0] >= self.volume_ma[0] * self.p.volume_factor
        )

    def short_entry_ok(self) -> bool:
        if not self.p.allow_short:
            return False
        close = float(self.data.close[0])
        breakout_level = float(self.lowest_low[0])
        return (
            self.ema_fast[0] < self.ema_slow[0]
            and close < breakout_level
            and self.rsi[0] <= self.p.rsi_short_max
            and self.adx[0] >= self.p.adx_min
            and self.data.volume[0] >= self.volume_ma[0] * self.p.volume_factor
        )


STRATEGY_REGISTRY = {
    "trend_pullback": TrendPullbackStrategy,
    "momentum_breakout": MomentumBreakoutStrategy,
}


def resolve_strategy_class(strategy_name: str) -> type[bt.Strategy]:
    return STRATEGY_REGISTRY.get(strategy_name, TrendPullbackStrategy)
