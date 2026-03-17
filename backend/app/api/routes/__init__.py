"""Compatibility exports for route modules mounted by the app."""

from backend.api.routes import analytics, backtest, data, models, strategies

__all__ = ["analytics", "backtest", "data", "models", "strategies"]
