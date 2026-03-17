"""Crypto data provider — top coins via Binance public API."""

import asyncio
from datetime import datetime
from typing import Optional

import pandas as pd
import aiohttp

from backend.data.base import BaseDataProvider


CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "NEARUSDT",
    "APTUSDT", "OPUSDT", "ARBUSDT", "FILUSDT", "INJUSDT",
]

BINANCE_BASE = "https://api.binance.com/api/v3"

INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "1d": "1d", "1w": "1w",
}


class CryptoProvider(BaseDataProvider):
    """Fetches crypto OHLCV from Binance public API (no key needed for klines)."""

    def __init__(self, symbols: Optional[list[str]] = None):
        self.symbols = symbols or CRYPTO_SYMBOLS

    async def _fetch_klines(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch klines (candlestick) data from Binance."""
        bi = INTERVAL_MAP.get(interval, "1d")
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_candles = []
        current_start = start_ms

        while current_start < end_ms:
            params = {
                "symbol": symbol,
                "interval": bi,
                "startTime": current_start,
                "endTime": end_ms,
                "limit": limit,
            }

            async with session.get(f"{BINANCE_BASE}/klines", params=params) as resp:
                if resp.status != 200:
                    raise ValueError(f"Binance API error {resp.status} for {symbol}")
                data = await resp.json()

            if not data:
                break

            all_candles.extend(data)
            # Move start to after last candle's close time
            current_start = data[-1][6] + 1

            if len(data) < limit:
                break

        if not all_candles:
            raise ValueError(f"No data returned for {symbol}")

        df = pd.DataFrame(all_candles, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])

        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df["symbol"] = symbol
        df["adjusted_close"] = df["close"]

        df = df[["symbol", "timestamp", "open", "high", "low",
                  "close", "volume", "adjusted_close"]]

        return self.validate_dataframe(df)

    async def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        async with aiohttp.ClientSession() as session:
            return await self._fetch_klines(session, symbol, start, end, interval)

    async def fetch_batch(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        async with aiohttp.ClientSession() as session:
            tasks = [
                self._fetch_klines(session, sym, start, end, interval)
                for sym in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                print(f"[Crypto] Failed to fetch {sym}: {result}")
                continue
            data[sym] = result

        return data

    def get_available_symbols(self) -> list[str]:
        return self.symbols

    def get_asset_class(self) -> str:
        return "crypto"
