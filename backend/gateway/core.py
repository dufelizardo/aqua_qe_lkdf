"""
AQuA-QE LKDF — AI Gateway Layer
Gateway Core: roteamento inteligente, fallback automático, observabilidade
"""
from __future__ import annotations
import asyncio
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from backend.models.schemas import (
    ProviderConfig, GatewayRequest, GatewayResponse,
    ExecutionLog, GatewayStats, ProviderName, EngineType,
    DeploymentMode, RequestStatus, RoutingStrategy
)
from backend.providers.registry import DEFAULT_PROVIDERS, DEFAULT_ENGINE_ROUTING
from backend.providers.adapters import create_adapter, BaseProviderAdapter
from backend.gateway.observability import (
    observability, compute_confidence, classify_error, prompt_hash
)
from backend.gateway.security import security_gateway


# ─────────────────────────────────────────────
# Gateway State
# ─────────────────────────────────────────────

class GatewayState:
    """Estado mutável do gateway (providers, logs, estatísticas)."""

    def __init__(self):
        # Provider configs (mutável pelo usuário via API)
        self.providers: dict[ProviderName, ProviderConfig] = dict(DEFAULT_PROVIDERS)

        # Engine routing table
        self.engine_routing: dict = dict(DEFAULT_ENGINE_ROUTING)

        # Deployment mode atual
        self.deployment_mode: DeploymentMode = DeploymentMode.CLOUD

        # Execution logs (circular buffer)
        self.logs: deque[ExecutionLog] = deque(maxlen=500)

        # Adapters cache
        self._adapters: dict[ProviderName, BaseProviderAdapter] = {}

        # Health status cache (provider → bool)
        self._health_cache: dict[ProviderName, tuple[bool, datetime]] = {}
        self._health_ttl = timedelta(minutes=2)

    def get_adapter(self, provider: ProviderName) -> BaseProviderAdapter:
        config = self.providers[provider]
        # Recria adapter se config mudou
        if provider not in self._adapters:
            self._adapters[provider] = create_adapter(config)
        return self._adapters[provider]

    def invalidate_adapter(self, provider: ProviderName):
        self._adapters.pop(provider, None)

    def add_log(self, log: ExecutionLog):
        self.logs.appendleft(log)

    def get_stats(self) -> GatewayStats:
        logs = list(self.logs)
        if not logs:
            return GatewayStats()

        total = len(logs)
        successes = sum(1 for l in logs if l.status in (RequestStatus.SUCCESS, RequestStatus.FALLBACK))
        fallbacks  = sum(1 for l in logs if l.status == RequestStatus.FALLBACK)
        total_latency = sum(l.latency_ms for l in logs)
        total_cost    = sum(l.cost_usd for l in logs)
        total_in   = sum(l.input_tokens for l in logs)
        total_out  = sum(l.output_tokens for l in logs)

        by_provider: dict[str, int] = defaultdict(int)
        by_engine:   dict[str, int] = defaultdict(int)
        cost_by_prov: dict[str, float] = defaultdict(float)

        for l in logs:
            by_provider[l.provider.value] += 1
            by_engine[l.engine.value]     += 1
            cost_by_prov[l.provider.value] += l.cost_usd

        return GatewayStats(
            total_requests=total,
            success_rate=round(successes / total * 100, 1) if total else 0,
            fallback_rate=round(fallbacks / total * 100, 1) if total else 0,
            avg_latency_ms=round(total_latency / total, 1) if total else 0,
            total_cost_usd=round(total_cost, 6),
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            requests_by_provider=dict(by_provider),
            requests_by_engine=dict(by_engine),
            cost_by_provider={k: round(v, 6) for k, v in cost_by_prov.items()},
        )


# ─────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────

class GatewayRouter:
    """Resolve qual provider/modelo usar para cada request."""

    def __init__(self, state: GatewayState):
        self.state = state

    def resolve(self, request: GatewayRequest) -> list[tuple[ProviderName, str]]:
        """
        Retorna lista ordenada de (provider, model) para tentar.
        O primeiro é o primário; o restante são fallbacks.
        """
        mode = request.deployment_mode

        # Force override
        if request.force_provider:
            provider = request.force_provider
            config = self.state.providers[provider]
            model = request.metadata.get("model_override", config.default_model)
            return [(provider, model)]

        routing = self.state.engine_routing.get(request.engine, {})
        primary_provider = routing.get("primary", ProviderName.ANTHROPIC)
        primary_model    = routing.get("model", "")
        fallbacks        = routing.get("fallbacks", [])
        strategy         = routing.get("strategy", RoutingStrategy.CAPABILITY_MATCH)

        candidates = [(primary_provider, primary_model)]
        for fb in fallbacks:
            fb_config = self.state.providers.get(fb)
            if fb_config:
                candidates.append((fb, fb_config.default_model))

        # Filtrar por deployment mode
        filtered = self._filter_by_mode(candidates, mode)

        # Re-ordenar por estratégia
        ordered = self._apply_strategy(filtered, strategy)

        return ordered or candidates[:1]

    def _filter_by_mode(
        self,
        candidates: list[tuple[ProviderName, str]],
        mode: DeploymentMode,
    ) -> list[tuple[ProviderName, str]]:
        from backend.models.schemas import ProviderType
        result = []
        for (pname, model) in candidates:
            config = self.state.providers.get(pname)
            if not config or not config.enabled:
                continue
            if mode == DeploymentMode.CLOUD and config.provider_type != ProviderType.CLOUD:
                continue
            if mode == DeploymentMode.LOCAL and config.provider_type != ProviderType.LOCAL:
                continue
            result.append((pname, model))
        return result

    def _apply_strategy(
        self,
        candidates: list[tuple[ProviderName, str]],
        strategy: RoutingStrategy,
    ) -> list[tuple[ProviderName, str]]:
        def cost_key(item):
            config = self.state.providers.get(item[0])
            return (config.cost_input_per_1k + config.cost_output_per_1k) if config else 999

        def prio_key(item):
            config = self.state.providers.get(item[0])
            return -(config.priority if config else 0)

        if strategy == RoutingStrategy.COST_OPTIMIZED:
            return sorted(candidates, key=cost_key)
        elif strategy == RoutingStrategy.PERFORMANCE_FIRST:
            return sorted(candidates, key=prio_key)
        elif strategy == RoutingStrategy.PRIVACY_FIRST:
            from backend.models.schemas import ProviderType
            local_first = [c for c in candidates
                           if self.state.providers.get(c[0], ProviderConfig(
                               name=c[0], provider_type=ProviderType.CLOUD,
                               display_name="")).provider_type == ProviderType.LOCAL]
            cloud = [c for c in candidates if c not in local_first]
            return local_first + cloud
        return candidates


# ─────────────────────────────────────────────
# Health Monitor
# ─────────────────────────────────────────────

class HealthMonitor:
    def __init__(self, state: GatewayState):
        self.state = state

    async def check_provider(self, provider: ProviderName) -> bool:
        # Cache TTL
        cached = self.state._health_cache.get(provider)
        if cached and (datetime.utcnow() - cached[1]) < self.state._health_ttl:
            return cached[0]

        config = self.state.providers.get(provider)
        if not config or not config.enabled:
            return False

        try:
            adapter = self.state.get_adapter(provider)
            healthy = await adapter.health_check()
        except Exception:
            healthy = False

        self.state._health_cache[provider] = (healthy, datetime.utcnow())
        config.is_healthy = healthy
        config.last_health_check = datetime.utcnow()
        if not healthy:
            config.consecutive_failures += 1
        else:
            config.consecutive_failures = 0

        return healthy

    async def check_all(self) -> dict[str, bool]:
        tasks = {
            pname: self.check_provider(pname)
            for pname, cfg in self.state.providers.items()
            if cfg.enabled
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            str(pname): (result if isinstance(result, bool) else False)
            for pname, result in zip(tasks.keys(), results)
        }


# ─────────────────────────────────────────────
# AI Gateway — Main Orchestrator
# ─────────────────────────────────────────────

class AIGateway:
    """
    Ponto central de orquestração de IA do AQuA-QE.
    Responsável por roteamento, fallback, execução e observabilidade.
    """

    def __init__(self):
        self.state   = GatewayState()
        self.router  = GatewayRouter(self.state)
        self.monitor = HealthMonitor(self.state)

    # ── Public API ──────────────────────────

    async def execute(self, request: GatewayRequest) -> GatewayResponse:
        """Executa request com roteamento inteligente, segurança e fallback automático."""
        candidates = self.router.resolve(request)
        last_response: GatewayResponse | None = None
        tried: list[ProviderName] = []

        # §30 Security inspection — inspect & optionally mask content
        user_content = " ".join(m.get("content", "") for m in request.messages)
        sec_result = security_gateway.inspect_request(
            content=user_content,
            provider=str(candidates[0][0]) if candidates else "",
            engine=str(request.engine),
            session_id=request.metadata.get("session_id"),
        )
        if not sec_result["allowed"]:
            return GatewayResponse(
                request_id=request.id, engine=request.engine,
                provider_used=candidates[0][0] if candidates else ProviderName.ANTHROPIC,
                model_used="blocked", status=RequestStatus.FAILED,
                content=f"[Bloqueado por política de segurança: {sec_result['action_taken']}]",
                input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
                error_message=f"security_block:{sec_result['action_taken']}",
            )
        # Apply masking if content was modified
        if sec_result["action_taken"] == "masked" and request.messages:
            last_msg = request.messages[-1]
            if last_msg.get("role") == "user":
                request.messages[-1] = {**last_msg, "content": sec_result["masked_content"]}

        for i, (provider_name, model) in enumerate(candidates):
            request.metadata["resolved_model"] = model
            is_fallback = i > 0

            try:
                adapter = self.state.get_adapter(provider_name)
                response = await adapter.complete(request)
            except Exception as e:
                response = GatewayResponse(
                    request_id=request.id,
                    engine=request.engine,
                    provider_used=provider_name,
                    model_used=model,
                    status=RequestStatus.FAILED,
                    content="",
                    error_message=str(e),
                )

            if is_fallback:
                response.fallback_used = True
                response.fallback_from = tried[-1] if tried else None
                if response.status == RequestStatus.SUCCESS:
                    response.status = RequestStatus.FALLBACK

            tried.append(provider_name)
            last_response = response

            # Log sempre
            self._log(response, request)

            # Se success ou fallback-success → retorna
            if response.status in (RequestStatus.SUCCESS, RequestStatus.FALLBACK):
                return response

        # Todos falharam
        if last_response:
            return last_response

        return GatewayResponse(
            request_id=request.id,
            engine=request.engine,
            provider_used=ProviderName.ANTHROPIC,
            model_used="none",
            status=RequestStatus.FAILED,
            content="",
            error_message="All providers failed",
        )

    def update_provider(self, provider: ProviderName, updates: dict) -> ProviderConfig:
        config = self.state.providers[provider]
        for k, v in updates.items():
            if hasattr(config, k):
                setattr(config, k, v)
        self.state.invalidate_adapter(provider)
        return config

    def update_engine_routing(self, engine: EngineType, routing: dict):
        self.state.engine_routing[engine] = routing

    def set_deployment_mode(self, mode: DeploymentMode):
        self.state.deployment_mode = mode

    def get_logs(self, limit: int = 50) -> list[ExecutionLog]:
        return list(self.state.logs)[:limit]

    def get_stats(self) -> GatewayStats:
        return self.state.get_stats()

    async def health_all(self) -> dict[str, bool]:
        return await self.monitor.check_all()

    async def health_provider(self, provider: ProviderName) -> bool:
        return await self.monitor.check_provider(provider)

    # ── Internal ────────────────────────────

    def _log(self, response: GatewayResponse, request: GatewayRequest):
        status_str = str(response.status.value if hasattr(response.status, 'value') else response.status)
        confidence = compute_confidence(
            status_str, response.fallback_used,
            response.error_message, response.latency_ms,
        )
        error_type = classify_error(response.error_message)
        phash      = prompt_hash(request.system_prompt)

        log = ExecutionLog(
            request_id=response.request_id,
            engine=response.engine,
            provider=response.provider_used,
            model=response.model_used,
            status=response.status,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            fallback_used=response.fallback_used,
            fallback_from=str(response.fallback_from) if response.fallback_from else None,
            error=response.error_message,
            # Enriched observability fields
            confidence_score=confidence,
            error_type=error_type,
            prompt_hash=phash,
            system_prompt_len=len(request.system_prompt or ''),
            user_prompt_len=sum(len(m.get('content','')) for m in request.messages),
            deployment_mode=str(request.deployment_mode.value if hasattr(request.deployment_mode,'value') else request.deployment_mode),
            session_id=request.metadata.get('session_id'),
            user_label=request.metadata.get('label'),
        )
        self.state.add_log(log)
        observability.record(log)  # forward to observability manager


# Singleton global
gateway = AIGateway()
