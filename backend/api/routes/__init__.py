"""Route modules exposed to the FastAPI app."""

from . import analytics, backtest, data, models, strategies

__all__ = ["analytics", "backtest", "data", "models", "strategies"]
