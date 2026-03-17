"""Provider exports and free-first registry helpers."""

from __future__ import annotations

from backend.data.base import BaseDataProvider
from backend.data.providers.asia import AsiaEquityProvider
from backend.data.providers.crypto import CryptoProvider
from backend.data.providers.forex import ForexProvider
from backend.data.providers.us_equities import USEquityProvider

FREE_PROVIDER_REGISTRY = {
    "us_equity": {
        "factory": USEquityProvider,
        "provider": "yfinance",
        "notes": "Free daily and intraday history via Yahoo Finance.",
        "default_benchmark": "SPY",
        "free_tier": True,
        "mvp_enabled": True,
    },
    "crypto": {
        "factory": CryptoProvider,
        "provider": "binance_public",
        "notes": "Free Binance public klines API for crypto pairs.",
        "default_benchmark": "BTCUSDT",
        "free_tier": True,
        "mvp_enabled": True,
    },
    "asia_equity": {
        "factory": AsiaEquityProvider,
        "provider": "yfinance",
        "notes": "Free Yahoo Finance coverage for SGX, HKEX, and KRX symbols.",
        "default_benchmark": "^STI",
        "free_tier": True,
        "mvp_enabled": True,
    },
    "forex": {
        "factory": ForexProvider,
        "provider": "yfinance_fallback",
        "notes": "Free daily FX via Yahoo Finance, with Alpha Vantage used when a key is configured.",
        "default_benchmark": None,
        "free_tier": True,
        "mvp_enabled": True,
    },
}

LIMITED_PROVIDER_REGISTRY = {}


def normalize_asset_symbol(asset_class: str, symbol: str) -> str:
    """Return the canonical symbol format for an asset class."""
    cleaned = symbol.strip().upper()
    if asset_class == "forex":
        return ForexProvider.normalize_symbol(cleaned)
    return cleaned


def list_supported_asset_classes(include_limited: bool = False) -> list[str]:
    """Return supported asset classes in stable order."""
    registry = dict(FREE_PROVIDER_REGISTRY)
    if include_limited:
        registry.update(LIMITED_PROVIDER_REGISTRY)
    return list(registry.keys())


def get_provider(asset_class: str, include_limited: bool = False) -> BaseDataProvider:
    """Instantiate a provider for the requested asset class."""
    registry = dict(FREE_PROVIDER_REGISTRY)
    if include_limited:
        registry.update(LIMITED_PROVIDER_REGISTRY)

    config = registry.get(asset_class)
    if not config:
        supported = ", ".join(list_supported_asset_classes(include_limited=include_limited))
        raise ValueError(f"Unsupported asset_class '{asset_class}'. Supported values: {supported}")

    return config["factory"]()


def get_provider_settings(asset_class: str, include_limited: bool = False) -> dict:
    """Return metadata for an asset class."""
    registry = dict(FREE_PROVIDER_REGISTRY)
    if include_limited:
        registry.update(LIMITED_PROVIDER_REGISTRY)

    config = registry.get(asset_class)
    if not config:
        supported = ", ".join(list_supported_asset_classes(include_limited=include_limited))
        raise ValueError(f"Unsupported asset_class '{asset_class}'. Supported values: {supported}")
    return dict(config)


def get_default_benchmark_symbol(asset_class: str) -> str | None:
    """Return the default benchmark symbol for the asset class."""
    config = FREE_PROVIDER_REGISTRY.get(asset_class) or LIMITED_PROVIDER_REGISTRY.get(asset_class)
    if not config:
        return None
    return config.get("default_benchmark")


__all__ = [
    "AsiaEquityProvider",
    "CryptoProvider",
    "ForexProvider",
    "USEquityProvider",
    "FREE_PROVIDER_REGISTRY",
    "LIMITED_PROVIDER_REGISTRY",
    "get_default_benchmark_symbol",
    "get_provider",
    "get_provider_settings",
    "list_supported_asset_classes",
    "normalize_asset_symbol",
]
