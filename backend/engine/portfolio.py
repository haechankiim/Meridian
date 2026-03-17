"""Portfolio — position tracking, cash management, equity curve."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from backend.app.database import OrderSide
from backend.engine.broker import Fill


@dataclass
class Position:
    """Open position in a single asset."""
    symbol: str
    quantity: float = 0.0
    avg_cost: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) < 1e-9

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return self.quantity * (price - self.avg_cost)


class Portfolio:
    """
    Tracks cash, positions, and equity over time.

    Long-only: quantities are always non-negative.
    """

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash: float = initial_capital
        self.positions: dict[str, Position] = {}
        self.equity_curve: list[dict] = []   # [{timestamp, equity, cash, market_value}]
        self.trade_log: list[dict] = []       # one entry per fill

    def apply_fill(self, fill: Fill) -> float:
        """
        Update positions and cash from an executed fill.

        Returns realized PnL (non-zero only when closing/reducing a position).
        """
        symbol = fill.symbol
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]
        realized_pnl = 0.0

        if fill.side == OrderSide.BUY:
            # Update average cost (weighted average)
            total_cost = pos.avg_cost * pos.quantity + fill.fill_price * fill.quantity
            pos.quantity += fill.quantity
            pos.avg_cost = total_cost / pos.quantity
            self.cash -= fill.notional + fill.commission

        else:  # SELL
            qty_closed = min(fill.quantity, pos.quantity)
            realized_pnl = qty_closed * (fill.fill_price - pos.avg_cost) - fill.commission
            pos.quantity -= qty_closed
            pos.realized_pnl += realized_pnl
            self.cash += qty_closed * fill.fill_price - fill.commission

            if pos.is_flat:
                pos.avg_cost = 0.0

        self.trade_log.append({
            "symbol": fill.symbol,
            "side": fill.side.value,
            "quantity": fill.quantity,
            "price": fill.fill_price,
            "commission": fill.commission,
            "slippage": fill.slippage,
            "timestamp": fill.timestamp,
            "pnl": realized_pnl,
            "signal_source": fill.signal_source,
            "signal_confidence": fill.signal_confidence,
        })

        return realized_pnl

    def mark_to_market(self, prices: dict[str, float], timestamp: datetime) -> float:
        """
        Compute total portfolio equity and record it on the equity curve.

        Returns total equity (cash + market value of all open positions).
        """
        market_value = sum(
            pos.quantity * prices[sym]
            for sym, pos in self.positions.items()
            if not pos.is_flat and sym in prices
        )
        equity = self.cash + market_value

        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": equity,
            "cash": self.cash,
            "market_value": market_value,
        })

        return equity

    def get_equity(self, prices: dict[str, float]) -> float:
        """Current portfolio value without recording to equity curve."""
        market_value = sum(
            pos.quantity * prices.get(sym, 0.0)
            for sym, pos in self.positions.items()
            if not pos.is_flat
        )
        return self.cash + market_value

    def get_weights(self, prices: dict[str, float]) -> dict[str, float]:
        """Current portfolio weights: position market value / total equity."""
        equity = self.get_equity(prices)
        if equity <= 0:
            return {}
        return {
            sym: (pos.quantity * prices.get(sym, 0.0)) / equity
            for sym, pos in self.positions.items()
            if not pos.is_flat
        }

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
