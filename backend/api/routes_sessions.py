"""
AQuA-QE LKDF — Session Routes
Endpoints REST para histórico de sessões de chat.
"""
from __future__ import annotations
from typing import Optional, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.gateway.session_manager import session_manager

router_sessions = APIRouter(prefix="/api/v1/sessions")


# ── DTOs ──────────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    messages:  list[dict[str, Any]]
    rtm_items: list[dict[str, Any]] = []
    provider:  str = ""
    model:     str = ""
    engine:    str = "requirement"
    metadata:  dict[str, Any] = {}


class SessionUpdateRequest(BaseModel):
    messages:  Optional[list[dict[str, Any]]] = None
    rtm_items: Optional[list[dict[str, Any]]] = None
    provider:  Optional[str] = None
    model:     Optional[str] = None
    engine:    Optional[str] = None
    metadata:  Optional[dict[str, Any]] = None


# ── Routes ────────────────────────────────────────────────────

@router_sessions.get("")
async def list_sessions(limit: int = 50, offset: int = 0, q: str = ""):
    """Lista sessões com paginação e busca opcional."""
    if q.strip():
        sessions = session_manager.search_sessions(q.strip(), limit)
    else:
        sessions = session_manager.list_sessions(limit, offset)
    return {
        "sessions": sessions,
        "total":    session_manager.count(),
        "limit":    limit,
        "offset":   offset,
    }


@router_sessions.post("")
async def create_session(req: SessionCreateRequest):
    """Cria uma nova sessão."""
    session = session_manager.create_session(
        messages=req.messages,
        rtm_items=req.rtm_items,
        provider=req.provider,
        model=req.model,
        engine=req.engine,
        metadata=req.metadata,
    )
    return session


@router_sessions.get("/{session_id}")
async def get_session(session_id: str):
    """Retorna sessão completa com mensagens e RTM."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return session


@router_sessions.patch("/{session_id}")
async def update_session(session_id: str, req: SessionUpdateRequest):
    """Atualiza uma sessão existente (auto-save incremental)."""
    session = session_manager.update_session(
        session_id=session_id,
        messages=req.messages,
        rtm_items=req.rtm_items,
        provider=req.provider,
        model=req.model,
        engine=req.engine,
        metadata=req.metadata,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return {"status": "updated", "id": session_id, "title": session["title"]}


@router_sessions.delete("/{session_id}")
async def delete_session(session_id: str):
    """Remove uma sessão."""
    ok = session_manager.delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return {"status": "deleted", "id": session_id}


@router_sessions.get("/stats/summary")
async def sessions_stats():
    """Estatísticas do histórico de sessões."""
    sessions = session_manager.list_sessions(limit=200)
    total_cost   = sum(s.get("cost_usd", 0) for s in sessions)
    total_cts    = sum(s.get("ct_count", 0) for s in sessions)
    total_tokens = sum(s.get("tokens",   0) for s in sessions)
    providers    = {}
    for s in sessions:
        p = s.get("provider", "")
        if p:
            providers[p] = providers.get(p, 0) + 1
    return {
        "total_sessions":  len(sessions),
        "total_cost_usd":  round(total_cost, 6),
        "total_cts":       total_cts,
        "total_tokens":    total_tokens,
        "by_provider":     providers,
    }
