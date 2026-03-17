"""Performance metrics — Sharpe, Sortino, alpha, beta, drawdown, etc."""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class PerformanceMetrics:
    """Complete set of backtest performance metrics."""
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    alpha: float
    beta: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_duration_days: float
    volatility: float
    var_95: float
    cvar_95: float
    information_ratio: float


def compute_metrics(
    equity_curve: pd.Series,
    benchmark: Optional[pd.Series] = None,
    trades: Optional[pd.DataFrame] = None,
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> PerformanceMetrics:
    """
    Compute comprehensive performance metrics from an equity curve.

    Args:
        equity_curve: Series of portfolio values indexed by timestamp
        benchmark: Optional benchmark equity curve for alpha/beta
        trades: Optional DataFrame of trades for win rate, profit factor
        risk_free_rate: Annual risk-free rate (default 5%)
        periods_per_year: Trading periods per year (252 for daily)
    """
    if equity_curve.empty:
        return PerformanceMetrics(
            total_return=0.0,
            annualized_return=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            calmar_ratio=0.0,
            alpha=0.0,
            beta=1.0,
            win_rate=0.0,
            profit_factor=0.0,
            total_trades=0,
            avg_trade_duration_days=0.0,
            volatility=0.0,
            var_95=0.0,
            cvar_95=0.0,
            information_ratio=0.0,
        )

    starting_equity = float(equity_curve.iloc[0])
    returns = equity_curve.pct_change().dropna()
    rf_daily = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    excess = returns - rf_daily

    # ── Return metrics ─────────────────────────────────
    total_return = ((equity_curve.iloc[-1] / starting_equity) - 1) if starting_equity > 0 else 0.0

    n_periods = len(returns)
    annualized_return = (
        (1 + total_return) ** (periods_per_year / n_periods) - 1
        if n_periods > 0
        else 0.0
    )

    # ── Risk metrics ───────────────────────────────────
    volatility = returns.std() * np.sqrt(periods_per_year)

    sharpe = (excess.mean() / excess.std() * np.sqrt(periods_per_year)
              if excess.std() > 0 else 0.0)

    downside = returns[returns < rf_daily]
    downside_std = downside.std() * np.sqrt(periods_per_year) if len(downside) > 0 else 0.0
    sortino = ((returns.mean() - rf_daily) * periods_per_year / downside_std
               if downside_std > 0 else 0.0)

    # ── Drawdown ───────────────────────────────────────
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative / running_max) - 1
    max_drawdown = drawdown.min() if not drawdown.empty else 0.0

    calmar = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0.0

    # ── VaR / CVaR ─────────────────────────────────────
    var_95 = returns.quantile(0.05) if not returns.empty else 0.0
    cvar_95 = (
        returns[returns <= var_95].mean()
        if not returns.empty and (returns <= var_95).any()
        else var_95
    )

    # ── Alpha / Beta ───────────────────────────────────
    if benchmark is not None and len(benchmark) > 1:
        bench_returns = benchmark.pct_change().dropna()

        # Align dates
        common = returns.index.intersection(bench_returns.index)
        r = returns.loc[common]
        b = bench_returns.loc[common]

        if len(r) > 1:
            cov = np.cov(r, b)
            beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 0.0
            alpha = (r.mean() - rf_daily - beta * (b.mean() - rf_daily)) * periods_per_year

            tracking_error = (r - b).std() * np.sqrt(periods_per_year)
            information_ratio = ((r.mean() - b.mean()) * periods_per_year / tracking_error
                                 if tracking_error > 0 else 0.0)
        else:
            alpha, beta, information_ratio = 0.0, 0.0, 0.0
    else:
        alpha, beta, information_ratio = 0.0, 1.0, 0.0

    # ── Trade metrics ──────────────────────────────────
    if trades is not None and not trades.empty and "pnl" in trades.columns:
        winning = trades[trades["pnl"] > 0]
        losing = trades[trades["pnl"] < 0]

        total_trades = len(trades)
        win_rate = len(winning) / total_trades if total_trades > 0 else 0.0

        gross_profit = winning["pnl"].sum() if len(winning) > 0 else 0.0
        gross_loss = abs(losing["pnl"].sum()) if len(losing) > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        if "duration_days" in trades.columns:
            avg_duration = trades["duration_days"].mean()
        else:
            avg_duration = 0.0
    else:
        total_trades = 0
        win_rate = 0.0
        profit_factor = 0.0
        avg_duration = 0.0

    return PerformanceMetrics(
        total_return=_safe_round(total_return, 6),
        annualized_return=_safe_round(annualized_return, 6),
        sharpe_ratio=_safe_round(sharpe, 4),
        sortino_ratio=_safe_round(sortino, 4),
        max_drawdown=_safe_round(max_drawdown, 6),
        calmar_ratio=_safe_round(calmar, 4),
        alpha=_safe_round(alpha, 6),
        beta=_safe_round(beta, 4, default=1.0),
        win_rate=_safe_round(win_rate, 4),
        profit_factor=_safe_round(profit_factor, 4),
        total_trades=total_trades,
        avg_trade_duration_days=_safe_round(avg_duration, 2),
        volatility=_safe_round(volatility, 6),
        var_95=_safe_round(var_95, 6),
        cvar_95=_safe_round(cvar_95, 6),
        information_ratio=_safe_round(information_ratio, 4),
    )


def _safe_round(value: float, digits: int, default: float = 0.0) -> float:
    if pd.isna(value) or not np.isfinite(value):
        return default
    return round(float(value), digits)
