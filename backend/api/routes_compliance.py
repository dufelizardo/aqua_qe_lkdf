"""
AQuA-QE LKDF — Compliance Routes §38
WCAG 2.1 · LGPD · OWASP Top 10 · ISO 25010
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from backend.engines.compliance_engine import compliance_engine

router_compliance = APIRouter(prefix="/api/v1/compliance")


class ComplianceAnalyzeRequest(BaseModel):
    text:       str
    standards:  Optional[list[str]] = None   # ["WCAG","LGPD","OWASP","ISO25010"]
    story_name: str = ""


@router_compliance.post("/analyze")
async def compliance_analyze(req: ComplianceAnalyzeRequest):
    """Analisa texto contra padrões de conformidade selecionados."""
    return compliance_engine.analyze(
        text=req.text,
        standards=req.standards,
        story_name=req.story_name,
    )


@router_compliance.post("/quick-scan")
async def compliance_quick_scan(body: dict):
    """Scan rápido: retorna score e top issues sem detalhe completo."""
    text = body.get("text", "")
    return compliance_engine.quick_scan(text)


@router_compliance.get("/rules")
async def compliance_rules(standard: str = ""):
    """Catálogo completo de regras, opcionalmente filtrado por standard."""
    return {
        "rules":   compliance_engine.rules_catalog(standard),
        "total":   len(compliance_engine.rules_catalog(standard)),
        "standards": compliance_engine.STANDARDS,
    }


@router_compliance.get("/standards")
async def compliance_standards():
    """Lista os padrões disponíveis com contagem de regras."""
    return {
        std: {
            "rules": len([r for r in compliance_engine.rules if r.standard == std]),
            "levels": list(set(r.level for r in compliance_engine.rules if r.standard == std)),
        }
        for std in compliance_engine.STANDARDS
    }
