"""Feature pipeline — orchestrates all feature generators."""

import pandas as pd

from backend.features.technical import TechnicalFeatures
from backend.features.volatility import VolatilityFeatures


class FeaturePipeline:
    """
    Orchestrates feature generation for ML model input.

    Takes cleaned OHLCV data and produces a feature matrix
    ready for the Transformer and RL models.
    """

    def __init__(
        self,
        include_technical: bool = True,
        include_volatility: bool = True,
        include_sentiment: bool = False,  # future expansion
    ):
        self.include_technical = include_technical
        self.include_volatility = include_volatility
        self.include_sentiment = include_sentiment

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run the full feature pipeline on a single-asset DataFrame.

        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]

        Returns:
            DataFrame with all original columns + computed features
        """
        df = df.copy()

        if self.include_technical:
            df = TechnicalFeatures.add_all(df)

        if self.include_volatility:
            df = VolatilityFeatures.add_all(df)

        # Drop warmup rows where indicators are NaN
        df = self._drop_warmup(df)

        return df

    def generate_multi_asset(
        self,
        data: dict[str, pd.DataFrame],
    ) -> dict[str, pd.DataFrame]:
        """Run pipeline on multiple assets."""
        result = {}
        for symbol, df in data.items():
            try:
                result[symbol] = self.generate(df)
            except Exception as e:
                print(f"[FeaturePipeline] Error processing {symbol}: {e}")
        return result

    def get_feature_names(self) -> list[str]:
        """Return list of all feature column names generated."""
        features = ["returns", "log_returns"]

        if self.include_technical:
            features.extend([
                "rsi_14",
                "macd_line", "macd_signal", "macd_hist",
                "bb_middle", "bb_upper", "bb_lower", "bb_pctb", "bb_width",
                "atr_14", "natr_14",
                "ema_9", "ema_21", "ema_50", "ema_200",
                "vol_sma", "vol_ratio", "obv", "obv_ema",
                "roc_5", "roc_10", "roc_20", "williams_r",
                "stoch_k", "stoch_d",
            ])

        if self.include_volatility:
            features.extend([
                "rvol_5d", "rvol_10d", "rvol_21d", "rvol_63d",
                "parkinson_vol_21d", "gk_vol_21d",
                "vol_regime", "high_vol_regime", "vol_of_vol",
            ])

        return features

    @staticmethod
    def _drop_warmup(df: pd.DataFrame, min_valid_ratio: float = 0.5) -> pd.DataFrame:
        """
        Drop initial rows where too many features are NaN.
        Keeps rows where at least min_valid_ratio of feature columns are valid.
        """
        feature_cols = [c for c in df.columns if c not in [
            "timestamp", "open", "high", "low", "close",
            "volume", "adjusted_close", "symbol",
        ]]

        if not feature_cols:
            return df

        valid_counts = df[feature_cols].notna().sum(axis=1)
        threshold = len(feature_cols) * min_valid_ratio
        mask = valid_counts >= threshold

        # Find first valid row
        first_valid = mask.idxmax() if mask.any() else 0
        return df.loc[first_valid:].reset_index(drop=True)
