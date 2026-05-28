"""
AQuA-QE LKDF — AI Security & Governance Routes §30
Endpoints para auditoria, PII detection, política e governança.
"""
from __future__ import annotations
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.gateway.security import security_gateway

router_security = APIRouter(prefix="/api/v1/security")


# ── DTOs ──────────────────────────────────────────────────────

class InspectRequest(BaseModel):
    content:    str
    provider:   str = ""
    engine:     str = ""
    session_id: Optional[str] = None
    actor:      str = "user"


class PolicyUpdateRequest(BaseModel):
    updates: dict[str, Any]


# ── Routes ────────────────────────────────────────────────────

@router_security.get("/summary")
async def security_summary():
    """Resumo de segurança: estatísticas de audit, PII e política ativa."""
    return security_gateway.summary()


@router_security.post("/inspect")
async def inspect_content(req: InspectRequest):
    """
    Inspeciona conteúdo para PII e política.
    Retorna findings, content mascarado e ação tomada.
    """
    return security_gateway.inspect_request(
        content=req.content,
        provider=req.provider,
        engine=req.engine,
        session_id=req.session_id,
        actor=req.actor,
    )


@router_security.get("/audit")
async def get_audit_log(limit: int = 100, outcome: str = "", q: str = ""):
    """
    Log de auditoria com filtros por outcome e busca livre.
    outcome: allowed | blocked | masked | flagged
    """
    if q.strip():
        entries = security_gateway.audit.search(q.strip(), limit)
    else:
        entries = security_gateway.audit.recent(limit, outcome_filter=outcome)
    return {
        "entries": entries,
        "stats":   security_gateway.audit.stats(),
    }


@router_security.get("/policy")
async def get_policy():
    """Retorna a política de segurança ativa."""
    return security_gateway.policy.to_dict()


@router_security.patch("/policy")
async def update_policy(req: PolicyUpdateRequest):
    """Atualiza campos da política de segurança."""
    security_gateway.policy.update(req.updates)
    # Rebuild PII detector with updated patterns
    enabled = security_gateway.policy.get("pii_patterns_enabled", [])
    from backend.gateway.security import PIIDetector
    security_gateway.detector = PIIDetector(enabled_patterns=enabled or None)
    return {"status": "updated", "policy": security_gateway.policy.to_dict()}


@router_security.get("/pii-stats")
async def get_pii_stats():
    """Estatísticas de detecção de PII por tipo."""
    return {
        "by_type": security_gateway.detector.stats(),
        "total":   sum(security_gateway.detector.stats().values()),
    }


@router_security.post("/scan")
async def scan_text(body: dict):
    """
    Scan rápido de texto para PII sem aplicar mascaramento.
    Body: { "text": "..." }
    """
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "Campo 'text' obrigatório")
    findings = security_gateway.detector.detect(text)
    _, masked_types = security_gateway.detector.mask(text, dry_run=True)
    return {
        "findings":    findings,
        "would_mask":  masked_types,
        "char_count":  len(text),
    }


@router_security.post("/mask")
async def mask_text(body: dict):
    """
    Aplica mascaramento de PII ao texto fornecido.
    Body: { "text": "...", "dry_run": false }
    """
    text    = body.get("text", "")
    dry_run = body.get("dry_run", False)
    if not text:
        raise HTTPException(400, "Campo 'text' obrigatório")
    masked, types = security_gateway.detector.mask(text, dry_run=dry_run)
    return {
        "original_length": len(text),
        "masked_text":     masked,
        "masked_types":    types,
        "changed":         masked != text,
    }
