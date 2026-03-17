"""Simulated broker — order execution with slippage and commission."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backend.app.database import OrderSide, OrderType


@dataclass
class Order:
    """Order submitted to the broker."""
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    timestamp: Optional[datetime] = None
    signal_source: str = ""
    signal_confidence: float = 0.0


@dataclass
class Fill:
    """Confirmed execution record."""
    symbol: str
    side: OrderSide
    quantity: float
    fill_price: float
    commission: float
    slippage: float
    notional: float
    timestamp: datetime
    signal_source: str = ""
    signal_confidence: float = 0.0
    pnl: float = 0.0  # filled in by portfolio on close


class SimulatedBroker:
    """
    Simulates order execution against end-of-bar close prices.

    Slippage model: fill at close ± slippage_rate (buys pay more, sells get less).
    Commission model: flat rate on notional value.
    """

    def __init__(
        self,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005,
    ):
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self._fills: list[Fill] = []

    def execute(self, order: Order, bar: dict) -> Optional[Fill]:
        """
        Execute an order against the current bar.

        Args:
            order: Order to execute.
            bar: Dict with keys {open, high, low, close, volume, timestamp}.

        Returns:
            Fill if executed, None if rejected (zero quantity, missing price).
        """
        if order.quantity <= 0:
            return None

        close = bar.get("close")
        if not close or close <= 0:
            return None

        if order.side == OrderSide.BUY:
            fill_price = close * (1 + self.slippage_rate)
        else:
            fill_price = close * (1 - self.slippage_rate)

        notional = order.quantity * fill_price
        commission = notional * self.commission_rate

        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            commission=commission,
            slippage=abs(fill_price - close) * order.quantity,
            notional=notional,
            timestamp=bar.get("timestamp", datetime.utcnow()),
            signal_source=order.signal_source,
            signal_confidence=order.signal_confidence,
        )

        self._fills.append(fill)
        return fill

    def get_fills(self) -> list[Fill]:
        return list(self._fills)

    def reset(self) -> None:
        self._fills.clear()
