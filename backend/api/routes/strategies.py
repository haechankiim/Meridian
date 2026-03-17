"""API routes for strategy management."""
from fastapi import APIRouter

router = APIRouter()

def _strategy_payload():
    return {
        "strategies": [
            {"name": "momentum", "description": "Dual MA crossover with RSI + volume filter", "status": "active"},
            {"name": "mean_reversion", "description": "Statistical arbitrage — coming Week 5", "status": "planned"},
            {"name": "ml_ensemble", "description": "ML signal fusion — coming Week 5", "status": "planned"},
        ]
    }


@router.get("/")
@router.get("/list")
async def list_strategies():
    return _strategy_payload()
