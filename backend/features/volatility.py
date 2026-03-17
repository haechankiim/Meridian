"""Volatility features — realized vol, rolling metrics, vol regime detection."""

import numpy as np
import pandas as pd


class VolatilityFeatures:
    """
    Volatility-based features for ML input.
    These are critical for risk management and position sizing.
    """

    @staticmethod
    def add_all(df: pd.DataFrame) -> pd.DataFrame:
        """Add all volatility features."""
        df = VolatilityFeatures.realized_volatility(df)
        df = VolatilityFeatures.parkinson_volatility(df)
        df = VolatilityFeatures.garman_klass(df)
        df = VolatilityFeatures.vol_regime(df)
        df = VolatilityFeatures.vol_of_vol(df)
        return df

    @staticmethod
    def realized_volatility(
        df: pd.DataFrame,
        windows: list[int] = None,
    ) -> pd.DataFrame:
        """
        Annualized realized volatility from close-to-close returns.
        Standard measure used across all asset classes.
        """
        windows = windows or [5, 10, 21, 63]  # 1w, 2w, 1m, 3m
        annualization = np.sqrt(252)

        log_ret = np.log(df["close"] / df["close"].shift(1))

        for w in windows:
            df[f"rvol_{w}d"] = log_ret.rolling(window=w).std() * annualization

        return df

    @staticmethod
    def parkinson_volatility(df: pd.DataFrame, window: int = 21) -> pd.DataFrame:
        """
        Parkinson estimator — uses high-low range.
        More efficient than close-to-close when intraday data exists.
        """
        log_hl = np.log(df["high"] / df["low"])
        factor = 1 / (4 * np.log(2))
        parkinsons = np.sqrt(factor * (log_hl ** 2).rolling(window=window).mean())
        df[f"parkinson_vol_{window}d"] = parkinsons * np.sqrt(252)
        return df

    @staticmethod
    def garman_klass(df: pd.DataFrame, window: int = 21) -> pd.DataFrame:
        """
        Garman-Klass estimator — uses OHLC data.
        Most efficient estimator for daily data.
        """
        log_hl = np.log(df["high"] / df["low"])
        log_co = np.log(df["close"] / df["open"])

        gk = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_co ** 2
        df[f"gk_vol_{window}d"] = np.sqrt(gk.rolling(window=window).mean() * 252)
        return df

    @staticmethod
    def vol_regime(
        df: pd.DataFrame,
        short_window: int = 10,
        long_window: int = 63,
    ) -> pd.DataFrame:
        """
        Volatility regime indicator.
        Ratio of short-term to long-term vol — high = vol expanding.

        > 1.0 = volatility expanding (risk-off signal)
        < 1.0 = volatility contracting (risk-on signal)
        """
        log_ret = np.log(df["close"] / df["close"].shift(1))
        short_vol = log_ret.rolling(window=short_window).std()
        long_vol = log_ret.rolling(window=long_window).std()

        df["vol_regime"] = short_vol / long_vol.replace(0, np.nan)

        # Binary regime classification
        df["high_vol_regime"] = (df["vol_regime"] > 1.2).astype(int)

        return df

    @staticmethod
    def vol_of_vol(df: pd.DataFrame, window: int = 21) -> pd.DataFrame:
        """
        Volatility of volatility — measures vol clustering.
        High vol-of-vol suggests unstable market conditions.
        """
        if f"rvol_{window}d" not in df.columns:
            df = VolatilityFeatures.realized_volatility(df, [window])

        df["vol_of_vol"] = df[f"rvol_{window}d"].rolling(window=window).std()
        return df
