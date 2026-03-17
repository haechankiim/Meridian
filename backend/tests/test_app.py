"""Smoke tests for the FastAPI MVP routes."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.api.routes import backtest as backtest_routes
from backend.api.routes import data as data_routes
from backend.app.database import Candle, get_db
from backend.app.main import app
from backend.data.providers import yahoo as yahoo_provider


class StubUSEquityProvider:
    """Small in-memory provider used to keep smoke tests offline."""

    async def fetch_batch(self, symbols, start, end, interval):
        del start, end, interval
        return {symbol: _build_price_frame(symbol) for symbol in symbols}

    async def fetch_historical(self, symbol, start, end, interval):
        del start, end, interval
        return _build_price_frame(symbol)

    def get_available_symbols(self):
        return ["AAPL", "MSFT", "NVDA", "SPY"]


class StubForexProvider:
    """Small in-memory forex provider used for compact symbol tests."""

    async def fetch_batch(self, symbols, start, end, interval):
        del start, end, interval
        assert symbols == ["EUR/USD"]
        return {symbol: _build_price_frame(symbol) for symbol in symbols}

    async def fetch_historical(self, symbol, start, end, interval):
        del start, end, interval
        assert symbol == "EUR/USD"
        return _build_price_frame(symbol)

    def get_available_symbols(self):
        return ["EUR/USD", "GBP/USD", "USD/JPY"]


def _build_price_frame(symbol: str) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=160, freq="B")
    closes = pd.Series(100 + (timestamps.dayofyear.to_numpy() * 0.25), dtype=float)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": (closes - 0.5).to_numpy(),
            "high": (closes + 1.0).to_numpy(),
            "low": (closes - 1.0).to_numpy(),
            "close": closes.to_numpy(),
            "volume": 1_000_000 + (timestamps.dayofyear.to_numpy() * 1_000),
            "adjusted_close": closes.to_numpy(),
            "symbol": symbol,
        }
    )


def _build_yahoo_history_frame() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=5, freq="B", name="Date")
    closes = pd.Series([100.0, 101.5, 103.0, 102.0, 104.0], index=index)
    return pd.DataFrame(
        {
            "Open": closes - 0.5,
            "High": closes + 1.0,
            "Low": closes - 1.0,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(index),
        },
        index=index,
    )


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "meridian"}


def test_fetch_yahoo_ohlcv_falls_back_to_ticker_history(monkeypatch):
    class StubTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            del kwargs
            return _build_yahoo_history_frame()

    monkeypatch.setattr(yahoo_provider.yf, "download", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(yahoo_provider.yf, "Ticker", StubTicker)

    frame = yahoo_provider.fetch_yahoo_ohlcv(
        "AAPL",
        pd.Timestamp("2024-01-01").to_pydatetime(),
        pd.Timestamp("2024-02-01").to_pydatetime(),
    )

    assert not frame.empty
    assert frame["symbol"].iloc[-1] == "AAPL"
    assert "timestamp" in frame.columns


def test_fetch_yahoo_ohlcv_reports_attempts_when_all_requests_are_empty(monkeypatch):
    class StubTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            del kwargs
            return pd.DataFrame()

    monkeypatch.setattr(yahoo_provider.yf, "download", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(yahoo_provider.yf, "Ticker", StubTicker)

    with pytest.raises(ValueError, match="download: empty; ticker.history: empty"):
        yahoo_provider.fetch_yahoo_ohlcv(
            "AAPL",
            pd.Timestamp("2024-01-01").to_pydatetime(),
            pd.Timestamp("2024-02-01").to_pydatetime(),
        )


def test_candle_interval_column_uses_string_values():
    interval_type = Candle.__table__.c.interval.type

    assert interval_type.native_enum is False
    assert interval_type.enums == ["1m", "5m", "15m", "1h", "1d", "1w"]


def test_hydrate_metrics_prefers_persisted_values():
    persisted = SimpleNamespace(
        total_return=0.2,
        annualized_return=0.3,
        sharpe_ratio=1.2,
        sortino_ratio=1.5,
        max_drawdown=-0.1,
        calmar_ratio=3.0,
        alpha=0.04,
        beta=0.7,
        win_rate=0.6,
        profit_factor=1.9,
        total_trades=5,
        avg_trade_duration=4.0,
        volatility=0.21,
        var_95=-0.03,
        cvar_95=-0.04,
        information_ratio=0.8,
    )
    computed = backtest_routes.MetricsResponse(
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

    merged = backtest_routes._hydrate_metrics(persisted, computed)

    assert merged.alpha == 0.04
    assert merged.beta == 0.7
    assert merged.information_ratio == 0.8
    assert merged.total_trades == 5


def test_strategy_listing_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/strategy/")

    assert response.status_code == 200
    body = response.json()
    assert "strategies" in body
    assert any(item["name"] == "momentum" for item in body["strategies"])


def test_assets_endpoint(monkeypatch):
    monkeypatch.setattr(
        data_routes,
        "get_provider",
        lambda asset_class: StubUSEquityProvider(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/data/assets?asset_class=us_equity&limit=3")

    assert response.status_code == 200
    body = response.json()
    assert len(body["assets"]) == 1
    assert body["assets"][0]["asset_class"] == "us_equity"
    assert body["assets"][0]["symbols"] == ["AAPL", "MSFT", "NVDA"]


def test_candles_endpoint(monkeypatch):
    monkeypatch.setattr(
        data_routes,
        "get_provider",
        lambda asset_class: StubUSEquityProvider(),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/data/candles/AAPL",
            params={
                "asset_class": "us_equity",
                "start_date": "2024-01-01",
                "end_date": "2024-08-30",
                "interval": "1d",
                "include_features": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["source"] == "provider"
    assert body["include_features"] is True
    assert len(body["candles"]) > 0
    assert "rsi_14" in body["candles"][-1]


def test_candles_endpoint_normalizes_compact_forex_symbol(monkeypatch):
    monkeypatch.setattr(
        data_routes,
        "get_provider",
        lambda asset_class: StubForexProvider(),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/data/candles/EURUSD",
            params={
                "asset_class": "forex",
                "start_date": "2024-01-01",
                "end_date": "2024-08-30",
                "interval": "1d",
                "include_features": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "EUR/USD"
    assert body["asset_class"] == "forex"


def test_candles_endpoint_prefers_database_source(monkeypatch):
    class StubDataStore:
        def __init__(self, session):
            self.session = session

        async def get_asset(self, symbol, asset_class):
            del symbol, asset_class
            return SimpleNamespace(id=1)

        async def get_candles(self, asset_id, start, end, interval):
            del asset_id, start, end, interval
            return _build_price_frame("BTCUSDT").set_index("timestamp")

    async def override_get_db():
        yield object()

    def fail_provider(asset_class):
        del asset_class
        raise AssertionError("provider should not be called when source=database and stored candles exist")

    monkeypatch.setattr(data_routes, "get_provider", fail_provider)
    monkeypatch.setattr(data_routes, "DataStore", StubDataStore)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/data/candles/BTCUSDT",
                params={
                    "asset_class": "crypto",
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-01",
                    "interval": "1d",
                    "include_features": "true",
                    "source": "database",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "database"
    assert len(body["candles"]) > 0
    assert "rsi_14" in body["candles"][-1]


def test_ingest_endpoint(monkeypatch):
    recorded = {"assets": [], "candles": []}

    class StubDataStore:
        def __init__(self, session):
            self.session = session

        async def upsert_asset(self, symbol, asset_class, name=None, exchange=None, currency="USD"):
            recorded["assets"].append(
                {
                    "symbol": symbol,
                    "asset_class": asset_class.value,
                    "exchange": exchange,
                    "currency": currency,
                }
            )
            return SimpleNamespace(id=len(recorded["assets"]))

        async def store_candles(self, asset_id, df, interval):
            recorded["candles"].append(
                {
                    "asset_id": asset_id,
                    "interval": interval.value,
                    "rows": len(df),
                }
            )
            return len(df)

    async def override_get_db():
        yield object()

    monkeypatch.setattr(
        data_routes,
        "get_provider",
        lambda asset_class: StubUSEquityProvider(),
    )
    monkeypatch.setattr(data_routes, "DataStore", StubDataStore)
    app.dependency_overrides[get_db] = override_get_db

    payload = {
        "symbols": ["AAPL", "MSFT"],
        "asset_class": "us_equity",
        "start_date": "2024-01-01",
        "end_date": "2024-08-30",
        "interval": "1d",
    }

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/data/ingest", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["asset_class"] == "us_equity"
    assert body["requested_symbols"] == ["AAPL", "MSFT"]
    assert body["missing_symbols"] == []
    assert body["total_rows_ingested"] == 320
    assert len(body["results"]) == 2
    assert recorded["assets"][0]["currency"] == "USD"
    assert recorded["candles"][0]["interval"] == "1d"


def test_backtest_run_endpoint(monkeypatch):
    async def override_get_db():
        yield object()

    monkeypatch.setattr(
        backtest_routes,
        "get_provider",
        lambda asset_class: StubUSEquityProvider(),
    )
    app.dependency_overrides[get_db] = override_get_db

    payload = {
        "symbols": ["AAPL", "MSFT"],
        "asset_class": "us_equity",
        "strategy": "momentum",
        "start_date": "2024-01-01",
        "end_date": "2024-08-30",
        "initial_capital": 100000,
        "interval": "1d",
        "benchmark_symbol": "SPY",
        "save_results": False,
    }

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/backtest/run", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_name"] == "momentum"
    assert body["symbols"] == ["AAPL", "MSFT"]
    assert len(body["equity_curve"]) > 0
    assert "metrics" in body
    assert body["persisted"] is False


def test_backtest_run_endpoint_accepts_zero_initial_capital(monkeypatch):
    async def override_get_db():
        yield object()

    monkeypatch.setattr(
        backtest_routes,
        "get_provider",
        lambda asset_class: StubUSEquityProvider(),
    )
    app.dependency_overrides[get_db] = override_get_db

    payload = {
        "symbols": ["AAPL"],
        "asset_class": "us_equity",
        "strategy": "momentum",
        "start_date": "2024-01-01",
        "end_date": "2024-08-30",
        "initial_capital": 0,
        "interval": "1d",
        "benchmark_symbol": "SPY",
        "save_results": False,
    }

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/backtest/run", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["initial_capital"] == 0
    assert body["metrics"]["total_return"] == 0


def test_backtest_status_endpoint(monkeypatch):
    async def override_get_db():
        yield object()

    async def fake_status_payload(db, backtest_id):
        del db
        return backtest_routes.BacktestStatusResponse(
            backtest_id=backtest_id,
            status="done",
            strategy_name="momentum",
            asset_class="us_equity",
            symbols=["AAPL", "MSFT"],
            start_date="2024-01-01",
            end_date="2024-08-30",
            created_at="2026-03-16T18:00:00",
            initial_capital=100000.0,
            strategy_params={"target_weight": 0.15},
        )

    monkeypatch.setattr(backtest_routes, "_get_backtest_status_payload", fake_status_payload)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/backtest/42/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["backtest_id"] == 42
    assert body["status"] == "done"
    assert body["symbols"] == ["AAPL", "MSFT"]


def test_recent_backtests_endpoint(monkeypatch):
    async def override_get_db():
        yield object()

    async def fake_recent_payload(db, limit, asset_class=None):
        del db, limit, asset_class
        return backtest_routes.RecentBacktestsResponse(
            items=[
                backtest_routes.RecentBacktestSummary(
                    backtest_id=7,
                    status="done",
                    strategy_name="momentum",
                    asset_class="crypto",
                    symbols=["BTCUSDT"],
                    start_date="2024-01-01",
                    end_date="2024-02-01",
                    created_at="2026-03-16T18:00:00",
                    initial_capital=100000.0,
                    total_return=0.042,
                    max_drawdown=-0.018,
                    sharpe_ratio=1.11,
                    total_trades=3,
                    persisted=True,
                )
            ]
        )

    monkeypatch.setattr(backtest_routes, "_list_recent_backtests_payload", fake_recent_payload)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/backtest/recent?limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["backtest_id"] == 7
    assert body["items"][0]["asset_class"] == "crypto"


def test_delete_backtest_endpoint():
    class FakeResult:
        def __init__(self, value=None):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeSession:
        def __init__(self):
            self.execute_calls = 0
            self.committed = False

        async def execute(self, stmt):
            del stmt
            self.execute_calls += 1
            if self.execute_calls == 1:
                return FakeResult(7)
            return FakeResult()

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.committed = False

    fake_session = FakeSession()

    async def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.delete("/api/v1/backtest/7")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"backtest_id": 7, "deleted": True}
    assert fake_session.committed is True


def test_backtest_results_endpoint(monkeypatch):
    async def override_get_db():
        yield object()

    async def fake_results_payload(db, backtest_id):
        del db
        return backtest_routes.BacktestResponse(
            backtest_id=backtest_id,
            persisted=True,
            persistence_error=None,
            status="done",
            created_at="2026-03-16T18:00:00",
            metrics=backtest_routes.MetricsResponse(
                total_return=0.1234,
                annualized_return=0.201,
                sharpe_ratio=1.25,
                sortino_ratio=1.8,
                max_drawdown=-0.05,
                calmar_ratio=4.02,
                alpha=0.01,
                beta=0.98,
                win_rate=0.6,
                profit_factor=1.4,
                total_trades=8,
                avg_trade_duration_days=4.5,
                volatility=0.12,
                var_95=-0.02,
                cvar_95=-0.03,
                information_ratio=0.4,
            ),
            equity_curve=[
                backtest_routes.EquityCurvePoint(timestamp="2024-01-01T00:00:00", equity=100000.0),
                backtest_routes.EquityCurvePoint(timestamp="2024-08-30T00:00:00", equity=112340.0),
            ],
            drawdown_curve=[
                backtest_routes.DrawdownPoint(timestamp="2024-01-01T00:00:00", drawdown=0.0),
                backtest_routes.DrawdownPoint(timestamp="2024-08-30T00:00:00", drawdown=-0.01),
            ],
            trades=[
                backtest_routes.TradeResponse(
                    symbol="AAPL",
                    side="buy",
                    quantity=10.0,
                    price=100.0,
                    commission=1.0,
                    slippage=0.5,
                    timestamp="2024-01-15T00:00:00",
                    pnl=0.0,
                    signal_source="momentum",
                    signal_confidence=0.8,
                )
            ],
            strategy_name="momentum",
            symbols=["AAPL", "MSFT"],
            start_date="2024-01-01",
            end_date="2024-08-30",
            initial_capital=100000.0,
            strategy_params={"target_weight": 0.15},
        )

    monkeypatch.setattr(backtest_routes, "_get_backtest_results_payload", fake_results_payload)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/backtest/42/results")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["backtest_id"] == 42
    assert body["persisted"] is True
    assert body["metrics"]["total_trades"] == 8


def test_risk_analytics_endpoint(monkeypatch):
    async def override_get_db():
        yield object()

    async def fake_risk_payload(db, backtest_id):
        del db
        return analytics_routes.RiskAnalyticsResponse(
            backtest_id=backtest_id,
            status="done",
            strategy_name="momentum",
            symbols=["BTCUSDT"],
            created_at="2026-03-16T18:00:00",
            latest_equity=102500.0,
            peak_equity=104000.0,
            trough_equity=99500.0,
            latest_drawdown=-0.01,
            max_drawdown=-0.045,
            volatility=0.14,
            var_95=-0.02,
            cvar_95=-0.03,
            alpha=0.012,
            beta=0.81,
            information_ratio=0.44,
            win_rate=0.55,
            profit_factor=1.3,
            total_trades=6,
            observation_count=18,
            risk_regime="controlled",
            monthly_returns=[
                analytics_routes.MonthlyReturnPoint(month="2024-01", return_value=0.025),
            ],
            drawdown_curve=[
                analytics_routes.RiskDrawdownPoint(
                    timestamp="2024-01-31T00:00:00",
                    drawdown=-0.01,
                )
            ],
        )

    monkeypatch.setattr(analytics_routes, "_get_risk_analytics_payload", fake_risk_payload)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/risk/42")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["backtest_id"] == 42
    assert body["risk_regime"] == "controlled"
    assert body["monthly_returns"][0]["month"] == "2024-01"
