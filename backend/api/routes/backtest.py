"""API routes for running backtests."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import (
    Asset,
    AssetClass,
    Backtest,
    BacktestResult as BacktestResultRecord,
    OrderSide,
    OrderType,
    Trade,
    get_db,
)
from backend.data.providers import get_default_benchmark_symbol, get_provider, normalize_asset_symbol
from backend.engine import BacktestConfig, BacktestEngine, compute_metrics
from backend.features.pipeline import FeaturePipeline
from backend.strategies.momentum import MomentumStrategy

logger = logging.getLogger(__name__)

router = APIRouter()


class BacktestRequest(BaseModel):
    """Payload used to trigger a synchronous MVP backtest."""

    symbols: list[str] = Field(min_length=1)
    asset_class: str = "us_equity"
    strategy: str = "momentum"
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100_000.0, ge=0)
    interval: str = "1d"
    benchmark_symbol: str | None = None
    save_results: bool = True
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class MetricsResponse(BaseModel):
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


class EquityCurvePoint(BaseModel):
    timestamp: str
    equity: float


class DrawdownPoint(BaseModel):
    timestamp: str
    drawdown: float


class TradeResponse(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    slippage: float
    timestamp: str
    pnl: float
    signal_source: str
    signal_confidence: float


class BacktestResponse(BaseModel):
    backtest_id: int | None = None
    persisted: bool = False
    persistence_error: str | None = None
    status: str = "completed"
    created_at: str | None = None
    metrics: MetricsResponse
    equity_curve: list[EquityCurvePoint]
    drawdown_curve: list[DrawdownPoint]
    trades: list[TradeResponse]
    strategy_name: str
    symbols: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class BacktestStatusResponse(BaseModel):
    backtest_id: int
    status: str
    strategy_name: str
    asset_class: str | None = None
    symbols: list[str]
    start_date: str
    end_date: str
    created_at: str
    initial_capital: float
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class RecentBacktestSummary(BaseModel):
    backtest_id: int
    status: str
    strategy_name: str
    asset_class: str | None = None
    symbols: list[str]
    start_date: str
    end_date: str
    created_at: str
    initial_capital: float
    total_return: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    total_trades: int | None = None
    persisted: bool = False


class RecentBacktestsResponse(BaseModel):
    items: list[RecentBacktestSummary]


class BacktestDeleteResponse(BaseModel):
    backtest_id: int
    deleted: bool


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(
    request: BacktestRequest,
    db: AsyncSession = Depends(get_db),
) -> BacktestResponse:
    """Run a basic US equities backtest using the existing engine stack."""
    if request.start_date >= request.end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    try:
        normalized_symbols = [
            normalize_asset_symbol(request.asset_class, symbol)
            for symbol in request.symbols
        ]
        benchmark_symbol = (
            normalize_asset_symbol(request.asset_class, request.benchmark_symbol)
            if request.benchmark_symbol
            else get_default_benchmark_symbol(request.asset_class)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    strategy = _get_strategy(request.strategy, request.strategy_params)
    provider = _get_data_provider(request.asset_class)

    start = datetime.combine(request.start_date, time.min)
    end = datetime.combine(request.end_date, time.min)

    try:
        raw_data = await provider.fetch_batch(
            normalized_symbols,
            start,
            end,
            request.interval,
        )
    except Exception as exc:
        logger.exception("Failed to fetch market data for backtest request")
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}") from exc

    if not raw_data:
        raise HTTPException(
            status_code=404,
            detail="No data available for the requested symbols and date range",
        )

    pipeline = FeaturePipeline()
    prepared_data = {
        symbol: frame.set_index("timestamp")
        for symbol, frame in pipeline.generate_multi_asset(raw_data).items()
        if not frame.empty
    }

    if not prepared_data:
        raise HTTPException(
            status_code=400,
            detail="Unable to generate usable features for the requested backtest window",
        )

    benchmark = await _get_benchmark_series(
        provider=provider,
        benchmark_symbol=benchmark_symbol,
        start=start,
        end=end,
        interval=request.interval,
    )

    engine = BacktestEngine(
        BacktestConfig(initial_capital=request.initial_capital),
    )

    try:
        result = engine.run(
            data=prepared_data,
            strategy=strategy,
            benchmark=benchmark,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    trades = result.trades.to_dict(orient="records") if not result.trades.empty else []
    persistence = {
        "backtest_id": None,
        "persisted": False,
        "persistence_error": None,
        "status": "completed",
        "created_at": None,
    }

    if request.save_results:
        try:
            persistence = await _persist_backtest_run(
                db=db,
                request=request,
                result=result,
                trades=trades,
            )
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.exception("Backtest completed but could not be persisted")
            persistence["persistence_error"] = str(exc)

    return BacktestResponse(
        backtest_id=persistence["backtest_id"],
        persisted=persistence["persisted"],
        persistence_error=persistence["persistence_error"],
        status=persistence["status"],
        created_at=persistence["created_at"],
        metrics=MetricsResponse(**result.metrics.__dict__),
        equity_curve=[
            EquityCurvePoint(timestamp=_serialize_timestamp(ts), equity=float(value))
            for ts, value in result.equity_curve.items()
        ],
        drawdown_curve=[
            DrawdownPoint(timestamp=_serialize_timestamp(ts), drawdown=float(value))
            for ts, value in result.drawdown_series.items()
        ],
        trades=[
            TradeResponse(
                symbol=str(trade["symbol"]),
                side=str(trade["side"]),
                quantity=float(trade["quantity"]),
                price=float(trade["price"]),
                commission=float(trade["commission"]),
                slippage=float(trade["slippage"]),
                timestamp=_serialize_timestamp(trade["timestamp"]),
                pnl=float(trade["pnl"]),
                signal_source=str(trade.get("signal_source", "")),
                signal_confidence=float(trade.get("signal_confidence", 0.0)),
            )
            for trade in trades
        ],
        strategy_name=result.strategy_name,
        symbols=result.symbols,
        start_date=result.start_date.date().isoformat(),
        end_date=result.end_date.date().isoformat(),
        initial_capital=result.config.initial_capital,
        strategy_params=request.strategy_params,
    )


@router.get("/recent", response_model=RecentBacktestsResponse)
async def list_recent_backtests(
    limit: int = Query(default=8, ge=1, le=50),
    asset_class: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RecentBacktestsResponse:
    if asset_class:
        try:
            AssetClass(asset_class)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return await _list_recent_backtests_payload(db, limit=limit, asset_class=asset_class)
    except SQLAlchemyError as exc:
        logger.exception("Unable to load recent backtests")
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@router.delete("/{backtest_id}", response_model=BacktestDeleteResponse)
async def delete_backtest(
    backtest_id: int,
    db: AsyncSession = Depends(get_db),
) -> BacktestDeleteResponse:
    try:
        stmt = select(Backtest.id).where(Backtest.id == backtest_id)
        existing_id = (await db.execute(stmt)).scalar_one_or_none()
        if existing_id is None:
            raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

        await db.execute(delete(Trade).where(Trade.backtest_id == backtest_id))
        await db.execute(delete(BacktestResultRecord).where(BacktestResultRecord.backtest_id == backtest_id))
        await db.execute(delete(Backtest).where(Backtest.id == backtest_id))
        await db.commit()
        return BacktestDeleteResponse(backtest_id=backtest_id, deleted=True)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Unable to delete backtest id=%s", backtest_id)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@router.get("/{backtest_id}/status", response_model=BacktestStatusResponse)
async def get_backtest_status(
    backtest_id: int,
    db: AsyncSession = Depends(get_db),
) -> BacktestStatusResponse:
    try:
        return await _get_backtest_status_payload(db, backtest_id)
    except SQLAlchemyError as exc:
        logger.exception("Unable to load backtest status for id=%s", backtest_id)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@router.get("/{backtest_id}/results", response_model=BacktestResponse)
async def get_backtest_results(
    backtest_id: int,
    db: AsyncSession = Depends(get_db),
) -> BacktestResponse:
    try:
        return await _get_backtest_results_payload(db, backtest_id)
    except SQLAlchemyError as exc:
        logger.exception("Unable to load backtest results for id=%s", backtest_id)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


def _get_strategy(strategy_name: str, strategy_params: dict[str, Any]) -> MomentumStrategy:
    if strategy_name != "momentum":
        raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy_name}")
    return MomentumStrategy(**strategy_params)


def _get_data_provider(asset_class: str):
    try:
        return get_provider(asset_class)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _get_benchmark_series(
    provider,
    benchmark_symbol: str | None,
    start: datetime,
    end: datetime,
    interval: str,
) -> pd.Series | None:
    if not benchmark_symbol:
        return None

    try:
        benchmark_df = await provider.fetch_historical(benchmark_symbol, start, end, interval)
    except Exception as exc:
        logger.warning("Benchmark fetch skipped for %s: %s", benchmark_symbol, exc)
        return None

    if benchmark_df.empty:
        return None

    return benchmark_df.set_index("timestamp")["close"]


async def _persist_backtest_run(
    db: AsyncSession,
    request: BacktestRequest,
    result,
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    asset_class = AssetClass(request.asset_class)
    created_at = datetime.utcnow()

    backtest_row = Backtest(
        name=_build_backtest_name(request, created_at),
        strategy_name=result.strategy_name,
        asset_class=asset_class,
        symbols=result.symbols,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=result.config.initial_capital,
        parameters=request.strategy_params,
        status="done",
        created_at=created_at,
    )
    db.add(backtest_row)
    await db.flush()

    asset_map = await _ensure_assets(db, result.symbols, asset_class)
    equity_curve_payload = _equity_curve_payload(result.equity_curve)

    db.add(
        BacktestResultRecord(
            backtest_id=int(backtest_row.id),
            total_return=result.metrics.total_return,
            annualized_return=result.metrics.annualized_return,
            sharpe_ratio=result.metrics.sharpe_ratio,
            sortino_ratio=result.metrics.sortino_ratio,
            max_drawdown=result.metrics.max_drawdown,
            calmar_ratio=result.metrics.calmar_ratio,
            alpha=result.metrics.alpha,
            beta=result.metrics.beta,
            win_rate=result.metrics.win_rate,
            profit_factor=result.metrics.profit_factor,
            total_trades=result.metrics.total_trades,
            avg_trade_duration=result.metrics.avg_trade_duration_days,
            volatility=result.metrics.volatility,
            var_95=result.metrics.var_95,
            cvar_95=result.metrics.cvar_95,
            information_ratio=result.metrics.information_ratio,
            equity_curve=equity_curve_payload,
            monthly_returns=_monthly_returns_payload(result.equity_curve),
        )
    )

    for trade in trades:
        symbol = str(trade["symbol"])
        asset_id = asset_map.get(symbol)
        if asset_id is None:
            continue

        db.add(
            Trade(
                backtest_id=int(backtest_row.id),
                asset_id=asset_id,
                side=OrderSide(str(trade["side"])),
                order_type=OrderType.MARKET,
                quantity=float(trade["quantity"]),
                price=float(trade["price"]),
                commission=float(trade["commission"]),
                slippage=float(trade["slippage"]),
                timestamp=pd.Timestamp(trade["timestamp"]).to_pydatetime(),
                signal_source=str(trade.get("signal_source", "")),
                signal_confidence=float(trade.get("signal_confidence", 0.0)),
                pnl=float(trade.get("pnl", 0.0)),
            )
        )

    await db.commit()

    return {
        "backtest_id": int(backtest_row.id),
        "persisted": True,
        "persistence_error": None,
        "status": "done",
        "created_at": created_at.isoformat(),
    }


async def _ensure_assets(
    db: AsyncSession,
    symbols: list[str],
    asset_class: AssetClass,
) -> dict[str, int]:
    stmt = select(Asset).where(
        Asset.asset_class == asset_class,
        Asset.symbol.in_(symbols),
    )
    rows = (await db.execute(stmt)).scalars().all()
    asset_map = {asset.symbol: int(asset.id) for asset in rows}

    missing_symbols = [symbol for symbol in symbols if symbol not in asset_map]
    for symbol in missing_symbols:
        asset = Asset(
            symbol=symbol,
            name=symbol,
            asset_class=asset_class,
            currency=_default_currency(asset_class),
        )
        db.add(asset)
        await db.flush()
        asset_map[symbol] = int(asset.id)

    return asset_map


async def _get_backtest_status_payload(
    db: AsyncSession,
    backtest_id: int,
) -> BacktestStatusResponse:
    stmt = select(Backtest).where(Backtest.id == backtest_id)
    backtest_row = (await db.execute(stmt)).scalar_one_or_none()
    if backtest_row is None:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

    asset_class = backtest_row.asset_class.value if backtest_row.asset_class else None
    return BacktestStatusResponse(
        backtest_id=int(backtest_row.id),
        status=str(backtest_row.status),
        strategy_name=str(backtest_row.strategy_name),
        asset_class=asset_class,
        symbols=list(backtest_row.symbols or []),
        start_date=backtest_row.start_date.date().isoformat(),
        end_date=backtest_row.end_date.date().isoformat(),
        created_at=backtest_row.created_at.isoformat() if backtest_row.created_at else "",
        initial_capital=float(backtest_row.initial_capital),
        strategy_params=dict(backtest_row.parameters or {}),
    )


async def _list_recent_backtests_payload(
    db: AsyncSession,
    limit: int,
    asset_class: str | None = None,
) -> RecentBacktestsResponse:
    stmt = (
        select(Backtest, BacktestResultRecord)
        .outerjoin(
            BacktestResultRecord,
            BacktestResultRecord.backtest_id == Backtest.id,
        )
        .order_by(Backtest.created_at.desc(), Backtest.id.desc())
        .limit(limit)
    )

    if asset_class:
        stmt = stmt.where(Backtest.asset_class == AssetClass(asset_class))

    rows = (await db.execute(stmt)).all()

    items = [
        RecentBacktestSummary(
            backtest_id=int(backtest_row.id),
            status=str(backtest_row.status),
            strategy_name=str(backtest_row.strategy_name),
            asset_class=backtest_row.asset_class.value if backtest_row.asset_class else None,
            symbols=list(backtest_row.symbols or []),
            start_date=backtest_row.start_date.date().isoformat(),
            end_date=backtest_row.end_date.date().isoformat(),
            created_at=backtest_row.created_at.isoformat() if backtest_row.created_at else "",
            initial_capital=float(backtest_row.initial_capital),
            total_return=float(result_row.total_return) if result_row and result_row.total_return is not None else None,
            max_drawdown=float(result_row.max_drawdown) if result_row and result_row.max_drawdown is not None else None,
            sharpe_ratio=float(result_row.sharpe_ratio) if result_row and result_row.sharpe_ratio is not None else None,
            total_trades=int(result_row.total_trades) if result_row and result_row.total_trades is not None else None,
            persisted=result_row is not None,
        )
        for backtest_row, result_row in rows
    ]

    return RecentBacktestsResponse(items=items)


async def _get_backtest_results_payload(
    db: AsyncSession,
    backtest_id: int,
) -> BacktestResponse:
    backtest_stmt = select(Backtest).where(Backtest.id == backtest_id)
    backtest_row = (await db.execute(backtest_stmt)).scalar_one_or_none()
    if backtest_row is None:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

    result_stmt = select(BacktestResultRecord).where(BacktestResultRecord.backtest_id == backtest_id)
    result_row = (await db.execute(result_stmt)).scalar_one_or_none()
    if result_row is None:
        raise HTTPException(status_code=202, detail=f"Backtest {backtest_id} results are not ready")

    trade_stmt = (
        select(Trade, Asset.symbol)
        .join(Asset, Trade.asset_id == Asset.id)
        .where(Trade.backtest_id == backtest_id)
        .order_by(Trade.timestamp)
    )
    trade_rows = (await db.execute(trade_stmt)).all()

    equity_curve_payload = result_row.equity_curve or []
    equity_curve = [
        EquityCurvePoint(
            timestamp=str(point["timestamp"]),
            equity=float(point["equity"]),
        )
        for point in equity_curve_payload
    ]
    drawdown_curve = _drawdown_curve_from_payload(equity_curve_payload)
    equity_series = _equity_series_from_payload(equity_curve_payload)
    trades_df = pd.DataFrame(
        [
            {
                "symbol": str(symbol),
                "side": trade.side.value if isinstance(trade.side, OrderSide) else str(trade.side),
                "quantity": float(trade.quantity),
                "price": float(trade.price),
                "commission": float(trade.commission or 0.0),
                "slippage": float(trade.slippage or 0.0),
                "timestamp": trade.timestamp,
                "pnl": float(trade.pnl or 0.0),
                "signal_source": str(trade.signal_source or ""),
                "signal_confidence": float(trade.signal_confidence or 0.0),
            }
            for trade, symbol in trade_rows
        ]
    )
    computed_metrics = compute_metrics(
        equity_curve=equity_series,
        benchmark=None,
        trades=trades_df if not trades_df.empty else None,
    )

    return BacktestResponse(
        backtest_id=int(backtest_row.id),
        persisted=True,
        persistence_error=None,
        status=str(backtest_row.status),
        created_at=backtest_row.created_at.isoformat() if backtest_row.created_at else None,
        metrics=_hydrate_metrics(result_row, computed_metrics),
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trades=[
            TradeResponse(
                symbol=str(symbol),
                side=trade.side.value if isinstance(trade.side, OrderSide) else str(trade.side),
                quantity=float(trade.quantity),
                price=float(trade.price),
                commission=float(trade.commission or 0.0),
                slippage=float(trade.slippage or 0.0),
                timestamp=trade.timestamp.isoformat(),
                pnl=float(trade.pnl or 0.0),
                signal_source=str(trade.signal_source or ""),
                signal_confidence=float(trade.signal_confidence or 0.0),
            )
            for trade, symbol in trade_rows
        ],
        strategy_name=str(backtest_row.strategy_name),
        symbols=list(backtest_row.symbols or []),
        start_date=backtest_row.start_date.date().isoformat(),
        end_date=backtest_row.end_date.date().isoformat(),
        initial_capital=float(backtest_row.initial_capital),
        strategy_params=dict(backtest_row.parameters or {}),
    )


def _build_backtest_name(request: BacktestRequest, created_at: datetime) -> str:
    timestamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"{request.strategy}-{request.asset_class}-{timestamp}"


def _equity_curve_payload(equity_curve: pd.Series) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": _serialize_timestamp(timestamp),
            "equity": float(value),
        }
        for timestamp, value in equity_curve.items()
    ]


def _monthly_returns_payload(equity_curve: pd.Series) -> list[dict[str, float]]:
    if equity_curve.empty:
        return []

    monthly = equity_curve.resample("ME").last()
    returns = monthly.pct_change().dropna()
    return [
        {
            "month": pd.Timestamp(timestamp).strftime("%Y-%m"),
            "return": float(value),
        }
        for timestamp, value in returns.items()
    ]


def _drawdown_curve_from_payload(payload: list[dict[str, Any]]) -> list[DrawdownPoint]:
    if not payload:
        return []

    equity_series = pd.Series(
        [float(item["equity"]) for item in payload],
        index=pd.to_datetime([item["timestamp"] for item in payload]),
    )
    cumulative = equity_series / equity_series.iloc[0]
    drawdown = (cumulative / cumulative.cummax()) - 1
    return [
        DrawdownPoint(
            timestamp=_serialize_timestamp(timestamp),
            drawdown=float(value),
        )
        for timestamp, value in drawdown.items()
    ]


def _equity_series_from_payload(payload: list[dict[str, Any]]) -> pd.Series:
    if not payload:
        return pd.Series(dtype=float, name="equity")
    return pd.Series(
        [float(item["equity"]) for item in payload],
        index=pd.to_datetime([item["timestamp"] for item in payload]),
        name="equity",
    )


def _default_currency(asset_class: AssetClass) -> str:
    if asset_class == AssetClass.CRYPTO:
        return "USDT"
    if asset_class == AssetClass.ASIA_EQUITY:
        return "LOCAL"
    return "USD"


def _hydrate_metrics(
    result_row: BacktestResultRecord,
    computed_metrics,
) -> MetricsResponse:
    return MetricsResponse(
        total_return=_stored_metric(result_row.total_return, computed_metrics.total_return),
        annualized_return=_stored_metric(
            result_row.annualized_return,
            computed_metrics.annualized_return,
        ),
        sharpe_ratio=_stored_metric(result_row.sharpe_ratio, computed_metrics.sharpe_ratio),
        sortino_ratio=_stored_metric(result_row.sortino_ratio, computed_metrics.sortino_ratio),
        max_drawdown=_stored_metric(result_row.max_drawdown, computed_metrics.max_drawdown),
        calmar_ratio=_stored_metric(result_row.calmar_ratio, computed_metrics.calmar_ratio),
        alpha=_stored_metric(result_row.alpha, computed_metrics.alpha),
        beta=_stored_metric(result_row.beta, computed_metrics.beta),
        win_rate=_stored_metric(result_row.win_rate, computed_metrics.win_rate),
        profit_factor=_stored_metric(result_row.profit_factor, computed_metrics.profit_factor),
        total_trades=int(_stored_metric(result_row.total_trades, computed_metrics.total_trades)),
        avg_trade_duration_days=_stored_metric(
            result_row.avg_trade_duration,
            computed_metrics.avg_trade_duration_days,
        ),
        volatility=_stored_metric(getattr(result_row, "volatility", None), computed_metrics.volatility),
        var_95=_stored_metric(getattr(result_row, "var_95", None), computed_metrics.var_95),
        cvar_95=_stored_metric(getattr(result_row, "cvar_95", None), computed_metrics.cvar_95),
        information_ratio=_stored_metric(
            getattr(result_row, "information_ratio", None),
            computed_metrics.information_ratio,
        ),
    )


def _stored_metric(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


def _serialize_timestamp(value: Any) -> str:
    return pd.Timestamp(value).isoformat()
