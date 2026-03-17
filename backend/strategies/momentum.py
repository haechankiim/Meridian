"""Momentum strategy built on EMA trend and RSI confirmation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.strategies.base import BaseStrategy, Signal, TradeSignal


class MomentumStrategy(BaseStrategy):
    """
    Long-only momentum strategy for the initial backend MVP.

    Entry:
        - fast EMA above slow EMA
        - RSI above the buy threshold
        - optional volume confirmation

    Exit:
        - fast EMA below slow EMA, or
        - RSI falls below the sell threshold
    """

    def __init__(
        self,
        fast_window: int = 9,
        slow_window: int = 21,
        buy_rsi: float = 55.0,
        sell_rsi: float = 45.0,
        min_volume_ratio: float = 0.8,
        target_weight: float = 0.15,
        strong_signal_threshold: float = 0.03,
        params: dict[str, Any] | None = None,
    ):
        merged_params = {
            "fast_window": fast_window,
            "slow_window": slow_window,
            "buy_rsi": buy_rsi,
            "sell_rsi": sell_rsi,
            "min_volume_ratio": min_volume_ratio,
            "target_weight": target_weight,
            "strong_signal_threshold": strong_signal_threshold,
        }
        if params:
            merged_params.update(params)

        super().__init__(name="momentum", params=merged_params)

        self.fast_window = int(merged_params["fast_window"])
        self.slow_window = int(merged_params["slow_window"])
        self.buy_rsi = float(merged_params["buy_rsi"])
        self.sell_rsi = float(merged_params["sell_rsi"])
        self.min_volume_ratio = float(merged_params["min_volume_ratio"])
        self.target_weight = float(merged_params["target_weight"])
        self.strong_signal_threshold = float(merged_params["strong_signal_threshold"])

    def generate_signals(
        self,
        data: pd.DataFrame,
        current_idx: int,
    ) -> dict[str, TradeSignal]:
        """Generate per-symbol signals using only data up to the current bar."""
        del current_idx

        if data.empty:
            return {}

        working = data.copy()
        if "symbol" not in working.columns:
            working["symbol"] = "asset"

        signals: dict[str, TradeSignal] = {}
        for symbol, symbol_data in working.groupby("symbol", sort=False):
            history = symbol_data.sort_index()
            if len(history) < self.slow_window:
                continue

            latest = history.iloc[-1]
            fast_ema = self._get_series_value(history, latest, f"ema_{self.fast_window}", self.fast_window)
            slow_ema = self._get_series_value(history, latest, f"ema_{self.slow_window}", self.slow_window)
            rsi = self._get_rsi(history, latest)
            volume_ratio = self._safe_float(latest.get("vol_ratio"), default=1.0)

            if fast_ema is None or slow_ema is None or rsi is None:
                continue

            momentum_gap = (fast_ema - slow_ema) / slow_ema if slow_ema else 0.0
            confidence = max(0.05, min(abs(momentum_gap) * 10, 1.0))

            if (
                fast_ema > slow_ema
                and rsi >= self.buy_rsi
                and volume_ratio >= self.min_volume_ratio
            ):
                signal_type = (
                    Signal.STRONG_BUY
                    if momentum_gap >= self.strong_signal_threshold
                    else Signal.BUY
                )
                signals[symbol] = TradeSignal(
                    signal=signal_type,
                    confidence=confidence,
                    target_weight=self.target_weight,
                    source=self.name,
                )
                continue

            if fast_ema < slow_ema or rsi <= self.sell_rsi:
                signal_type = (
                    Signal.STRONG_SELL
                    if momentum_gap <= -self.strong_signal_threshold
                    else Signal.SELL
                )
                signals[symbol] = TradeSignal(
                    signal=signal_type,
                    confidence=confidence,
                    target_weight=0.0,
                    source=self.name,
                )
                continue

            signals[symbol] = TradeSignal(
                signal=Signal.HOLD,
                confidence=confidence,
                target_weight=self.target_weight,
                source=self.name,
            )

        return signals

    def get_required_features(self) -> list[str]:
        """Return the feature set normally expected from the pipeline."""
        return [
            f"ema_{self.fast_window}",
            f"ema_{self.slow_window}",
            "rsi_14",
            "vol_ratio",
        ]

    def _get_series_value(
        self,
        history: pd.DataFrame,
        latest: pd.Series,
        column: str,
        span: int,
    ) -> float | None:
        value = self._safe_float(latest.get(column))
        if value is not None:
            return value

        if "close" not in history.columns:
            return None

        computed = history["close"].ewm(span=span, adjust=False).mean().iloc[-1]
        return self._safe_float(computed)

    def _get_rsi(self, history: pd.DataFrame, latest: pd.Series, period: int = 14) -> float | None:
        value = self._safe_float(latest.get(f"rsi_{period}"))
        if value is not None:
            return value

        if len(history) < period + 1 or "close" not in history.columns:
            return None

        delta = history["close"].diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.ewm(alpha=1 / period, min_periods=period).mean().iloc[-1]
        avg_loss = losses.ewm(alpha=1 / period, min_periods=period).mean().iloc[-1]

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return self._safe_float(100 - (100 / (1 + rs)))

    @staticmethod
    def _safe_float(value: Any, default: float | None = None) -> float | None:
        if value is None or pd.isna(value):
            return default
        return float(value)
