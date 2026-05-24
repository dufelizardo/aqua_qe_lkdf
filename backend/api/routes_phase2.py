"""
AQuA-QE LKDF — Fase 2
Rotas adicionais: Engines Avançadas + Prompt Management System
Inclua no routes.py principal via: from backend.api.routes_phase2 import router_phase2; app.include_router(router_phase2)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.engines.advanced import engine_registry
from backend.gateway.prompt_manager import prompt_manager, PromptType
from backend.models.schemas import DeploymentMode, ProviderName

router_phase2 = APIRouter(prefix="/api/v2")


# ──────────────────────────────────────────────
# DTOs
# ──────────────────────────────────────────────

class EngineRunRequest(BaseModel):
    content: str
    variables: dict[str, str] = {}
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD
    force_provider: Optional[ProviderName] = None


class FullAnalysisRequest(BaseModel):
    content: str
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD


class ConsistencyRequest(BaseModel):
    rns: list[str]
    cas: list[str]
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD


class ImpactRequest(BaseModel):
    change_description: str
    existing_rtm: list[dict] = []
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD


class PromptCreateRequest(BaseModel):
    name: str
    prompt_type: PromptType
    description: str
    content: str
    system: str = ""
    tags: list[str] = []
    variables: dict[str, str] = {}


class PromptVersionRequest(BaseModel):
    content: str
    changelog: str = ""
    variables: dict[str, str] = {}


class PromptRenderRequest(BaseModel):
    variables: dict[str, str] = {}


# ──────────────────────────────────────────────
# Engine Routes
# ──────────────────────────────────────────────

@router_phase2.post("/engines/{engine_name}/run")
async def run_engine(engine_name: str, req: EngineRunRequest):
    """Executa uma engine avançada específica."""
    result = await engine_registry.run_engine(
        engine_name, req.content, req.variables,
        req.deployment_mode, req.force_provider,
    )
    return result.__dict__


@router_phase2.post("/engines/consistency/check")
async def consistency_check(req: ConsistencyRequest):
    """Verifica consistência entre RN e CA."""
    result = await engine_registry.consistency.check(req.rns, req.cas, req.deployment_mode)
    return result.__dict__


@router_phase2.post("/engines/impact/analyze")
async def impact_analyze(req: ImpactRequest):
    """Analisa impacto de uma mudança no RTM existente."""
    result = await engine_registry.impact.analyze(
        req.change_description, req.existing_rtm, req.deployment_mode)
    return result.__dict__


@router_phase2.post("/engines/full-analysis")
async def full_analysis(req: FullAnalysisRequest):
    """Pipeline completo: Risk + Coverage + Inference + Compliance → Synthesis."""
    return await engine_registry.full_analysis(req.content, req.deployment_mode)


@router_phase2.get("/engines")
async def list_engines():
    """Lista engines avançadas disponíveis."""
    return {
        "engines": [
            {"name": "risk",        "description": "Classificação e priorização de riscos", "section": "§6.6"},
            {"name": "coverage",    "description": "Cobertura funcional/técnica/risco/compliance", "section": "§6.7"},
            {"name": "inference",   "description": "Inferência de cenários e fluxos ocultos", "section": "§6.8"},
            {"name": "synthesis",   "description": "Consolidação e visão final de análises", "section": "§6.9"},
            {"name": "consistency", "description": "Validação de coerência RN × CA", "section": "§6.10"},
            {"name": "impact",      "description": "Análise de impacto de mudanças no RTM", "section": "§6.11"},
            {"name": "compliance",  "description": "WCAG / OWASP / LGPD / ISO", "section": "§6.12"},
        ]
    }


# ──────────────────────────────────────────────
# Prompt Management Routes  (§27)
# ──────────────────────────────────────────────

@router_phase2.get("/prompts")
async def list_prompts(prompt_type: Optional[str] = None):
    """Lista todos os templates de prompt."""
    pt = PromptType(prompt_type) if prompt_type else None
    templates = prompt_manager.list_templates(pt)
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "prompt_type": t.prompt_type,
                "description": t.description,
                "tags": t.tags,
                "active_version": t.active_version,
                "versions_count": len(t.versions),
                "usage_count": t.usage_count,
                "avg_latency_ms": round(t.avg_latency_ms, 1),
                "avg_cost_usd": round(t.avg_cost_usd, 6),
                "created_at": t.created_at.isoformat(),
                "variables": t.current.variables if t.current else {},
            }
            for t in templates
        ],
        "total": len(templates),
    }


@router_phase2.get("/prompts/{template_id}")
async def get_prompt(template_id: str):
    """Retorna template com todas as versões."""
    t = prompt_manager.get_template(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return {
        "id": t.id, "name": t.name, "prompt_type": t.prompt_type,
        "description": t.description, "tags": t.tags,
        "active_version": t.active_version, "usage_count": t.usage_count,
        "versions": [
            {"version": v.version, "hash": v.hash, "changelog": v.changelog,
             "content": v.content, "system": v.system,
             "variables": v.variables, "created_at": v.created_at.isoformat()}
            for v in t.versions
        ],
    }


@router_phase2.post("/prompts")
async def create_prompt(req: PromptCreateRequest):
    """Cria novo template de prompt."""
    from backend.gateway.prompt_manager import SYSTEM_BASE
    t = prompt_manager.create_template(
        name=req.name, prompt_type=req.prompt_type,
        description=req.description, content=req.content,
        system=req.system or SYSTEM_BASE, tags=req.tags, variables=req.variables,
    )
    return {"id": t.id, "name": t.name, "version": t.active_version}


@router_phase2.post("/prompts/{template_id}/versions")
async def add_prompt_version(template_id: str, req: PromptVersionRequest):
    """Adiciona nova versão a um template existente."""
    v = prompt_manager.add_version(template_id, req.content, req.changelog, req.variables)
    if not v:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return {"version": v.version, "hash": v.hash}


@router_phase2.post("/prompts/{template_id}/render")
async def render_prompt(template_id: str, req: PromptRenderRequest):
    """Renderiza um template com variáveis."""
    system, content = prompt_manager.render(template_id, req.variables)
    return {"system": system, "content": content}


@router_phase2.get("/prompts/{template_id}/logs")
async def get_prompt_logs(template_id: str, limit: int = 20):
    """Retorna logs de execução de um template."""
    logs = prompt_manager.get_logs(template_id, limit)
    return {
        "logs": [
            {"id": l.id, "version": l.version_used, "provider": l.provider,
             "model": l.model, "latency_ms": round(l.latency_ms, 1),
             "cost_usd": l.cost_usd, "success": l.success,
             "timestamp": l.timestamp.isoformat()}
            for l in logs
        ]
    }


@router_phase2.get("/prompts/stats/summary")
async def prompt_stats():
    """Estatísticas consolidadas do Prompt Manager."""
    return prompt_manager.get_stats()
