"""
AQuA-QE LKDF — AI Gateway Layer
FastAPI Application: todos os endpoints REST do gateway
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.gateway.core import gateway
from backend.models.schemas import (
    GatewayRequest, ProviderName, EngineType,
    DeploymentMode, RoutingStrategy, ProviderType
)


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

app = FastAPI(
    title="AQuA-QE AI Gateway",
    description="AI Gateway Layer — Multi-provider, fallback, observabilidade",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Request / Response DTOs
# ─────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    engine: EngineType
    content: str
    system_prompt: Optional[str] = None
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD
    force_provider: Optional[ProviderName] = None
    model_override: Optional[str] = None
    max_tokens: int = 2000
    temperature: float = 0.3


class ProviderUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    default_model: Optional[str] = None
    timeout_seconds: Optional[int] = None


class EngineRoutingUpdateRequest(BaseModel):
    primary_provider: ProviderName
    primary_model: str
    fallback_providers: list[ProviderName] = []
    strategy: RoutingStrategy = RoutingStrategy.CAPABILITY_MATCH


class DeploymentModeRequest(BaseModel):
    mode: DeploymentMode


# ─────────────────────────────────────────────
# Routes — Analysis
# ─────────────────────────────────────────────

@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest):
    """Executa análise via engine cognitiva com roteamento automático."""
    gw_request = GatewayRequest(
        engine=req.engine,
        messages=[{"role": "user", "content": req.content}],
        system_prompt=req.system_prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        deployment_mode=req.deployment_mode,
        force_provider=req.force_provider,
        metadata={"model_override": req.model_override} if req.model_override else {},
    )
    response = await gateway.execute(gw_request)
    return {
        "request_id": response.request_id,
        "engine": response.engine,
        "provider": response.provider_used,
        "model": response.model_used,
        "content": response.content,
        "status": response.status,
        "fallback_used": response.fallback_used,
        "fallback_from": response.fallback_from,
        "metrics": {
            "latency_ms": round(response.latency_ms, 1),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": response.cost_usd,
        },
        "error": response.error_message,
    }


@app.post("/api/v1/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """SSE streaming de análise."""
    async def event_stream():
        gw_request = GatewayRequest(
            engine=req.engine,
            messages=[{"role": "user", "content": req.content}],
            system_prompt=req.system_prompt,
            max_tokens=req.max_tokens,
            deployment_mode=req.deployment_mode,
            force_provider=req.force_provider,
        )
        yield f"data: {json.dumps({'event': 'start', 'engine': req.engine})}\n\n"
        response = await gateway.execute(gw_request)
        # Simula streaming por tokens
        words = response.content.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield f"data: {json.dumps({'event': 'token', 'token': chunk})}\n\n"
            await asyncio.sleep(0.01)
        yield f"data: {json.dumps({'event': 'done', 'provider': str(response.provider_used), 'cost': response.cost_usd})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────
# Routes — Providers
# ─────────────────────────────────────────────

@app.get("/api/v1/providers")
async def list_providers():
    """Lista todos os providers configurados."""
    providers = []
    for name, cfg in gateway.state.providers.items():
        providers.append({
            "name": cfg.name,
            "display_name": cfg.display_name,
            "type": cfg.provider_type,
            "enabled": cfg.enabled,
            "priority": cfg.priority,
            "is_healthy": cfg.is_healthy,
            "last_health_check": cfg.last_health_check.isoformat() if cfg.last_health_check else None,
            "consecutive_failures": cfg.consecutive_failures,
            "available_models": cfg.available_models,
            "default_model": cfg.default_model,
            "cost_input_per_1k": cfg.cost_input_per_1k,
            "cost_output_per_1k": cfg.cost_output_per_1k,
            "max_context_tokens": cfg.max_context_tokens,
            "supports_streaming": cfg.supports_streaming,
            "supports_function_calling": cfg.supports_function_calling,
            "supports_vision": cfg.supports_vision,
            "has_api_key": bool(cfg.api_key),
            "base_url": cfg.base_url,
            "timeout_seconds": cfg.timeout_seconds,
        })
    return {"providers": providers, "total": len(providers)}


@app.patch("/api/v1/providers/{provider_name}")
async def update_provider(provider_name: str, req: ProviderUpdateRequest):
    """Atualiza configuração de um provider."""
    try:
        pname = ProviderName(provider_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' não encontrado")

    updates = {k: v for k, v in req.dict().items() if v is not None}
    cfg = gateway.update_provider(pname, updates)
    return {"status": "updated", "provider": cfg.name}


@app.post("/api/v1/providers/{provider_name}/health")
async def check_provider_health(provider_name: str):
    """Força verificação de saúde de um provider."""
    try:
        pname = ProviderName(provider_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="Provider não encontrado")

    # Limpa cache para forçar novo check
    gateway.state._health_cache.pop(pname, None)
    healthy = await gateway.health_provider(pname)

    return {
        "provider": provider_name,
        "healthy": healthy,
        "checked_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/v1/providers/health/all")
async def check_all_health():
    """Verifica saúde de todos os providers habilitados."""
    # Limpa cache
    gateway.state._health_cache.clear()
    results = await gateway.health_all()
    healthy_count = sum(1 for v in results.values() if v)
    return {
        "results": results,
        "healthy": healthy_count,
        "total": len(results),
        "checked_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/v1/providers/ollama/models")
async def list_ollama_models():
    """Lista modelos instalados no Ollama."""
    from backend.providers.adapters import OllamaAdapter
    cfg = gateway.state.providers.get(ProviderName.OLLAMA)
    if not cfg:
        raise HTTPException(status_code=404, detail="Ollama não configurado")
    adapter = OllamaAdapter(cfg)
    models = await adapter.list_models()
    return {"models": models}


# ─────────────────────────────────────────────
# Routes — Engine Routing
# ─────────────────────────────────────────────

@app.get("/api/v1/routing")
async def get_routing():
    """Retorna tabela de roteamento por engine."""
    routing = {}
    for engine, cfg in gateway.state.engine_routing.items():
        routing[str(engine)] = {
            "engine": str(engine),
            "primary_provider": str(cfg.get("primary", "")),
            "primary_model": cfg.get("model", ""),
            "fallback_providers": [str(f) for f in cfg.get("fallbacks", [])],
            "strategy": str(cfg.get("strategy", "")),
        }
    return {"routing": routing}


@app.put("/api/v1/routing/{engine_name}")
async def update_engine_routing(engine_name: str, req: EngineRoutingUpdateRequest):
    """Atualiza roteamento de uma engine específica."""
    try:
        engine = EngineType(engine_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Engine '{engine_name}' não encontrada")

    gateway.update_engine_routing(engine, {
        "primary": req.primary_provider,
        "model": req.primary_model,
        "fallbacks": req.fallback_providers,
        "strategy": req.strategy,
    })
    return {"status": "updated", "engine": engine_name}


# ─────────────────────────────────────────────
# Routes — Deployment Mode
# ─────────────────────────────────────────────

@app.get("/api/v1/deployment")
async def get_deployment_mode():
    return {"mode": gateway.state.deployment_mode}


@app.put("/api/v1/deployment")
async def set_deployment_mode(req: DeploymentModeRequest):
    gateway.set_deployment_mode(req.mode)
    return {"status": "updated", "mode": req.mode}


# ─────────────────────────────────────────────
# Routes — Observability
# ─────────────────────────────────────────────

@app.get("/api/v1/stats")
async def get_stats():
    """Estatísticas consolidadas do gateway."""
    stats = gateway.get_stats()
    return stats.dict()


@app.get("/api/v1/logs")
async def get_logs(limit: int = 50):
    """Logs de execução recentes."""
    logs = gateway.get_logs(limit)
    return {
        "logs": [
            {
                "id": l.id,
                "request_id": l.request_id,
                "engine": l.engine,
                "provider": l.provider,
                "model": l.model,
                "status": l.status,
                "input_tokens": l.input_tokens,
                "output_tokens": l.output_tokens,
                "latency_ms": round(l.latency_ms, 1),
                "cost_usd": l.cost_usd,
                "fallback_used": l.fallback_used,
                "error": l.error,
                "timestamp": l.timestamp.isoformat(),
            }
            for l in logs
        ],
        "total": len(logs),
    }


@app.delete("/api/v1/logs")
async def clear_logs():
    gateway.state.logs.clear()
    return {"status": "cleared"}


# ─────────────────────────────────────────────
# Routes — Gateway Info
# ─────────────────────────────────────────────

@app.get("/api/v1/info")
async def gateway_info():
    return {
        "name": "AQuA-QE AI Gateway",
        "version": "2.0.0",
        "deployment_mode": gateway.state.deployment_mode,
        "providers_total": len(gateway.state.providers),
        "providers_enabled": sum(1 for c in gateway.state.providers.values() if c.enabled),
        "engines_total": len(EngineType),
        "logs_buffered": len(gateway.state.logs),
        "uptime": "active",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "aqua-qe-gateway"}


# ─────────────────────────────────────────────
# WebSocket — Live monitoring
# ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        for ws in self.active[:]:
            try:
                await ws.send_json(data)
            except Exception:
                self.active.remove(ws)


ws_manager = ConnectionManager()


@app.websocket("/ws/gateway")
async def ws_gateway(websocket: WebSocket):
    """WebSocket para monitoramento em tempo real."""
    await ws_manager.connect(websocket)
    try:
        # Envia estado inicial
        await websocket.send_json({
            "type": "init",
            "stats": gateway.get_stats().dict(),
            "deployment_mode": gateway.state.deployment_mode,
        })
        while True:
            # Aguarda mensagem do cliente ou envia heartbeat
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif data.get("type") == "stats":
                    await websocket.send_json({
                        "type": "stats",
                        "stats": gateway.get_stats().dict(),
                    })
            except asyncio.TimeoutError:
                # Heartbeat automático a cada 5s
                await websocket.send_json({
                    "type": "heartbeat",
                    "stats": gateway.get_stats().dict(),
                    "ts": datetime.utcnow().isoformat(),
                })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)



# ─────────────────────────────────────────────
# Proxy Endpoint — resolve CORS para chamadas diretas do browser
# ─────────────────────────────────────────────

class ProxyRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: ProviderName
    model_id: str
    messages: list[dict]
    system_prompt: Optional[str] = None
    api_key: str
    max_tokens: int = 4000
    temperature: float = 0.3


@app.post("/api/v1/proxy/chat")
async def proxy_chat(req: ProxyRequest):
    """
    Proxy para chamadas diretas ao provider — resolve CORS.
    A API key é enviada pelo frontend e usada apenas nesta chamada,
    não é armazenada no servidor.
    """
    import httpx, time

    prov  = req.provider
    key   = req.api_key
    model = req.model_id
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=90) as client:

            # ── Anthropic ────────────────────────────────────────
            if prov == ProviderName.ANTHROPIC:
                payload: dict = {
                    "model": model,
                    "max_tokens": req.max_tokens,
                    "messages": req.messages,
                }
                if req.system_prompt:
                    payload["system"] = req.system_prompt
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
                if not resp.is_success:
                    raise HTTPException(status_code=resp.status_code,
                                        detail=f"Anthropic: {resp.text[:300]}")
                data  = resp.json()
                text  = data["content"][0]["text"]
                usage = data.get("usage", {})
                return {
                    "content": text,
                    "provider": prov,
                    "model": model,
                    "input_tokens":  usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                    "cost_usd": (usage.get("input_tokens",0)/1000)*0.003
                              + (usage.get("output_tokens",0)/1000)*0.015,
                }

            # ── Google Gemini ─────────────────────────────────────
            elif prov == ProviderName.GOOGLE:
                # Normalize aliases
                _ALIASES = {"gemini-pro": "gemini-1.5-pro", "gemini-flash": "gemini-2.0-flash"}
                model = _ALIASES.get(model, model)
                contents = [
                    {"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]}
                    for m in req.messages
                ]
                if not contents or contents[0]["role"] != "user":
                    contents.insert(0, {"role": "user", "parts": [{"text": "Olá"}]})
                body: dict = {
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": req.max_tokens,
                        "temperature": req.temperature,
                    },
                }
                if req.system_prompt:
                    body["systemInstruction"] = {"parts": [{"text": req.system_prompt}]}
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                    json=body,
                    headers={"content-type": "application/json"},
                )
                if not resp.is_success:
                    err = resp.json().get("error", {}).get("message", resp.text[:200])
                    raise HTTPException(status_code=resp.status_code, detail=f"Gemini: {err}")
                data  = resp.json()
                text  = data["candidates"][0]["content"]["parts"][0]["text"]
                usage = data.get("usageMetadata", {})
                inp   = usage.get("promptTokenCount", 0)
                out   = usage.get("candidatesTokenCount", 0)
                return {
                    "content": text,
                    "provider": prov,
                    "model": model,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                    "cost_usd": (inp/1000)*0.0001 + (out/1000)*0.0004,
                }

            # ── OpenAI-compatible (openai, groq, mistral) ─────────
            else:
                endpoints = {
                    ProviderName.OPENAI:   "https://api.openai.com/v1/chat/completions",
                    ProviderName.GROQ:     "https://api.groq.com/openai/v1/chat/completions",
                    ProviderName.MISTRAL:  "https://api.mistral.ai/v1/chat/completions",
                }
                endpoint = endpoints.get(prov)
                if not endpoint:
                    raise HTTPException(status_code=400,
                                        detail=f"Provider '{prov}' não suportado no proxy direto")
                msgs = req.messages[:]
                if req.system_prompt:
                    msgs = [{"role": "system", "content": req.system_prompt}] + msgs
                resp = await client.post(
                    endpoint,
                    json={"model": model, "messages": msgs,
                          "max_tokens": req.max_tokens, "temperature": req.temperature},
                    headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                )
                if not resp.is_success:
                    raise HTTPException(status_code=resp.status_code,
                                        detail=f"{prov}: {resp.text[:300]}")
                data  = resp.json()
                text  = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                costs = {
                    ProviderName.OPENAI:  (0.005, 0.015),
                    ProviderName.GROQ:    (0.00059, 0.00079),
                    ProviderName.MISTRAL: (0.004, 0.012),
                }
                ci, co = costs.get(prov, (0, 0))
                inp = usage.get("prompt_tokens", 0)
                out = usage.get("completion_tokens", 0)
                return {
                    "content": text,
                    "provider": prov,
                    "model": model,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                    "cost_usd": (inp/1000)*ci + (out/1000)*co,
                }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)[:200]}")


# ─────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    print("🔌 AQuA-QE AI Gateway iniciando...")
    print(f"   Providers: {len(gateway.state.providers)}")
    print(f"   Engines:   {len(EngineType)}")
    print("✅ Gateway pronto.")
