"""
AQuA-QE LKDF — AI Observability Routes
§29: logs de reasoning, tracing, custo, percentis, heatmap, explainability.
"""
from fastapi import APIRouter
from backend.gateway.observability import observability

router_obs = APIRouter(prefix="/api/v1/observability")


@router_obs.get("/summary")
async def obs_summary():
    """Resumo geral: success rate, latência P50/P95/P99, custo total."""
    return observability.summary()


@router_obs.get("/by-provider")
async def obs_by_provider():
    """Stats por provider: requests, latência, custo, fallbacks."""
    return observability.by_provider()


@router_obs.get("/by-engine")
async def obs_by_engine():
    """Stats por engine cognitiva: requests, latência média, custo."""
    return observability.by_engine()


@router_obs.get("/hourly-trend")
async def obs_hourly_trend(hours: int = 24):
    """Tendência horária: requests, latência média, custo por hora."""
    return {"trend": observability.hourly_trend(min(hours, 48))}


@router_obs.get("/traces")
async def obs_traces(limit: int = 50):
    """Traces recentes com detalhe completo (engine chain, confidence, error type)."""
    return {"traces": observability.recent_traces(min(limit, 200))}


@router_obs.get("/latency-heatmap")
async def obs_latency_heatmap():
    """Heatmap Provider × Engine com latência média."""
    return observability.latency_heatmap()


@router_obs.get("/cost-breakdown")
async def obs_cost_breakdown():
    """Custo por modelo e por hora."""
    return observability.cost_breakdown()


@router_obs.get("/confidence")
async def obs_confidence():
    """Distribuição de confidence scores."""
    return observability.confidence_distribution()
