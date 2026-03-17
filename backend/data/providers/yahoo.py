"""Shared Yahoo Finance fetch helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import yfinance as yf


def fetch_yahoo_ohlcv(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = "1d",
    default_volume: float = 0.0,
) -> pd.DataFrame:
    """Fetch OHLCV data from Yahoo Finance with a retry fallback."""
    attempts: list[str] = []

    for name, loader in (
        (
            "download",
            lambda: yf.download(
                symbol,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=interval,
                progress=False,
                auto_adjust=False,
                actions=False,
                threads=False,
                group_by="column",
            ),
        ),
        (
            "ticker.history",
            lambda: yf.Ticker(symbol).history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=interval,
                auto_adjust=False,
                actions=False,
                repair=True,
            ),
        ),
    ):
        try:
            frame = loader()
        except Exception as exc:
            attempts.append(f"{name}: {exc}")
            continue

        if frame is None or frame.empty:
            attempts.append(f"{name}: empty")
            continue

        return normalize_yahoo_frame(frame, symbol, default_volume=default_volume)

    attempt_text = "; ".join(attempts) if attempts else "no Yahoo attempts succeeded"
    raise ValueError(f"No data returned for {symbol} ({attempt_text})")


def normalize_yahoo_frame(
    frame: pd.DataFrame,
    symbol: str,
    default_volume: float = 0.0,
) -> pd.DataFrame:
    """Normalize Yahoo Finance columns into the app's standard schema."""
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    normalized = frame.reset_index().rename(
        columns={
            "Date": "timestamp",
            "Datetime": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adjusted_close",
            "Volume": "volume",
        }
    )

    if "timestamp" not in normalized.columns:
        raise ValueError(f"Yahoo response for {symbol} did not include a timestamp column")

    if "adjusted_close" not in normalized.columns:
        normalized["adjusted_close"] = normalized["close"]

    if "volume" not in normalized.columns:
        normalized["volume"] = default_volume

    normalized["symbol"] = symbol
    return normalized
