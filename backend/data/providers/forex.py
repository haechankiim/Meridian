"""Forex data provider with free Yahoo Finance fallback."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import aiohttp
import pandas as pd

from backend.app.config import get_settings
from backend.data.base import BaseDataProvider
from backend.data.providers.yahoo import fetch_yahoo_ohlcv


FOREX_PAIRS = [
    ("EUR", "USD"), ("GBP", "USD"), ("USD", "JPY"), ("USD", "SGD"),
    ("AUD", "USD"), ("USD", "CAD"), ("USD", "CHF"), ("NZD", "USD"),
    ("EUR", "GBP"), ("EUR", "JPY"),
]

AV_BASE = "https://www.alphavantage.co/query"


class ForexProvider(BaseDataProvider):
    """Fetches daily forex OHLCV with Alpha Vantage and Yahoo fallback."""

    def __init__(
        self,
        pairs: Optional[list[tuple[str, str]]] = None,
        api_key: Optional[str] = None,
    ):
        self.pairs = pairs or FOREX_PAIRS
        self.api_key = api_key or get_settings().alpha_vantage_key

    async def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch daily forex candles from Alpha Vantage or Yahoo Finance."""
        normalized_symbol = self.normalize_symbol(symbol)

        if self.api_key:
            try:
                return await self._fetch_alpha_vantage(normalized_symbol, start, end)
            except Exception:
                # Fall back to Yahoo Finance when the free Alpha Vantage tier throttles.
                pass

        return await self._fetch_yahoo(normalized_symbol, start, end, interval)

    async def fetch_batch(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple pairs while preserving normalized pair symbols."""
        normalized_symbols = [self.normalize_symbol(symbol) for symbol in symbols]

        if self.api_key:
            data: dict[str, pd.DataFrame] = {}
            for symbol in normalized_symbols:
                try:
                    data[symbol] = await self.fetch_historical(symbol, start, end, interval)
                    await asyncio.sleep(12)
                except Exception as exc:
                    print(f"[Forex] Failed to fetch {symbol}: {exc}")
            return data

        tasks = [
            self.fetch_historical(symbol, start, end, interval)
            for symbol in normalized_symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for symbol, result in zip(normalized_symbols, results):
            if isinstance(result, Exception):
                print(f"[Forex] Failed to fetch {symbol}: {result}")
                continue
            data[symbol] = result

        return data

    def get_available_symbols(self) -> list[str]:
        return [self._pair_to_symbol(from_currency, to_currency) for from_currency, to_currency in self.pairs]

    def get_asset_class(self) -> str:
        return "forex"

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        compact = symbol.strip().upper().replace(" ", "")
        if "/" in compact:
            base, quote = compact.split("/", maxsplit=1)
            return f"{base}/{quote}"

        if len(compact) == 6:
            return f"{compact[:3]}/{compact[3:]}"

        raise ValueError(f"Unsupported forex symbol format: {symbol}")

    @staticmethod
    def _pair_to_symbol(from_currency: str, to_currency: str) -> str:
        return f"{from_currency}/{to_currency}"

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        return f"{symbol.replace('/', '')}=X"

    async def _fetch_alpha_vantage(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        from_currency, to_currency = symbol.split("/")
        params = {
            "function": "FX_DAILY",
            "from_symbol": from_currency,
            "to_symbol": to_currency,
            "apikey": self.api_key,
            "outputsize": "full",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(AV_BASE, params=params) as response:
                if response.status != 200:
                    raise ValueError(f"Alpha Vantage error {response.status}")
                data = await response.json()

        time_series_key = "Time Series FX (Daily)"
        if time_series_key not in data:
            error_message = data.get("Note", data.get("Error Message", "Unknown error"))
            raise ValueError(f"Alpha Vantage: {error_message}")

        records = []
        for date_str, values in data[time_series_key].items():
            timestamp = datetime.strptime(date_str, "%Y-%m-%d")
            if start <= timestamp <= end:
                records.append(
                    {
                        "timestamp": timestamp,
                        "open": float(values["1. open"]),
                        "high": float(values["2. high"]),
                        "low": float(values["3. low"]),
                        "close": float(values["4. close"]),
                        "volume": 0.0,
                        "adjusted_close": float(values["4. close"]),
                        "symbol": symbol,
                    }
                )

        if not records:
            raise ValueError(f"No data in range for {symbol}")

        frame = pd.DataFrame(records)
        return self.validate_dataframe(frame)

    async def _fetch_yahoo(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> pd.DataFrame:
        yahoo_symbol = self._to_yahoo_symbol(symbol)
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(
            None,
            lambda: fetch_yahoo_ohlcv(
                yahoo_symbol,
                start,
                end,
                interval,
                default_volume=0.0,
            ),
        )
        frame["symbol"] = symbol
        return self.validate_dataframe(frame)
