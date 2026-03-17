"""API routes for listing supported assets and fetching candle data."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import AssetClass, Interval, get_db
from backend.data.providers import (
    get_default_benchmark_symbol,
    get_provider,
    get_provider_settings,
    list_supported_asset_classes,
    normalize_asset_symbol,
)
from backend.data.store import DataStore
from backend.features.pipeline import FeaturePipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class AssetCatalogEntry(BaseModel):
    asset_class: str
    provider: str
    free_tier: bool
    mvp_enabled: bool
    default_benchmark: str | None = None
    notes: str
    symbols: list[str]


class AssetCatalogResponse(BaseModel):
    assets: list[AssetCatalogEntry]


class CandleResponse(BaseModel):
    symbol: str
    asset_class: str
    provider: str
    source: str
    interval: str
    start_date: str
    end_date: str
    include_features: bool
    candles: list[dict[str, Any]]


class IngestRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    asset_class: str = "us_equity"
    start_date: date
    end_date: date
    interval: str = "1d"


class IngestedSymbolResult(BaseModel):
    symbol: str
    asset_id: int
    rows_ingested: int


class IngestResponse(BaseModel):
    asset_class: str
    provider: str
    interval: str
    start_date: str
    end_date: str
    requested_symbols: list[str]
    ingested_symbols: list[str]
    missing_symbols: list[str]
    total_rows_ingested: int
    results: list[IngestedSymbolResult]


@router.get("/assets", response_model=AssetCatalogResponse)
async def list_assets(
    asset_class: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
) -> AssetCatalogResponse:
    """List symbols available from the free-first providers."""
    asset_classes = [asset_class] if asset_class else list_supported_asset_classes()

    assets: list[AssetCatalogEntry] = []
    for asset_class_name in asset_classes:
        try:
            settings = get_provider_settings(asset_class_name)
            provider = get_provider(asset_class_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        symbols = provider.get_available_symbols()[:limit]
        assets.append(
            AssetCatalogEntry(
                asset_class=asset_class_name,
                provider=settings["provider"],
                free_tier=bool(settings["free_tier"]),
                mvp_enabled=bool(settings["mvp_enabled"]),
                default_benchmark=get_default_benchmark_symbol(asset_class_name),
                notes=str(settings["notes"]),
                symbols=symbols,
            )
        )

    return AssetCatalogResponse(assets=assets)


@router.get("/candles/{symbol}", response_model=CandleResponse)
async def get_candles(
    symbol: str,
    asset_class: str = Query(default="us_equity"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    interval: str = Query(default="1d"),
    include_features: bool = Query(default=False),
    source: str = Query(default="auto"),
    db: AsyncSession = Depends(get_db),
) -> CandleResponse:
    """Fetch OHLCV candles directly from the configured free provider."""
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    try:
        settings = get_provider_settings(asset_class)
        asset_class_enum = AssetClass(asset_class)
        interval_enum = Interval(interval)
        normalized_symbol = normalize_asset_symbol(asset_class, symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    start = datetime.combine(start_date, time.min)
    end = datetime.combine(end_date, time.min)
    frame = pd.DataFrame()
    response_source = "provider"
    provider = None

    if source not in {"auto", "provider", "database"}:
        raise HTTPException(status_code=400, detail="source must be one of: auto, provider, database")

    if source in {"auto", "database"}:
        try:
            store = DataStore(db)
            asset = await store.get_asset(normalized_symbol, asset_class_enum)
            if asset is not None:
                stored_frame = await store.get_candles(
                    asset_id=int(asset.id),
                    start=start,
                    end=end,
                    interval=interval_enum,
                )
                if not stored_frame.empty:
                    frame = stored_frame.reset_index()
                    response_source = "database"
        except Exception as exc:
            if source == "database":
                logger.exception("Database error while loading candles for %s", symbol)
                raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
            logger.warning("Falling back to provider for %s after database error: %s", symbol, exc)

    if frame.empty and source in {"auto", "provider"}:
        try:
            provider = get_provider(asset_class)
            frame = await provider.fetch_historical(normalized_symbol, start, end, interval)
            response_source = "provider"
        except Exception as exc:
            logger.exception("Failed to fetch candles for %s (%s)", normalized_symbol, asset_class)
            raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}") from exc

    if frame.empty:
        raise HTTPException(status_code=404, detail=f"No candles returned for {normalized_symbol}")

    if include_features:
        frame = FeaturePipeline().generate(frame)

    frame = frame.sort_values("timestamp").reset_index(drop=True)

    return CandleResponse(
        symbol=normalized_symbol,
        asset_class=asset_class,
        provider=str(settings["provider"]),
        source=response_source,
        interval=interval,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        include_features=include_features,
        candles=_serialize_frame(frame),
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest_data(
    request: IngestRequest,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Fetch candles from a free provider and upsert them into PostgreSQL."""
    if request.start_date >= request.end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    try:
        settings = get_provider_settings(request.asset_class)
        provider = get_provider(request.asset_class)
        asset_class_enum = AssetClass(request.asset_class)
        interval_enum = Interval(request.interval)
        normalized_symbols = [
            normalize_asset_symbol(request.asset_class, symbol)
            for symbol in request.symbols
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    start = datetime.combine(request.start_date, time.min)
    end = datetime.combine(request.end_date, time.min)

    try:
        raw_data = await provider.fetch_batch(normalized_symbols, start, end, request.interval)
    except Exception as exc:
        logger.exception("Failed to fetch candles for ingestion request")
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}") from exc

    if not raw_data:
        raise HTTPException(
            status_code=404,
            detail="No data available for the requested symbols and date range",
        )

    store = DataStore(db)
    results: list[IngestedSymbolResult] = []

    try:
        for symbol in normalized_symbols:
            frame = raw_data.get(symbol)
            if frame is None or frame.empty:
                continue

            asset = await store.upsert_asset(
                symbol=symbol,
                asset_class=asset_class_enum,
                name=symbol,
                exchange=_infer_exchange(symbol, request.asset_class),
                currency=_infer_currency(symbol, request.asset_class),
            )
            rows_ingested = await store.store_candles(
                asset_id=int(asset.id),
                df=frame,
                interval=interval_enum,
            )
            results.append(
                IngestedSymbolResult(
                    symbol=symbol,
                    asset_id=int(asset.id),
                    rows_ingested=rows_ingested,
                )
            )
    except SQLAlchemyError as exc:
        logger.exception("Database error during candle ingestion")
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    ingested_symbols = [item.symbol for item in results]
    missing_symbols = [symbol for symbol in normalized_symbols if symbol not in ingested_symbols]

    return IngestResponse(
        asset_class=request.asset_class,
        provider=str(settings["provider"]),
        interval=request.interval,
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        requested_symbols=normalized_symbols,
        ingested_symbols=ingested_symbols,
        missing_symbols=missing_symbols,
        total_rows_ingested=sum(item.rows_ingested for item in results),
        results=results,
    )


def _serialize_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = frame.to_dict(orient="records")
    serialized: list[dict[str, Any]] = []

    for record in records:
        item: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, (pd.Timestamp, datetime)):
                item[key] = pd.Timestamp(value).isoformat()
            elif pd.isna(value):
                item[key] = None
            elif isinstance(value, (int, float, bool, str)):
                item[key] = value
            else:
                item[key] = float(value) if hasattr(value, "__float__") else str(value)
        serialized.append(item)

    return serialized


def _infer_exchange(symbol: str, asset_class: str) -> str | None:
    if asset_class == "asia_equity":
        if symbol.endswith(".SI") or symbol == "^STI":
            return "SGX"
        if symbol.endswith(".HK") or symbol == "^HSI":
            return "HKEX"
        if symbol.endswith(".KS") or symbol == "^KS11":
            return "KRX"
    if asset_class == "crypto":
        return "BINANCE"
    return None


def _infer_currency(symbol: str, asset_class: str) -> str:
    if asset_class == "crypto":
        return "USDT"
    if asset_class == "asia_equity":
        if symbol.endswith(".SI") or symbol == "^STI":
            return "SGD"
        if symbol.endswith(".HK") or symbol == "^HSI":
            return "HKD"
        if symbol.endswith(".KS") or symbol == "^KS11":
            return "KRW"
    return "USD"
