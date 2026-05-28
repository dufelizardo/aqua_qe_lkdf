"""
AQuA-QE LKDF — CI/CD Routes §36 + WebSocket §35
"""
from __future__ import annotations
import asyncio
import json
import time
from typing import Any, Optional, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.gateway.cicd import cicd_exporter

router_cicd = APIRouter(prefix="/api/v1/cicd")


# ── DTOs ──────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    test_cases:    list[dict[str, Any]]
    format:        str = "github"   # github | gitlab | junit | robot | json
    project_name:  str = "AQuA-QE"
    branch:        str = "main"


# ── CI/CD Export ──────────────────────────────────────────────

@router_cicd.post("/export")
async def export_cicd(req: ExportRequest):
    """
    Exporta Casos de Teste para formatos de CI/CD.
    formats: github | gitlab | junit | robot | json
    """
    fmt = req.format.lower()
    if fmt == "github":
        content = cicd_exporter.to_github_actions(
            req.test_cases, req.project_name, req.branch
        )
        media_type = "text/yaml"
        filename   = "aqua-qe-workflow.yml"
    elif fmt == "gitlab":
        content = cicd_exporter.to_gitlab_ci(req.test_cases, req.project_name)
        media_type = "text/yaml"
        filename   = "aqua-qe-gitlab-ci.yml"
    elif fmt == "junit":
        content = cicd_exporter.to_junit_xml(req.test_cases, req.project_name)
        media_type = "application/xml"
        filename   = "aqua-qe-junit.xml"
    elif fmt == "robot":
        content = cicd_exporter.to_robot(req.test_cases, req.project_name)
        media_type = "text/plain"
        filename   = "aqua-qe-tests.robot"
    elif fmt == "json":
        content = cicd_exporter.to_json(req.test_cases, {"project": req.project_name})
        media_type = "application/json"
        filename   = "aqua-qe-tests.json"
    else:
        from fastapi import HTTPException
        raise HTTPException(400, f"Formato '{fmt}' não suportado. Use: github, gitlab, junit, robot, json")

    return PlainTextResponse(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router_cicd.get("/formats")
async def list_formats():
    """Lista formatos de exportação disponíveis."""
    return {
        "formats": [
            {"id": "github", "name": "GitHub Actions",     "ext": ".yml",   "description": "Workflow YAML com steps por CT"},
            {"id": "gitlab", "name": "GitLab CI",          "ext": ".yml",   "description": "Fragment .gitlab-ci.yml"},
            {"id": "junit",  "name": "JUnit XML",          "ext": ".xml",   "description": "Jenkins, CircleCI, Azure DevOps, Bamboo"},
            {"id": "robot",  "name": "Robot Framework",    "ext": ".robot", "description": "Arquivo de testes automatizados"},
            {"id": "json",   "name": "JSON (genérico)",    "ext": ".json",  "description": "Integração customizada"},
        ]
    }


# ── WebSocket — Live Events §35 ───────────────────────────────

class ConnectionManager:
    """Gerencia conexões WebSocket ativas."""

    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        msg  = json.dumps(data)
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.active -= dead

    async def send_to(self, ws: WebSocket, data: dict):
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            self.disconnect(ws)


ws_manager = ConnectionManager()


def get_ws_router():
    ws_router = APIRouter()

    @ws_router.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket):
        """
        WebSocket para eventos em tempo real do gateway.

        Eventos emitidos pelo servidor:
          { "event": "gateway_stats",    "data": {...} }
          { "event": "new_log",          "data": ExecutionLog }
          { "event": "new_knowledge",    "data": KnowledgeItem }
          { "event": "provider_health",  "data": {"provider": ..., "healthy": bool} }

        Mensagens aceitas do cliente:
          { "action": "subscribe",   "topics": ["logs","stats","knowledge"] }
          { "action": "ping" }
        """
        await ws_manager.connect(websocket)
        subscriptions = {"logs", "stats", "knowledge"}

        try:
            # Send welcome
            await ws_manager.send_to(websocket, {
                "event": "connected",
                "data": {
                    "message": "AQuA-QE Gateway WebSocket connected",
                    "topics":  list(subscriptions),
                    "timestamp": time.time(),
                }
            })

            # Background: push stats every 5s
            async def push_stats():
                while True:
                    try:
                        from backend.gateway.core import gateway
                        from backend.gateway.rag import rag_engine
                        s = gateway.get_stats()
                        await ws_manager.send_to(websocket, {
                            "event": "gateway_stats",
                            "data": {
                                "total_requests":  s.total_requests,
                                "success_rate":    s.success_rate,
                                "total_cost_usd":  s.total_cost_usd,
                                "active_providers":s.provider_stats,
                                "rag_indexed":     rag_engine.stats()["indices"]["knowledge"],
                                "timestamp":       time.time(),
                            }
                        })
                    except Exception:
                        pass
                    await asyncio.sleep(5)

            stats_task = asyncio.create_task(push_stats())

            # Listen for client messages
            while True:
                try:
                    raw  = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    msg  = json.loads(raw)
                    action = msg.get("action","")

                    if action == "ping":
                        await ws_manager.send_to(websocket, {"event": "pong", "data": {"ts": time.time()}})

                    elif action == "subscribe":
                        topics = set(msg.get("topics", []))
                        subscriptions.update(topics)
                        await ws_manager.send_to(websocket, {
                            "event": "subscribed",
                            "data": {"topics": list(subscriptions)}
                        })

                    elif action == "rag_search":
                        query = msg.get("query","")
                        if query:
                            from backend.gateway.rag import rag_engine
                            results = rag_engine.retrieve(query, top_k=5)
                            await ws_manager.send_to(websocket, {
                                "event": "rag_results",
                                "data": {"query": query, "results": results}
                            })

                except asyncio.TimeoutError:
                    # Send heartbeat
                    await ws_manager.send_to(websocket, {"event": "heartbeat", "data": {"ts": time.time()}})
                except (json.JSONDecodeError, KeyError):
                    pass

        except WebSocketDisconnect:
            pass
        finally:
            stats_task.cancel()
            ws_manager.disconnect(websocket)

    @ws_router.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        """WebSocket dedicado ao stream de logs de execução em tempo real."""
        await ws_manager.connect(websocket)
        try:
            await ws_manager.send_to(websocket, {"event":"connected","data":{"topic":"logs"}})
            last_idx = 0
            while True:
                await asyncio.sleep(1)
                try:
                    from backend.gateway.core import gateway
                    logs = list(gateway.state.logs)
                    new_logs = logs[:max(0, len(logs) - last_idx)]
                    if new_logs:
                        for log in reversed(new_logs):
                            await ws_manager.send_to(websocket, {
                                "event": "new_log",
                                "data": {
                                    "id":       getattr(log, "id","")[:8],
                                    "engine":   str(log.engine),
                                    "provider": str(log.provider),
                                    "model":    log.model,
                                    "status":   str(log.status),
                                    "latency":  log.latency_ms,
                                    "cost":     log.cost_usd,
                                    "fallback": log.fallback_used,
                                    "ts":       time.time(),
                                }
                            })
                        last_idx = len(logs)
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            ws_manager.disconnect(websocket)

    return ws_router


ws_router = get_ws_router()


# ── Broadcast helpers (called from gateway core) ──────────────

async def broadcast_new_log(log) -> None:
    if not ws_manager.active:
        return
    await ws_manager.broadcast({
        "event": "new_log",
        "data": {
            "engine":   str(log.engine),
            "provider": str(log.provider),
            "status":   str(log.status),
            "latency":  log.latency_ms,
            "cost":     log.cost_usd,
            "ts":       time.time(),
        }
    })


async def broadcast_knowledge_item(item: dict) -> None:
    if not ws_manager.active:
        return
    await ws_manager.broadcast({
        "event": "new_knowledge",
        "data": {
            "type":  item.get("type",""),
            "title": item.get("title","")[:80],
            "id":    item.get("id",""),
        }
    })
