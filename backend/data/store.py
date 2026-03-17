"""Data store — read/write OHLCV data to PostgreSQL."""

from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import Asset, Candle, AssetClass, Interval


class DataStore:
    """Handles all database operations for market data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Assets ─────────────────────────────────────────

    async def upsert_asset(
        self,
        symbol: str,
        asset_class: AssetClass,
        name: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: str = "USD",
    ) -> Asset:
        """Insert or update an asset record."""
        stmt = pg_insert(Asset).values(
            symbol=symbol,
            asset_class=asset_class,
            name=name or symbol,
            exchange=exchange,
            currency=currency,
        ).on_conflict_do_update(
            constraint="uq_asset_symbol_class",
            set_={"name": name or symbol, "exchange": exchange},
        ).returning(Asset.id)

        result = await self.session.execute(stmt)
        await self.session.commit()
        asset_id = result.scalar_one()

        return await self.session.get(Asset, asset_id)

    async def get_asset(self, symbol: str, asset_class: AssetClass) -> Optional[Asset]:
        stmt = select(Asset).where(
            and_(Asset.symbol == symbol, Asset.asset_class == asset_class)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Candles ────────────────────────────────────────

    async def store_candles(
        self,
        asset_id: int,
        df: pd.DataFrame,
        interval: Interval = Interval.D1,
    ) -> int:
        """
        Bulk upsert OHLCV candles from a DataFrame.
        Returns number of rows inserted/updated.
        """
        if df.empty:
            return 0

        interval_value = _normalize_interval(interval)
        records = []
        for _, row in df.iterrows():
            records.append({
                "asset_id": asset_id,
                "interval": interval_value,
                "timestamp": row["timestamp"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row.get("volume", 0.0),
                "adjusted_close": row.get("adjusted_close"),
            })

        stmt = pg_insert(Candle).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_candle",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "adjusted_close": stmt.excluded.adjusted_close,
            },
        )

        await self.session.execute(stmt)
        await self.session.commit()
        return len(records)

    async def get_candles(
        self,
        asset_id: int,
        start: datetime,
        end: datetime,
        interval: Interval = Interval.D1,
    ) -> pd.DataFrame:
        """Load candles as a DataFrame."""
        interval_value = _normalize_interval(interval)
        stmt = (
            select(Candle)
            .where(
                and_(
                    Candle.asset_id == asset_id,
                    Candle.interval == interval_value,
                    Candle.timestamp >= start,
                    Candle.timestamp <= end,
                )
            )
            .order_by(Candle.timestamp)
        )

        result = await self.session.execute(stmt)
        candles = result.scalars().all()

        if not candles:
            return pd.DataFrame()

        records = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "adjusted_close": c.adjusted_close,
            }
            for c in candles
        ]

        df = pd.DataFrame(records)
        df = df.set_index("timestamp").sort_index()
        return df

    async def get_latest_timestamp(
        self,
        asset_id: int,
        interval: Interval = Interval.D1,
    ) -> Optional[datetime]:
        """Get the most recent candle timestamp for incremental updates."""
        from sqlalchemy import func

        interval_value = _normalize_interval(interval)
        stmt = select(func.max(Candle.timestamp)).where(
            and_(Candle.asset_id == asset_id, Candle.interval == interval_value)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


def _normalize_interval(interval: Interval | str) -> str:
    if isinstance(interval, Interval):
        return interval.value
    return Interval(interval).value
