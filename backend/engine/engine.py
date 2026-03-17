"""Event-driven backtesting engine."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.app.config import get_settings
from backend.engine.broker import SimulatedBroker
from backend.engine.metrics import compute_metrics, PerformanceMetrics
from backend.engine.portfolio import Portfolio
from backend.engine.risk import RiskConfig, RiskManager
from backend.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""
    initial_capital: float = 100_000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005
    risk: RiskConfig = field(default_factory=RiskConfig)
    warmup_bars: int = 0  # skip first N bars before trading (feature warmup)


@dataclass
class BacktestResult:
    """Full results from a completed backtest."""
    metrics: PerformanceMetrics
    equity_curve: pd.Series
    drawdown_series: pd.Series
    trades: pd.DataFrame
    strategy_name: str
    symbols: list[str]
    start_date: datetime
    end_date: datetime
    config: BacktestConfig


class BacktestEngine:
    """
    Event-driven backtesting engine.

    Loop for each bar t:
        1. Mark portfolio to market at close[t]
        2. Skip if still in warmup period
        3. Check risk limits — halt if drawdown breached
        4. Call strategy.generate_signals(data_up_to_t, t)
        5. For each signal → RiskManager.size_order()
        6. Execute valid orders via SimulatedBroker
        7. Apply fills to Portfolio

    No look-ahead bias: strategy receives only data.loc[:current_timestamp].
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        if config is None:
            s = get_settings()
            config = BacktestConfig(
                initial_capital=s.initial_capital,
                commission_rate=s.commission_rate,
                slippage_rate=s.slippage_rate,
            )
        self.config = config

    def run(
        self,
        data: dict[str, pd.DataFrame],
        strategy: BaseStrategy,
        benchmark: Optional[pd.Series] = None,
    ) -> BacktestResult:
        """
        Run a backtest.

        Args:
            data: Dict mapping symbol → DataFrame with a DatetimeIndex (sorted
                  ascending) and columns [open, high, low, close, volume] plus
                  any feature columns produced by FeaturePipeline.
            strategy: Any BaseStrategy implementation.
            benchmark: Optional equity/price series for alpha/beta calculation.

        Returns:
            BacktestResult with metrics, equity curve, and trade log.
        """
        cfg = self.config
        broker = SimulatedBroker(cfg.commission_rate, cfg.slippage_rate)
        portfolio = Portfolio(cfg.initial_capital)
        risk = RiskManager(cfg.risk)
        symbols = list(data.keys())

        # ── Build aligned timeline (intersection of all assets) ──────────────
        all_timestamps: Optional[set] = None
        for df in data.values():
            ts_set = set(df.index)
            all_timestamps = ts_set if all_timestamps is None else all_timestamps & ts_set

        timestamps = sorted(all_timestamps)  # type: ignore[arg-type]

        if not timestamps:
            raise ValueError("No overlapping timestamps across provided assets.")

        # Reindex all assets onto the shared timeline
        aligned: dict[str, pd.DataFrame] = {
            sym: df.reindex(timestamps) for sym, df in data.items()
        }

        # Pre-build combined DataFrame once (all assets, all bars)
        # Shape: (n_symbols * T, n_features + 1), DatetimeIndex with duplicates
        full_combined = pd.concat(
            [df.assign(symbol=sym) for sym, df in aligned.items()]
        ).sort_index()

        start_date = _to_datetime(timestamps[cfg.warmup_bars] if cfg.warmup_bars < len(timestamps) else timestamps[0])
        end_date = _to_datetime(timestamps[-1])

        logger.info(
            "[Backtest] %s | %d symbols | %d bars | %s → %s",
            strategy.name, len(symbols), len(timestamps),
            start_date.date(), end_date.date(),
        )

        # ── Main loop ────────────────────────────────────────────────────────
        for t, ts in enumerate(timestamps):
            ts_dt = _to_datetime(ts)

            # Build price snapshot and bar data for this step
            prices: dict[str, float] = {}
            bars: dict[str, dict] = {}
            for sym in symbols:
                row = aligned[sym].loc[ts]
                close = row.get("close")
                if close is None or pd.isna(close):
                    continue
                prices[sym] = float(close)
                bars[sym] = {
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": float(close),
                    "volume": float(row.get("volume") or 0.0),
                    "timestamp": ts_dt,
                }

            # Mark to market (always, including warmup)
            portfolio.mark_to_market(prices, ts_dt)

            # Skip warmup bars
            if t < cfg.warmup_bars:
                continue

            # Check risk limits
            if not risk.check_drawdown(portfolio):
                logger.warning("[Backtest] Drawdown limit hit at %s — trading halted.", ts_dt.date())
                break

            # Slice combined DataFrame up to current timestamp (no look-ahead)
            current_data = full_combined.loc[:ts]

            # Generate signals
            try:
                signals = strategy.generate_signals(current_data, t)
            except Exception as exc:
                logger.error("[Backtest] Strategy error at %s: %s", ts_dt.date(), exc)
                continue

            # Execute signals
            for sym, signal in signals.items():
                if sym not in prices:
                    continue
                order = risk.size_order(sym, signal, portfolio, prices)
                if order is None:
                    continue
                bar = bars.get(sym)
                if bar is None:
                    continue
                fill = broker.execute(order, bar)
                if fill:
                    portfolio.apply_fill(fill)

        # ── Compute results ──────────────────────────────────────────────────
        equity_series = pd.Series(
            [e["equity"] for e in portfolio.equity_curve],
            index=[e["timestamp"] for e in portfolio.equity_curve],
            name="equity",
        )

        trades_df = pd.DataFrame(portfolio.trade_log)
        if not trades_df.empty and "timestamp" in trades_df.columns:
            trades_df = trades_df.sort_values("timestamp").reset_index(drop=True)

        metrics = compute_metrics(
            equity_curve=equity_series,
            benchmark=benchmark,
            trades=trades_df if not trades_df.empty else None,
        )

        if equity_series.empty or float(equity_series.iloc[0]) <= 0:
            drawdown_series = pd.Series(0.0, index=equity_series.index, name="drawdown")
        else:
            cumulative = equity_series / equity_series.iloc[0]
            drawdown_series = (cumulative / cumulative.cummax()) - 1

        logger.info(
            "[Backtest] Done — Return: %.1f%%  Sharpe: %.2f  MaxDD: %.1f%%  Trades: %d",
            metrics.total_return * 100,
            metrics.sharpe_ratio,
            metrics.max_drawdown * 100,
            metrics.total_trades,
        )

        return BacktestResult(
            metrics=metrics,
            equity_curve=equity_series,
            drawdown_series=drawdown_series,
            trades=trades_df,
            strategy_name=strategy.name,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            config=cfg,
        )


def _to_datetime(ts) -> datetime:
    """Normalise a numpy/pandas timestamp to a plain Python datetime."""
    if isinstance(ts, datetime):
        return ts
    return pd.Timestamp(ts).to_pydatetime()
