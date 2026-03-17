"""Abstract base class for all market data providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd


@dataclass
class CandleData:
    """Standardized OHLCV record across all providers."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted_close: Optional[float] = None


class BaseDataProvider(ABC):
    """
    All data providers (US equities, crypto, forex, Asia)
    must implement this interface.

    This is the Strategy pattern in action — the backtesting engine
    doesn't care which provider supplies the data, only that it
    conforms to this contract.
    """

    @abstractmethod
    async def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for a single symbol.

        Returns DataFrame with columns:
            timestamp, open, high, low, close, volume, adjusted_close
        Index: DatetimeIndex on 'timestamp'
        """
        ...

    @abstractmethod
    async def fetch_batch(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch historical data for multiple symbols concurrently."""
        ...

    @abstractmethod
    def get_available_symbols(self) -> list[str]:
        """Return list of symbols this provider supports."""
        ...

    @abstractmethod
    def get_asset_class(self) -> str:
        """Return the asset class identifier (e.g. 'us_equity')."""
        ...

    def validate_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate and clean a raw OHLCV DataFrame.
        Ensures consistent column naming, drops NaNs, sorts by time.
        """
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Sanity checks
        assert (df["high"] >= df["low"]).all(), "high < low detected"
        assert (df["close"] > 0).all(), "non-positive close detected"

        return df
