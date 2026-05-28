"""
AQuA-QE LKDF — Graph Database Routes §33
Nodes, relationships, traversal, analytics e export.
"""
from __future__ import annotations
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.gateway.graph_db import graph_db

router_graph = APIRouter(prefix="/api/v1/graph")


# ── DTOs ──────────────────────────────────────────────────────

class NodeRequest(BaseModel):
    label: str
    name:  str
    props: dict[str, Any] = {}
    node_id: Optional[str] = None


class RelRequest(BaseModel):
    from_id:  str
    to_id:    str
    rel_type: str
    weight:   float = 1.0
    props:    dict[str, Any] = {}


class TraversalRequest(BaseModel):
    node_id:   str
    direction: str = "both"   # out | in | both
    rel_type:  str = ""
    depth:     int = 1


# ── Node CRUD ────────────────────────────────────────────────

@router_graph.post("/nodes")
async def merge_node(req: NodeRequest):
    node = graph_db.merge_node(req.label, req.name, req.props, req.node_id)
    return node.to_dict()


@router_graph.get("/nodes/{node_id}")
async def get_node(node_id: str):
    node = graph_db.get_node(node_id)
    if not node:
        raise HTTPException(404, f"Node '{node_id}' não encontrado")
    degree = graph_db.degree(node_id)
    neighbors = graph_db.neighbors(node_id, depth=1)
    return {**node.to_dict(), "degree": degree, "neighbors": neighbors[:10]}


@router_graph.get("/nodes")
async def find_nodes(label: str = "", name: str = "", limit: int = 50):
    nodes = graph_db.find_nodes(label=label, name_like=name, limit=limit)
    return {"nodes": [n.to_dict() for n in nodes], "total": len(nodes)}


@router_graph.delete("/nodes/{node_id}")
async def delete_node(node_id: str):
    ok = graph_db.delete_node(node_id)
    if not ok:
        raise HTTPException(404, "Node não encontrado")
    return {"status": "deleted", "id": node_id}


# ── Relationship CRUD ─────────────────────────────────────────

@router_graph.post("/relationships")
async def merge_rel(req: RelRequest):
    rel = graph_db.merge_rel(req.from_id, req.to_id, req.rel_type, req.weight, req.props)
    if not rel:
        raise HTTPException(400, "Nós from_id ou to_id não encontrados")
    return rel.to_dict()


@router_graph.get("/relationships")
async def find_rels(from_id: str = "", to_id: str = "", rel_type: str = ""):
    rels = graph_db.find_rels(from_id=from_id, to_id=to_id, rel_type=rel_type)
    return {"relationships": [r.to_dict() for r in rels]}


@router_graph.delete("/relationships/{rel_id}")
async def delete_rel(rel_id: str):
    ok = graph_db.delete_rel(rel_id)
    if not ok:
        raise HTTPException(404, "Relationship não encontrado")
    return {"status": "deleted", "id": rel_id}


# ── Traversal ─────────────────────────────────────────────────

@router_graph.post("/traverse")
async def traverse(req: TraversalRequest):
    """Traversal BFS a partir de um nó."""
    results = graph_db.neighbors(
        node_id=req.node_id, direction=req.direction,
        rel_type=req.rel_type, depth=req.depth,
    )
    return {"from": req.node_id, "results": results, "count": len(results)}


@router_graph.get("/path/{from_id}/{to_id}")
async def shortest_path(from_id: str, to_id: str, max_depth: int = 8):
    """Caminho mais curto entre dois nós."""
    path = graph_db.shortest_path(from_id, to_id, max_depth)
    return {"from": from_id, "to": to_id, "path": path, "length": len(path)-1}


@router_graph.get("/reachable/{node_id}")
async def reachable(node_id: str, max_depth: int = 4):
    """Todos os nós alcançáveis a partir de um nó."""
    nodes = graph_db.reachable(node_id, max_depth)
    return {"from": node_id, "nodes": [n.to_dict() for n in nodes], "count": len(nodes)}


@router_graph.post("/subgraph")
async def get_subgraph(body: dict):
    """Subgrafo induzido pelos nós fornecidos."""
    node_ids = body.get("node_ids", [])
    return graph_db.subgraph(node_ids)


# ── Analytics ─────────────────────────────────────────────────

@router_graph.get("/stats")
async def graph_stats():
    return graph_db.stats()


@router_graph.get("/centrality")
async def centrality(top_k: int = 10):
    return {"centrality": graph_db.centrality(top_k)}


@router_graph.get("/degree/{node_id}")
async def node_degree(node_id: str):
    return graph_db.degree(node_id)


# ── Import / Export ───────────────────────────────────────────

@router_graph.post("/import/knowledge")
async def import_from_knowledge():
    """Importa todo o Knowledge Layer como grafo."""
    from backend.gateway.knowledge import knowledge_manager
    items = knowledge_manager.list(limit=500)
    result = graph_db.import_from_knowledge(items)
    return {**result, "status": "imported"}


@router_graph.get("/export/cytoscape")
async def export_cytoscape(label: str = "", limit: int = 200):
    """Exporta grafo no formato Cytoscape.js."""
    return graph_db.to_cytoscape(label_filter=label, limit=limit)


@router_graph.get("/export/d3")
async def export_d3(limit: int = 150):
    """Exporta grafo no formato D3.js force simulation."""
    return graph_db.to_d3(limit=limit)


# ── Schema info ───────────────────────────────────────────────

@router_graph.get("/schema")
async def graph_schema():
    return {
        "labels":    ["Story","Requirement","AcceptanceCriteria","TestCase",
                      "Risk","Defect","Pattern","Scenario","Insight","Term"],
        "rel_types": graph_db.REL_TYPES,
    }
