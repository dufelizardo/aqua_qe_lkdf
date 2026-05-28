"""
AQuA-QE LKDF — RAG Routes §32
Endpoints para busca semântica e retrieval augmented generation.
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from backend.gateway.rag import rag_engine

router_rag = APIRouter(prefix="/api/v1/rag")


class SearchRequest(BaseModel):
    query:       str
    index:       str = "knowledge"   # knowledge | sessions | stories
    top_k:       int = 5
    min_score:   float = 0.05
    type_filter: str = ""            # rn | ca | pattern | scenario | ...


class AugmentRequest(BaseModel):
    query:         str
    system_prompt: str = ""
    index:         str = "knowledge"
    top_k:         int = 4
    min_score:     float = 0.05


class IndexRequest(BaseModel):
    doc_id:   str
    text:     str
    metadata: dict = {}
    index:    str = "knowledge"


@router_rag.post("/search")
async def rag_search(req: SearchRequest):
    """Busca semântica nos índices RAG."""
    results = rag_engine.retrieve(
        query=req.query,
        index=req.index,
        top_k=req.top_k,
        min_score=req.min_score,
        type_filter=req.type_filter,
    )
    return {
        "query":   req.query,
        "index":   req.index,
        "results": results,
        "total":   len(results),
    }


@router_rag.post("/search-all")
async def rag_search_all(body: dict):
    """Busca em todos os índices simultaneamente."""
    query = body.get("query", "")
    top_k = int(body.get("top_k", 3))
    results = rag_engine.retrieve_multi(query, top_k=top_k)
    return {"query": query, "results": results}


@router_rag.post("/augment")
async def rag_augment(req: AugmentRequest):
    """
    Recupera contexto e constrói system prompt aumentado.
    Use antes de chamar /analyze para injetar conhecimento relevante.
    """
    augmented, sources = rag_engine.augment_prompt(
        user_query=req.query,
        system_prompt=req.system_prompt,
        index=req.index,
        top_k=req.top_k,
        min_score=req.min_score,
    )
    return {
        "augmented_prompt": augmented,
        "sources":          sources,
        "context_injected": len(sources) > 0,
        "source_count":     len(sources),
    }


@router_rag.post("/index")
async def rag_index(req: IndexRequest):
    """Adiciona documento manualmente ao índice RAG."""
    store = rag_engine._indices.get(req.index)
    if not store:
        from fastapi import HTTPException
        raise HTTPException(400, f"Índice '{req.index}' não existe. Use: knowledge, sessions, stories")
    store.add(doc_id=req.doc_id, text=req.text, metadata=req.metadata)
    return {"status": "indexed", "index": req.index, "doc_id": req.doc_id}


@router_rag.post("/reindex")
async def rag_reindex():
    """Re-indexa todo o Knowledge Layer do zero."""
    from backend.gateway.knowledge import knowledge_manager
    from backend.gateway.rag import bootstrap_from_knowledge
    rag_engine.clear_index("knowledge")
    n = bootstrap_from_knowledge(knowledge_manager)
    return {"status": "reindexed", "items": n}


@router_rag.get("/stats")
async def rag_stats():
    """Estatísticas dos índices RAG: tamanho, queries, hit rate."""
    return rag_engine.stats()


@router_rag.delete("/index/{index_name}")
async def clear_index(index_name: str):
    """Limpa um índice RAG específico."""
    rag_engine.clear_index(index_name)
    return {"status": "cleared", "index": index_name}
