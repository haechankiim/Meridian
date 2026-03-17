# Meridian

**Algorithmic Trading Backtester with ML Signal Generation**

A full-stack quantitative trading platform that combines multi-asset data ingestion, transformer-based price prediction, reinforcement learning for position sizing, and an event-driven backtesting engine — all served through a React dashboard.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLAlchemy, Celery, Redis |
| ML | PyTorch, Stable-Baselines3, scikit-learn, TA-Lib |
| Data | yfinance, Binance API, Alpha Vantage, PostgreSQL |
| Frontend | React 18, TypeScript, TradingView Charts, Recharts, TailwindCSS |
| Infra | Docker, GitHub Actions, Alembic |

## Supported Markets

| Market | Source | Assets |
|--------|--------|--------|
| US Equities | yfinance | S&P 500 components |
| Crypto | Binance | BTC, ETH, SOL + top 20 |
| Forex | Alpha Vantage | EUR/USD, GBP/USD, USD/JPY, USD/SGD |
| Asia | Yahoo Finance | STI (SGX), HSI (HKEX), KOSPI |

## ML Models

- **Temporal Fusion Transformer**: Multi-horizon price prediction with interpretable attention
- **PPO (RL Agent)**: Optimal position sizing under risk constraints
- **Ensemble**: Weighted signal fusion across models with dynamic confidence

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/meridian.git
cd meridian
docker-compose up -d

# Backend:  http://localhost:8000
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

## Local Development

```bash
# One command
./dev-up.sh

# Stop PostgreSQL after you're done
./dev-down.sh

# Clear all saved local market data + backtests
./reset-db.sh
```

`./dev-up.sh` starts PostgreSQL, the FastAPI backend on `http://127.0.0.1:8000`, and the Vite frontend on `http://127.0.0.1:3000`. Press `Ctrl+C` in that terminal to stop the frontend and backend together.

`./reset-db.sh` clears the local Meridian PostgreSQL tables. Add `--yes` to skip the confirmation prompt.

```bash
# Backend
cd backend
source .venv311/bin/activate
uvicorn backend.app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

The current frontend MVP is a single-page backtest runner that talks to the live FastAPI routes for:

- `GET /health`
- `GET /api/v1/data/assets`
- `POST /api/v1/backtest/run`

## License

MIT
