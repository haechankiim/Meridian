"""Meridian database — SQLAlchemy models and connection."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Float, Integer, BigInteger, DateTime,
    Enum, Index, UniqueConstraint, ForeignKey, Text, JSON,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from backend.app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


INTERVAL_ENUM = Enum(
    "1m",
    "5m",
    "15m",
    "1h",
    "1d",
    "1w",
    name="candle_interval",
    native_enum=False,
    validate_strings=True,
)


# ── Enums ──────────────────────────────────────────────

class AssetClass(str, PyEnum):
    US_EQUITY = "us_equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    ASIA_EQUITY = "asia_equity"


class Interval(str, PyEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"


class OrderSide(str, PyEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, PyEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


# ── Market Data ────────────────────────────────────────

class Asset(Base):
    """Tradeable instrument metadata."""
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    name = Column(String(128))
    asset_class = Column(Enum(AssetClass), nullable=False)
    exchange = Column(String(32))
    currency = Column(String(8), default="USD")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    candles = relationship("Candle", back_populates="asset", lazy="dynamic")

    __table_args__ = (
        UniqueConstraint("symbol", "asset_class", name="uq_asset_symbol_class"),
    )


class Candle(Base):
    """OHLCV price bar."""
    __tablename__ = "candles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    interval = Column(INTERVAL_ENUM, nullable=False, default=Interval.D1.value)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0)
    adjusted_close = Column(Float)

    asset = relationship("Asset", back_populates="candles")

    __table_args__ = (
        UniqueConstraint("asset_id", "interval", "timestamp", name="uq_candle"),
        Index("ix_candle_asset_ts", "asset_id", "timestamp"),
    )


# ── Features ───────────────────────────────────────────

class Feature(Base):
    """Computed feature values for ML input."""
    __tablename__ = "features"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    feature_name = Column(String(64), nullable=False)
    value = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "timestamp", "feature_name", name="uq_feature"),
        Index("ix_feature_lookup", "asset_id", "feature_name", "timestamp"),
    )


# ── Backtests ──────────────────────────────────────────

class Backtest(Base):
    """Single backtest run metadata."""
    __tablename__ = "backtests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    strategy_name = Column(String(64), nullable=False)
    asset_class = Column(Enum(AssetClass))
    symbols = Column(JSON)  # list of symbols tested
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    initial_capital = Column(Float, nullable=False)
    parameters = Column(JSON)  # strategy params
    status = Column(String(16), default="pending")  # pending, running, done, failed
    created_at = Column(DateTime, default=datetime.utcnow)

    results = relationship("BacktestResult", back_populates="backtest", uselist=False)
    trades = relationship("Trade", back_populates="backtest", lazy="dynamic")


class BacktestResult(Base):
    """Aggregated performance metrics for a backtest."""
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backtest_id = Column(Integer, ForeignKey("backtests.id"), unique=True, nullable=False)
    total_return = Column(Float)
    annualized_return = Column(Float)
    sharpe_ratio = Column(Float)
    sortino_ratio = Column(Float)
    max_drawdown = Column(Float)
    calmar_ratio = Column(Float)
    alpha = Column(Float)
    beta = Column(Float)
    win_rate = Column(Float)
    profit_factor = Column(Float)
    total_trades = Column(Integer)
    avg_trade_duration = Column(Float)  # in days
    volatility = Column(Float)
    var_95 = Column(Float)
    cvar_95 = Column(Float)
    information_ratio = Column(Float)
    equity_curve = Column(JSON)  # list of {timestamp, equity}
    monthly_returns = Column(JSON)  # list of {month, return}

    backtest = relationship("Backtest", back_populates="results")


class Trade(Base):
    """Individual trade executed during a backtest."""
    __tablename__ = "trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    backtest_id = Column(Integer, ForeignKey("backtests.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    side = Column(Enum(OrderSide), nullable=False)
    order_type = Column(Enum(OrderType), default=OrderType.MARKET)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    timestamp = Column(DateTime, nullable=False)
    signal_source = Column(String(64))  # which model/strategy generated the signal
    signal_confidence = Column(Float)  # 0-1 confidence score
    pnl = Column(Float)  # realized PnL for closing trades

    backtest = relationship("Backtest", back_populates="trades")

    __table_args__ = (
        Index("ix_trade_backtest_ts", "backtest_id", "timestamp"),
    )


# ── ML Models ──────────────────────────────────────────

class ModelArtifact(Base):
    """Trained model metadata and path."""
    __tablename__ = "model_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_type = Column(String(32), nullable=False)  # transformer, rl, ensemble
    version = Column(String(32), nullable=False)
    asset_class = Column(Enum(AssetClass))
    symbols = Column(JSON)
    train_start = Column(DateTime)
    train_end = Column(DateTime)
    metrics = Column(JSON)  # {mse, mae, sharpe_improvement, ...}
    artifact_path = Column(String(256))  # path to saved weights
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Integer, default=1)

    __table_args__ = (
        Index("ix_model_type_active", "model_type", "is_active"),
    )


# ── Helpers ────────────────────────────────────────────

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _repair_legacy_interval_column(conn)
        await _ensure_backtest_result_metric_columns(conn)


async def _repair_legacy_interval_column(conn) -> None:
    """Convert legacy PostgreSQL INTERVAL columns to string-backed candle intervals."""
    if conn.dialect.name != "postgresql":
        return

    result = await conn.exec_driver_sql(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'candles'
          AND column_name = 'interval'
        """
    )
    row = result.first()
    if row is None or row[0] != "interval":
        return

    await conn.exec_driver_sql(
        "ALTER TABLE candles DROP CONSTRAINT IF EXISTS uq_candle"
    )
    await conn.exec_driver_sql(
        """
        ALTER TABLE candles
        ALTER COLUMN interval TYPE VARCHAR(8)
        USING CASE
            WHEN interval = INTERVAL '1 minute' THEN '1m'
            WHEN interval = INTERVAL '5 minutes' THEN '5m'
            WHEN interval = INTERVAL '15 minutes' THEN '15m'
            WHEN interval = INTERVAL '1 hour' THEN '1h'
            WHEN interval = INTERVAL '1 day' THEN '1d'
            WHEN interval = INTERVAL '7 days' THEN '1w'
            ELSE interval::text
        END
        """
    )
    await conn.exec_driver_sql(
        """
        ALTER TABLE candles
        ADD CONSTRAINT uq_candle UNIQUE (asset_id, interval, timestamp)
        """
    )


async def _ensure_backtest_result_metric_columns(conn) -> None:
    """Backfill newly added metric columns for existing local databases."""
    if conn.dialect.name != "postgresql":
        return

    await conn.exec_driver_sql(
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS volatility DOUBLE PRECISION"
    )
    await conn.exec_driver_sql(
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS var_95 DOUBLE PRECISION"
    )
    await conn.exec_driver_sql(
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS cvar_95 DOUBLE PRECISION"
    )
    await conn.exec_driver_sql(
        "ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS information_ratio DOUBLE PRECISION"
    )


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
