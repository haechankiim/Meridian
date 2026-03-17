"""Meridian configuration — environment-driven settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Meridian"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # API Keys
    alpha_vantage_key: str = ""
    binance_api_key: str = ""
    binance_api_secret: str = ""

    # Data settings
    default_lookback_days: int = 365 * 5  # 5 years of history
    ohlcv_interval: str = "1d"

    # ML settings
    transformer_epochs: int = 100
    transformer_lr: float = 1e-3
    rl_timesteps: int = 100_000

    # Backtest settings
    initial_capital: float = 100_000.0
    commission_rate: float = 0.001  # 10 bps
    slippage_rate: float = 0.0005  # 5 bps

    class Config:
        env_file = ".env"
        env_prefix = "MERIDIAN_"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
