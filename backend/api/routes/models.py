"""API routes for ML model management."""
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_models():
    return {
        "models": [
            {"name": "temporal_fusion_transformer", "status": "planned", "target_week": 3},
            {"name": "ppo_rl_agent", "status": "planned", "target_week": 5},
        ]
    }
