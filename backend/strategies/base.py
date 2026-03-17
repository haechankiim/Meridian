"""Abstract strategy interface — all strategies implement this contract."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Signal(Enum):
    """Trading signal produced by a strategy."""
    STRONG_BUY = 2
    BUY = 1
    HOLD = 0
    SELL = -1
    STRONG_SELL = -2


@dataclass
class TradeSignal:
    """Complete trading signal with metadata."""
    signal: Signal
    confidence: float        # 0.0 - 1.0
    target_weight: float     # target portfolio weight for this asset
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    source: str = ""         # which strategy/model produced this


class BaseStrategy(ABC):
    """
    Abstract strategy interface.

    All strategies (momentum, mean reversion, ML ensemble, custom)
    must implement this interface. The backtesting engine calls
    generate_signals() on each time step.

    This is the Strategy pattern from CS2030S — the engine
    is decoupled from the specific strategy implementation.
    """

    def __init__(self, name: str, params: Optional[dict] = None):
        self.name = name
        self.params = params or {}

    @abstractmethod
    def generate_signals(
        self,
        data: pd.DataFrame,
        current_idx: int,
    ) -> dict[str, TradeSignal]:
        """
        Generate trading signals for all assets at a given time step.

        Args:
            data: DataFrame with OHLCV + features, multi-asset
            current_idx: current row index (look-back only, no future data)

        Returns:
            Dict mapping symbol -> TradeSignal
        """
        ...

    @abstractmethod
    def get_required_features(self) -> list[str]:
        """Return list of feature names this strategy needs."""
        ...

    def get_params(self) -> dict:
        return self.params

    def set_params(self, params: dict) -> None:
        self.params.update(params)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, params={self.params})"
