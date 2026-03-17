"""US Equities data provider — S&P 500 via yfinance."""

import asyncio
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.data.base import BaseDataProvider
from backend.data.providers.yahoo import fetch_yahoo_ohlcv


# Top 50 S&P 500 by weight — expandable
SP500_TOP = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK-B",
    "UNH", "XOM", "JNJ", "JPM", "V", "PG", "MA", "AVGO", "HD", "CVX",
    "MRK", "ABBV", "LLY", "PEP", "KO", "COST", "ADBE", "WMT", "MCD",
    "CRM", "BAC", "CSCO", "ACN", "TMO", "NFLX", "AMD", "LIN", "ABT",
    "DHR", "ORCL", "CMCSA", "TXN", "PM", "NEE", "RTX", "HON", "INTC",
    "UPS", "LOW", "UNP", "QCOM", "SPGI",
]


class USEquityProvider(BaseDataProvider):
    """Fetches US equity OHLCV data via yfinance (free, no API key)."""

    def __init__(self, symbols: Optional[list[str]] = None):
        self.symbols = symbols or SP500_TOP

    async def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch single symbol from yfinance."""
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: fetch_yahoo_ohlcv(symbol, start, end, interval),
        )
        return self.validate_dataframe(df)

    async def fetch_batch(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple symbols concurrently."""
        tasks = [
            self.fetch_historical(sym, start, end, interval)
            for sym in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                print(f"[USEquity] Failed to fetch {sym}: {result}")
                continue
            data[sym] = result

        return data

    def get_available_symbols(self) -> list[str]:
        return self.symbols

    def get_asset_class(self) -> str:
        return "us_equity"
