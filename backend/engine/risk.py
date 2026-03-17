"""Risk manager — position sizing, drawdown limits, exposure control."""

from dataclasses import dataclass
from typing import Optional

from backend.app.database import OrderSide, OrderType
from backend.engine.broker import Order
from backend.engine.portfolio import Portfolio
from backend.strategies.base import Signal, TradeSignal


@dataclass
class RiskConfig:
    """Risk management parameters."""
    max_position_weight: float = 0.20   # max 20% NAV in any single asset
    max_drawdown_limit: float = -0.20   # halt trading if drawdown exceeds -20%
    max_gross_exposure: float = 1.0     # max 100% gross exposure (long-only)
    min_trade_size: float = 1.0         # minimum order quantity (shares/units)
    round_lot: float = 1.0              # lot size for rounding (1 = single shares)


class RiskManager:
    """
    Enforces risk rules and converts TradeSignals into sized Orders.

    Responsibilities:
    1. Convert strategy target_weight → order quantity.
    2. Clamp positions to max_position_weight.
    3. Reject orders when cash is insufficient.
    4. Halt trading when max drawdown is breached.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self._halted = False

    @property
    def is_halted(self) -> bool:
        return self._halted

    def check_drawdown(self, portfolio: Portfolio) -> bool:
        """
        Check whether the current drawdown exceeds the configured limit.
        Sets internal halt flag if breached. Returns True if trading may continue.
        """
        if len(portfolio.equity_curve) < 2:
            return True

        peak = max(e["equity"] for e in portfolio.equity_curve)
        current = portfolio.equity_curve[-1]["equity"]
        if peak <= 0:
            return True
        drawdown = (current / peak) - 1

        if drawdown <= self.config.max_drawdown_limit:
            self._halted = True
            return False

        return True

    def size_order(
        self,
        symbol: str,
        signal: TradeSignal,
        portfolio: Portfolio,
        prices: dict[str, float],
    ) -> Optional[Order]:
        """
        Convert a TradeSignal into a sized Order.

        Uses signal.target_weight as the desired portfolio allocation.
        For BUY signals: buys the delta between current and target weight.
        For SELL signals: sells down to target_weight (0 = full exit).

        Returns None if no trade should be placed.
        """
        if self._halted:
            return None

        if signal.signal == Signal.HOLD:
            return None

        price = prices.get(symbol)
        if not price or price <= 0:
            return None

        total_equity = portfolio.get_equity(prices)
        if total_equity <= 0:
            return None

        current_weights = portfolio.get_weights(prices)
        current_weight = current_weights.get(symbol, 0.0)

        # Clamp target weight to configured maximum
        target_weight = min(abs(signal.target_weight), self.config.max_position_weight)

        is_buy = signal.signal in (Signal.BUY, Signal.STRONG_BUY)
        is_sell = signal.signal in (Signal.SELL, Signal.STRONG_SELL)

        if is_buy:
            delta_weight = target_weight - current_weight
            if delta_weight < 0.001:
                return None  # already at or above target
            quantity = (delta_weight * total_equity) / price

        elif is_sell:
            pos = portfolio.get_position(symbol)
            if pos is None or pos.is_flat:
                return None
            target_qty = (target_weight * total_equity) / price
            quantity = pos.quantity - target_qty
            if quantity <= 0:
                return None

        else:
            return None

        # Round to lot size
        quantity = round(quantity / self.config.round_lot) * self.config.round_lot

        if quantity < self.config.min_trade_size:
            return None

        # Ensure sufficient cash for buy orders (with buffer for commission/slippage)
        if is_buy:
            cost_estimate = quantity * price * 1.002
            if cost_estimate > portfolio.cash:
                # Scale down to available cash
                quantity = portfolio.cash / (price * 1.002)
                quantity = round(quantity / self.config.round_lot) * self.config.round_lot
                if quantity < self.config.min_trade_size:
                    return None

        side = OrderSide.BUY if is_buy else OrderSide.SELL

        return Order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            signal_source=signal.source,
            signal_confidence=signal.confidence,
        )
