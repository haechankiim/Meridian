"""Technical indicator features — RSI, MACD, Bollinger Bands, ATR, etc."""

import numpy as np
import pandas as pd


class TechnicalFeatures:
    """
    Computes standard technical analysis indicators.
    Uses pure pandas/numpy (no TA-Lib dependency required).

    All functions take a DataFrame with OHLCV columns and return
    the same DataFrame with new feature columns appended.
    """

    @staticmethod
    def add_all(df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical features in one call."""
        df = TechnicalFeatures.rsi(df)
        df = TechnicalFeatures.macd(df)
        df = TechnicalFeatures.bollinger_bands(df)
        df = TechnicalFeatures.atr(df)
        df = TechnicalFeatures.ema(df, periods=[9, 21, 50, 200])
        df = TechnicalFeatures.volume_profile(df)
        df = TechnicalFeatures.momentum(df)
        df = TechnicalFeatures.stochastic(df)
        return df

    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Relative Strength Index."""
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.inf)
        df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        """MACD line, signal line, and histogram."""
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

        df["macd_line"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd_line"].ewm(span=signal, adjust=False).mean()
        df["macd_hist"] = df["macd_line"] - df["macd_signal"]
        return df

    @staticmethod
    def bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> pd.DataFrame:
        """Bollinger Bands — middle, upper, lower, and %B."""
        sma = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std()

        df["bb_middle"] = sma
        df["bb_upper"] = sma + (std_dev * std)
        df["bb_lower"] = sma - (std_dev * std)
        df["bb_pctb"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
        return df

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Average True Range — volatility measure."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df[f"atr_{period}"] = true_range.rolling(window=period).mean()
        # Normalized ATR (as percentage of close)
        df[f"natr_{period}"] = df[f"atr_{period}"] / df["close"] * 100
        return df

    @staticmethod
    def ema(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
        """Exponential Moving Averages."""
        periods = periods or [9, 21, 50, 200]
        for p in periods:
            df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
        return df

    @staticmethod
    def volume_profile(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Volume-based features."""
        df["vol_sma"] = df["volume"].rolling(window=period).mean()
        df["vol_ratio"] = df["volume"] / df["vol_sma"].replace(0, np.nan)

        # On-Balance Volume
        obv = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
        df["obv"] = obv
        df["obv_ema"] = obv.ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def momentum(df: pd.DataFrame) -> pd.DataFrame:
        """Rate of change and momentum indicators."""
        for period in [5, 10, 20]:
            df[f"roc_{period}"] = df["close"].pct_change(periods=period) * 100

        # Williams %R
        period = 14
        highest_high = df["high"].rolling(window=period).max()
        lowest_low = df["low"].rolling(window=period).min()
        df["williams_r"] = -100 * (highest_high - df["close"]) / (highest_high - lowest_low)

        return df

    @staticmethod
    def stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3,
    ) -> pd.DataFrame:
        """Stochastic Oscillator (%K and %D)."""
        lowest_low = df["low"].rolling(window=k_period).min()
        highest_high = df["high"].rolling(window=k_period).max()

        df["stoch_k"] = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low)
        df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
        return df
