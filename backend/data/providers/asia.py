"""Asia equity data provider — SGX, HKEX, KOSPI via Yahoo Finance."""

import asyncio
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.data.base import BaseDataProvider
from backend.data.providers.yahoo import fetch_yahoo_ohlcv


# Key indices and popular constituents
ASIA_SYMBOLS = {
    # Singapore (SGX) — STI components
    "sgx": [
        "^STI",       # Straits Times Index
        "D05.SI",     # DBS Group
        "O39.SI",     # OCBC Bank
        "U11.SI",     # UOB
        "Z74.SI",     # Singtel
        "C6L.SI",     # Singapore Airlines
        "C38U.SI",    # CapitaLand Integrated
        "Y92.SI",     # Thai Beverage
        "BN4.SI",     # Keppel Corp
        "A17U.SI",    # CapitaLand Ascendas REIT
    ],
    # Hong Kong (HKEX) — HSI components
    "hkex": [
        "^HSI",       # Hang Seng Index
        "0700.HK",    # Tencent
        "9988.HK",    # Alibaba
        "0005.HK",    # HSBC
        "1299.HK",    # AIA Group
        "3690.HK",    # Meituan
        "9999.HK",    # NetEase
        "2318.HK",    # Ping An
        "0941.HK",    # China Mobile
        "1810.HK",    # Xiaomi
    ],
    # Korea (KRX)
    "krx": [
        "^KS11",      # KOSPI
        "005930.KS",  # Samsung Electronics
        "000660.KS",  # SK Hynix
        "373220.KS",  # LG Energy Solution
        "207940.KS",  # Samsung Biologics
        "005380.KS",  # Hyundai Motor
        "006400.KS",  # Samsung SDI
        "051910.KS",  # LG Chem
        "035420.KS",  # NAVER
        "035720.KS",  # Kakao
    ],
}


class AsiaEquityProvider(BaseDataProvider):
    """Fetches Asian equity data via Yahoo Finance (free)."""

    def __init__(
        self,
        exchanges: Optional[list[str]] = None,
        custom_symbols: Optional[list[str]] = None,
    ):
        self.exchanges = exchanges or ["sgx", "hkex", "krx"]
        if custom_symbols:
            self.symbols = custom_symbols
        else:
            self.symbols = []
            for ex in self.exchanges:
                self.symbols.extend(ASIA_SYMBOLS.get(ex, []))

    async def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch single Asian equity symbol."""
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
        tasks = [
            self.fetch_historical(sym, start, end, interval)
            for sym in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                print(f"[Asia] Failed to fetch {sym}: {result}")
                continue
            data[sym] = result

        return data

    def get_available_symbols(self) -> list[str]:
        return self.symbols

    def get_asset_class(self) -> str:
        return "asia_equity"
