"""OHLCV data cleaner — normalization, validation, and gap filling."""

from typing import Optional

import numpy as np
import pandas as pd


class DataCleaner:
    """
    Cleans and normalizes raw OHLCV data from any provider
    into a consistent format for the feature engine and backtester.
    """

    @staticmethod
    def clean(
        df: pd.DataFrame,
        fill_gaps: bool = True,
        remove_outliers: bool = True,
        outlier_std: float = 5.0,
    ) -> pd.DataFrame:
        """
        Full cleaning pipeline.

        Steps:
            1. Ensure correct dtypes
            2. Remove duplicates
            3. Sort by timestamp
            4. Handle missing values
            5. Fill calendar gaps (weekdays for equities)
            6. Remove statistical outliers
            7. Add derived columns (returns, log_returns)
        """
        df = df.copy()

        # 1. Dtypes
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 2. Remove exact duplicates
        df = df.drop_duplicates(subset=["timestamp"], keep="last")

        # 3. Sort
        df = df.sort_values("timestamp").reset_index(drop=True)

        # 4. Handle NaN
        df = DataCleaner._handle_missing(df)

        # 5. Fill gaps
        if fill_gaps:
            df = DataCleaner._fill_gaps(df)

        # 6. Outlier removal
        if remove_outliers:
            df = DataCleaner._remove_outliers(df, std_threshold=outlier_std)

        # 7. Derived columns
        df = DataCleaner._add_returns(df)

        return df

    @staticmethod
    def _handle_missing(df: pd.DataFrame) -> pd.DataFrame:
        """Forward-fill price data, zero-fill volume."""
        price_cols = ["open", "high", "low", "close", "adjusted_close"]
        existing_price_cols = [c for c in price_cols if c in df.columns]

        df[existing_price_cols] = df[existing_price_cols].ffill()
        df["volume"] = df["volume"].fillna(0)

        # Drop any remaining rows where close is NaN (start of series)
        df = df.dropna(subset=["close"])

        return df

    @staticmethod
    def _fill_gaps(df: pd.DataFrame) -> pd.DataFrame:
        """
        Fill missing calendar days.
        Uses forward-fill for prices, 0 for volume on gap days.
        """
        if df.empty:
            return df

        df = df.set_index("timestamp")
        full_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq="B")
        df = df.reindex(full_range)

        price_cols = ["open", "high", "low", "close", "adjusted_close"]
        existing = [c for c in price_cols if c in df.columns]
        df[existing] = df[existing].ffill()
        df["volume"] = df["volume"].fillna(0)

        # Forward-fill symbol
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].ffill()

        df = df.reset_index().rename(columns={"index": "timestamp"})
        return df

    @staticmethod
    def _remove_outliers(
        df: pd.DataFrame,
        std_threshold: float = 5.0,
    ) -> pd.DataFrame:
        """
        Remove rows where single-bar return exceeds threshold * std.
        This catches data errors (splits not adjusted, glitches).
        """
        if len(df) < 10:
            return df

        returns = df["close"].pct_change()
        mean_ret = returns.mean()
        std_ret = returns.std()

        if std_ret == 0:
            return df

        z_scores = (returns - mean_ret).abs() / std_ret
        mask = z_scores <= std_threshold
        mask.iloc[0] = True  # keep first row

        removed = (~mask).sum()
        if removed > 0:
            print(f"[Cleaner] Removed {removed} outlier rows (>{std_threshold}σ)")

        return df[mask].reset_index(drop=True)

    @staticmethod
    def _add_returns(df: pd.DataFrame) -> pd.DataFrame:
        """Add simple and log return columns."""
        df["returns"] = df["close"].pct_change()
        df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
        return df

    @staticmethod
    def normalize_multi_asset(
        data: dict[str, pd.DataFrame],
        align_dates: bool = True,
    ) -> pd.DataFrame:
        """
        Combine multiple single-asset DataFrames into one multi-asset DataFrame.
        Aligns on common trading dates if requested.
        """
        frames = []
        for symbol, df in data.items():
            df = df.copy()
            if "symbol" not in df.columns:
                df["symbol"] = symbol
            frames.append(df)

        combined = pd.concat(frames, ignore_index=True)

        if align_dates:
            # Keep only dates where all assets have data
            date_counts = combined.groupby("timestamp")["symbol"].nunique()
            n_assets = combined["symbol"].nunique()
            valid_dates = date_counts[date_counts == n_assets].index
            combined = combined[combined["timestamp"].isin(valid_dates)]

        return combined.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
