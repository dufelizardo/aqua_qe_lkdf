"""
AQuA-QE LKDF — Knowledge Layer Routes §31
Endpoints para memória organizacional viva.
"""
from __future__ import annotations
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.gateway.knowledge import knowledge_manager

router_knowledge = APIRouter(prefix="/api/v1/knowledge")


class KnowledgeAddRequest(BaseModel):
    type:       str
    title:      str
    content:    str
    tags:       list[str] = []
    source:     str = ""
    story_name: str = ""
    rn_ids:     list[str] = []
    ca_ids:     list[str] = []
    confidence: float = 1.0


class KnowledgeExtractRequest(BaseModel):
    response_text: str
    story_name:    str = ""
    source:        str = ""


@router_knowledge.get("")
async def list_knowledge(
    type: str = "", limit: int = 50, offset: int = 0,
    sort: str = "updated", q: str = ""
):
    if q.strip():
        items = knowledge_manager.search(q.strip(), item_type=type, limit=limit)
    else:
        items = knowledge_manager.list(item_type=type, limit=limit, offset=offset, sort=sort)
    return {"items": items, "total": knowledge_manager.stats()["total"]}


@router_knowledge.post("")
async def add_knowledge(req: KnowledgeAddRequest):
    item = knowledge_manager.add(
        item_type=req.type, title=req.title, content=req.content,
        tags=req.tags, source=req.source, story_name=req.story_name,
        rn_ids=req.rn_ids, ca_ids=req.ca_ids, confidence=req.confidence,
    )
    return item


@router_knowledge.get("/stats")
async def knowledge_stats():
    return knowledge_manager.stats()


@router_knowledge.post("/extract")
async def extract_knowledge(req: KnowledgeExtractRequest):
    """Extrai RNs, CAs, padrões e cenários de uma resposta do LLM."""
    items = knowledge_manager.extract_from_response(
        response_text=req.response_text,
        story_name=req.story_name,
        source=req.source,
    )
    return {"extracted": len(items), "items": items}


@router_knowledge.get("/{item_id}")
async def get_knowledge(item_id: str):
    item = knowledge_manager.get(item_id)
    if not item:
        raise HTTPException(404, "Item não encontrado")
    related = knowledge_manager.get_related(item_id)
    return {**item, "related": related}


@router_knowledge.delete("/{item_id}")
async def delete_knowledge(item_id: str):
    ok = knowledge_manager.delete(item_id)
    if not ok:
        raise HTTPException(404, "Item não encontrado")
    return {"status": "deleted", "id": item_id}


@router_knowledge.patch("/{item_id}/tags")
async def update_tags(item_id: str, body: dict):
    tags = body.get("tags", [])
    ok   = knowledge_manager.update_tags(item_id, tags)
    if not ok:
        raise HTTPException(404, "Item não encontrado")
    return {"status": "updated", "tags": tags}


@router_knowledge.post("/{from_id}/relate/{to_id}")
async def add_relation(from_id: str, to_id: str, body: dict):
    rel_type = body.get("rel_type", "relates_to")
    weight   = float(body.get("weight", 1.0))
    ok = knowledge_manager.add_relation(from_id, to_id, rel_type, weight)
    return {"status": "ok" if ok else "error"}
