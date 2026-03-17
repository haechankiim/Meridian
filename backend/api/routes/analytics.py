"""API routes for backtest analytics and risk inspection."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import Backtest, BacktestResult as BacktestResultRecord, get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class MonthlyReturnPoint(BaseModel):
    month: str
    return_value: float


class RiskDrawdownPoint(BaseModel):
    timestamp: str
    drawdown: float


class RiskAnalyticsResponse(BaseModel):
    backtest_id: int
    status: str
    strategy_name: str
    symbols: list[str]
    created_at: str
    latest_equity: float
    peak_equity: float
    trough_equity: float
    latest_drawdown: float
    max_drawdown: float
    volatility: float
    var_95: float
    cvar_95: float
    alpha: float
    beta: float
    information_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    observation_count: int
    risk_regime: str
    monthly_returns: list[MonthlyReturnPoint]
    drawdown_curve: list[RiskDrawdownPoint]


@router.get("/risk/{backtest_id}", response_model=RiskAnalyticsResponse)
async def get_risk_analytics(
    backtest_id: int,
    db: AsyncSession = Depends(get_db),
) -> RiskAnalyticsResponse:
    try:
        return await _get_risk_analytics_payload(db, backtest_id)
    except SQLAlchemyError as exc:
        logger.exception("Unable to load risk analytics for id=%s", backtest_id)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


async def _get_risk_analytics_payload(
    db: AsyncSession,
    backtest_id: int,
) -> RiskAnalyticsResponse:
    backtest_stmt = select(Backtest).where(Backtest.id == backtest_id)
    backtest_row = (await db.execute(backtest_stmt)).scalar_one_or_none()
    if backtest_row is None:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

    result_stmt = select(BacktestResultRecord).where(BacktestResultRecord.backtest_id == backtest_id)
    result_row = (await db.execute(result_stmt)).scalar_one_or_none()
    if result_row is None:
        raise HTTPException(status_code=202, detail=f"Backtest {backtest_id} results are not ready")

    equity_payload = list(result_row.equity_curve or [])
    equity_series = _equity_series_from_payload(equity_payload)
    drawdown_curve = _drawdown_curve_from_series(equity_series)

    latest_equity = float(equity_series.iloc[-1]) if not equity_series.empty else float(backtest_row.initial_capital)
    peak_equity = float(equity_series.max()) if not equity_series.empty else latest_equity
    trough_equity = float(equity_series.min()) if not equity_series.empty else latest_equity
    latest_drawdown = drawdown_curve[-1].drawdown if drawdown_curve else 0.0

    return RiskAnalyticsResponse(
        backtest_id=int(backtest_row.id),
        status=str(backtest_row.status),
        strategy_name=str(backtest_row.strategy_name),
        symbols=list(backtest_row.symbols or []),
        created_at=backtest_row.created_at.isoformat() if backtest_row.created_at else "",
        latest_equity=latest_equity,
        peak_equity=peak_equity,
        trough_equity=trough_equity,
        latest_drawdown=latest_drawdown,
        max_drawdown=float(result_row.max_drawdown or 0.0),
        volatility=float(result_row.volatility or 0.0),
        var_95=float(result_row.var_95 or 0.0),
        cvar_95=float(result_row.cvar_95 or 0.0),
        alpha=float(result_row.alpha or 0.0),
        beta=float(result_row.beta or 0.0),
        information_ratio=float(result_row.information_ratio or 0.0),
        win_rate=float(result_row.win_rate or 0.0),
        profit_factor=float(result_row.profit_factor or 0.0),
        total_trades=int(result_row.total_trades or 0),
        observation_count=len(equity_payload),
        risk_regime=_risk_regime(
            max_drawdown=float(result_row.max_drawdown or 0.0),
            var_95=float(result_row.var_95 or 0.0),
            volatility=float(result_row.volatility or 0.0),
        ),
        monthly_returns=[
            MonthlyReturnPoint(
                month=str(item.get("month", "")),
                return_value=float(item.get("return", 0.0)),
            )
            for item in list(result_row.monthly_returns or [])
        ],
        drawdown_curve=drawdown_curve,
    )


def _equity_series_from_payload(payload: list[dict[str, Any]]) -> pd.Series:
    if not payload:
        return pd.Series(dtype=float, name="equity")
    return pd.Series(
        [float(item["equity"]) for item in payload],
        index=pd.to_datetime([item["timestamp"] for item in payload]),
        name="equity",
    )


def _drawdown_curve_from_series(equity_series: pd.Series) -> list[RiskDrawdownPoint]:
    if equity_series.empty:
        return []

    cumulative = equity_series / equity_series.iloc[0]
    drawdown = (cumulative / cumulative.cummax()) - 1

    return [
        RiskDrawdownPoint(
            timestamp=pd.Timestamp(timestamp).isoformat(),
            drawdown=float(value),
        )
        for timestamp, value in drawdown.items()
    ]


def _risk_regime(max_drawdown: float, var_95: float, volatility: float) -> str:
    if max_drawdown <= -0.20 or var_95 <= -0.03 or volatility >= 0.35:
        return "elevated"
    if max_drawdown <= -0.10 or var_95 <= -0.015 or volatility >= 0.18:
        return "watch"
    return "controlled"
