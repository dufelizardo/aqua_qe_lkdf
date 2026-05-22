"""
ai_engine/gateway/gateway.py
AQuA-QE LKDF v1.4 — AI Gateway

Abstração multi-LLM com:
  - Roteamento inteligente por tarefa e custo
  - Fallback automático entre providers
  - Batch de chamadas no Fan-Out pipeline
  - Auditoria e controle de custo por execução
  - Retry com backoff exponencial
  - Suporte: Claude (Anthropic) · OpenAI · Gemini · modelos locais (Ollama)
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI    = "openai"
    GEMINI    = "gemini"
    OLLAMA    = "ollama"    # modelos locais


class TaskType(str, Enum):
    """Tipo de tarefa — usado pelo router para escolher provider e modelo."""
    REQUIREMENT_ANALYSIS  = "requirement_analysis"   # reasoning complexo → Claude Sonnet
    SCENARIO_GENERATION   = "scenario_generation"    # geração estruturada → Claude Haiku / GPT-4o-mini
    AMBIGUITY_DETECTION   = "ambiguity_detection"    # análise linguística → Claude Haiku
    CODE_GENERATION       = "code_generation"        # geração de código → GPT-4o / Claude Sonnet
    EMBEDDING             = "embedding"              # embeddings → text-embedding-3-small
    CLASSIFICATION        = "classification"         # classificação rápida → modelos locais
    CHAT                  = "chat"                   # uso geral → configurável


@dataclass
class LLMConfig:
    """Configuração de um provider específico."""
    provider:      LLMProvider
    model:         str
    api_key:       str          = ""
    base_url:      str          = ""           # para Ollama ou proxies
    max_tokens:    int          = 2000
    temperature:   float        = 0.2
    timeout_s:     int          = 60
    cost_per_1k_input:  float   = 0.0          # USD por 1k tokens de entrada
    cost_per_1k_output: float   = 0.0          # USD por 1k tokens de saída


@dataclass
class LLMRequest:
    """Requisição normalizada para qualquer provider."""
    id:            UUID         = field(default_factory=uuid4)
    task_type:     TaskType     = TaskType.CHAT
    system:        str          = ""
    messages:      list[dict]   = field(default_factory=list)
    max_tokens:    int          = 2000
    temperature:   float        = 0.2
    json_mode:     bool         = False        # force JSON output
    metadata:      dict         = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Resposta normalizada de qualquer provider."""
    request_id:    UUID
    provider:      LLMProvider
    model:         str
    content:       str
    input_tokens:  int          = 0
    output_tokens: int          = 0
    latency_ms:    int          = 0
    cost_usd:      float        = 0.0
    raw:           dict         = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class GatewayAuditEntry:
    """Log de auditoria de cada chamada via Gateway."""
    request_id:   UUID
    task_type:    TaskType
    provider:     LLMProvider
    model:        str
    success:      bool
    latency_ms:   int
    cost_usd:     float
    error:        str         = ""
    timestamp:    float       = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Provider clients (lazy imports — só instala o que usar)
# ---------------------------------------------------------------------------

class _AnthropicClient:
    def __init__(self, config: LLMConfig) -> None:
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self._config = config

    async def complete(self, req: LLMRequest) -> LLMResponse:
        t0 = time.perf_counter()
        resp = await self._client.messages.create(
            model=self._config.model,
            max_tokens=req.max_tokens,
            system=req.system,
            messages=req.messages,
            temperature=req.temperature,
        )
        ms   = int((time.perf_counter() - t0) * 1000)
        text = resp.content[0].text if resp.content else ""
        inp  = resp.usage.input_tokens
        out  = resp.usage.output_tokens
        cost = (inp / 1000 * self._config.cost_per_1k_input
                + out / 1000 * self._config.cost_per_1k_output)
        return LLMResponse(
            request_id=req.id, provider=LLMProvider.ANTHROPIC,
            model=self._config.model, content=text,
            input_tokens=inp, output_tokens=out,
            latency_ms=ms, cost_usd=cost, raw=resp.model_dump(),
        )


class _OpenAIClient:
    def __init__(self, config: LLMConfig) -> None:
        import openai
        self._client = openai.AsyncOpenAI(api_key=config.api_key)
        self._config = config

    async def complete(self, req: LLMRequest) -> LLMResponse:
        t0 = time.perf_counter()
        msgs = ([{"role": "system", "content": req.system}] if req.system else []) + req.messages
        kwargs: dict[str, Any] = dict(
            model=self._config.model,
            messages=msgs,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        if req.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        ms   = int((time.perf_counter() - t0) * 1000)
        text = resp.choices[0].message.content or ""
        inp  = resp.usage.prompt_tokens
        out  = resp.usage.completion_tokens
        cost = (inp / 1000 * self._config.cost_per_1k_input
                + out / 1000 * self._config.cost_per_1k_output)
        return LLMResponse(
            request_id=req.id, provider=LLMProvider.OPENAI,
            model=self._config.model, content=text,
            input_tokens=inp, output_tokens=out,
            latency_ms=ms, cost_usd=cost,
        )


class _OllamaClient:
    """Modelos locais via Ollama REST API."""
    def __init__(self, config: LLMConfig) -> None:
        import httpx
        self._http   = httpx.AsyncClient(base_url=config.base_url or "http://localhost:11434")
        self._config = config

    async def complete(self, req: LLMRequest) -> LLMResponse:
        t0   = time.perf_counter()
        body = {
            "model":  self._config.model,
            "prompt": req.messages[-1]["content"] if req.messages else "",
            "system": req.system,
            "stream": False,
            "options": {"temperature": req.temperature},
        }
        resp = await self._http.post("/api/generate", json=body, timeout=self._config.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        ms   = int((time.perf_counter() - t0) * 1000)
        return LLMResponse(
            request_id=req.id, provider=LLMProvider.OLLAMA,
            model=self._config.model, content=data.get("response", ""),
            latency_ms=ms, cost_usd=0.0, raw=data,
        )


# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------

_DEFAULT_ROUTING: dict[TaskType, LLMProvider] = {
    TaskType.REQUIREMENT_ANALYSIS: LLMProvider.ANTHROPIC,
    TaskType.SCENARIO_GENERATION:  LLMProvider.ANTHROPIC,
    TaskType.AMBIGUITY_DETECTION:  LLMProvider.ANTHROPIC,
    TaskType.CODE_GENERATION:      LLMProvider.ANTHROPIC,
    TaskType.EMBEDDING:            LLMProvider.OPENAI,
    TaskType.CLASSIFICATION:       LLMProvider.OLLAMA,
    TaskType.CHAT:                 LLMProvider.ANTHROPIC,
}


# ---------------------------------------------------------------------------
# AI Gateway
# ---------------------------------------------------------------------------

class AIGateway:
    """
    Gateway central de IA do LKDF v1.4.

    Uso:
        gw = AIGateway()
        gw.register(LLMConfig(provider=ANTHROPIC, model="claude-sonnet-4-20250514",
                               api_key=os.getenv("ANTHROPIC_API_KEY"),
                               cost_per_1k_input=0.003, cost_per_1k_output=0.015))
        response = await gw.complete(LLMRequest(
            task_type=TaskType.REQUIREMENT_ANALYSIS,
            system="...", messages=[{"role":"user","content":"..."}]
        ))
    """

    def __init__(self) -> None:
        self._configs:  dict[LLMProvider, LLMConfig]  = {}
        self._clients:  dict[LLMProvider, Any]         = {}
        self._routing:  dict[TaskType, LLMProvider]    = dict(_DEFAULT_ROUTING)
        self._audit:    list[GatewayAuditEntry]         = []
        self._fallback_chain: list[LLMProvider]         = [
            LLMProvider.ANTHROPIC,
            LLMProvider.OPENAI,
            LLMProvider.OLLAMA,
        ]

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def register(self, config: LLMConfig) -> None:
        """Registra um provider com sua configuração."""
        self._configs[config.provider] = config
        self._clients.pop(config.provider, None)   # reset client cache
        log.info("ai_gateway_provider_registered", provider=config.provider, model=config.model)

    def set_routing(self, task_type: TaskType, provider: LLMProvider) -> None:
        """Sobrescreve o roteamento padrão para uma task específica."""
        self._routing[task_type] = provider

    def set_fallback_chain(self, chain: list[LLMProvider]) -> None:
        """Define a ordem de fallback entre providers."""
        self._fallback_chain = chain

    # ------------------------------------------------------------------
    # Core: complete
    # ------------------------------------------------------------------

    async def complete(
        self,
        request:  LLMRequest,
        provider: LLMProvider | None = None,
    ) -> LLMResponse:
        """
        Completa uma requisição com roteamento automático e fallback.
        """
        target = provider or self._routing.get(request.task_type, LLMProvider.ANTHROPIC)

        # Build fallback order: preferred → rest of chain (excluding preferred)
        chain = [target] + [p for p in self._fallback_chain if p != target]

        last_error: Exception | None = None
        for attempt_provider in chain:
            if attempt_provider not in self._configs:
                continue
            try:
                response = await self._call_with_retry(request, attempt_provider)
                self._audit_success(request, response)
                if attempt_provider != target:
                    log.warning("ai_gateway_fallback_used",
                                original=target, used=attempt_provider)
                return response
            except Exception as exc:
                last_error = exc
                self._audit_failure(request, attempt_provider, str(exc))
                log.warning("ai_gateway_provider_failed",
                            provider=attempt_provider, error=str(exc))

        raise RuntimeError(
            f"All AI providers failed for task '{request.task_type}'. "
            f"Last error: {last_error}"
        )

    async def complete_batch(
        self,
        requests: list[LLMRequest],
        max_concurrent: int = 5,
    ) -> list[LLMResponse]:
        """
        Executa múltiplas requisições em paralelo (Fan-Out).
        Usado pelo pipeline assíncrono do v1.4.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded(req: LLMRequest) -> LLMResponse:
            async with semaphore:
                return await self.complete(req)

        results = await asyncio.gather(
            *[_bounded(r) for r in requests],
            return_exceptions=True,
        )

        responses: list[LLMResponse] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.error("batch_item_failed", index=i, error=str(result))
                # Return empty response to not block the batch
                responses.append(LLMResponse(
                    request_id=requests[i].id,
                    provider=LLMProvider.ANTHROPIC,
                    model="unknown",
                    content="",
                ))
            else:
                responses.append(result)
        return responses

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        request:  LLMRequest,
        provider: LLMProvider,
        max_retries: int = 3,
    ) -> LLMResponse:
        client = self._get_client(provider)
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(
                    client.complete(request),
                    timeout=self._configs[provider].timeout_s,
                )
            except asyncio.TimeoutError as exc:
                last_exc = exc
                log.warning("ai_gateway_timeout", provider=provider, attempt=attempt)
            except Exception as exc:
                # Rate limit or transient error — exponential backoff
                if "rate" in str(exc).lower() or "429" in str(exc):
                    wait = 2 ** attempt
                    log.warning("ai_gateway_rate_limit", provider=provider, wait=wait)
                    await asyncio.sleep(wait)
                    last_exc = exc
                else:
                    raise

        raise last_exc or RuntimeError(f"Max retries exceeded for {provider}")

    # ------------------------------------------------------------------
    # Client factory
    # ------------------------------------------------------------------

    def _get_client(self, provider: LLMProvider) -> Any:
        if provider not in self._clients:
            config = self._configs.get(provider)
            if not config:
                raise RuntimeError(f"Provider '{provider}' not registered in AIGateway.")
            if provider == LLMProvider.ANTHROPIC:
                self._clients[provider] = _AnthropicClient(config)
            elif provider == LLMProvider.OPENAI:
                self._clients[provider] = _OpenAIClient(config)
            elif provider == LLMProvider.OLLAMA:
                self._clients[provider] = _OllamaClient(config)
            else:
                raise NotImplementedError(f"Provider '{provider}' not implemented yet.")
        return self._clients[provider]

    # ------------------------------------------------------------------
    # Audit & cost
    # ------------------------------------------------------------------

    def _audit_success(self, req: LLMRequest, resp: LLMResponse) -> None:
        self._audit.append(GatewayAuditEntry(
            request_id=req.id, task_type=req.task_type,
            provider=resp.provider, model=resp.model,
            success=True, latency_ms=resp.latency_ms, cost_usd=resp.cost_usd,
        ))

    def _audit_failure(
        self, req: LLMRequest, provider: LLMProvider, error: str
    ) -> None:
        self._audit.append(GatewayAuditEntry(
            request_id=req.id, task_type=req.task_type,
            provider=provider, model=self._configs.get(provider, LLMConfig(
                provider=provider, model="unknown"
            )).model,
            success=False, latency_ms=0, cost_usd=0.0, error=error,
        ))

    def cost_report(self) -> dict[str, Any]:
        """Relatório de custo acumulado por provider e task."""
        total_cost   = sum(e.cost_usd for e in self._audit if e.success)
        by_provider  = {}
        by_task      = {}
        for e in self._audit:
            if not e.success:
                continue
            by_provider[e.provider] = by_provider.get(e.provider, 0.0) + e.cost_usd
            by_task[e.task_type]    = by_task.get(e.task_type, 0.0) + e.cost_usd

        return {
            "total_calls":   len(self._audit),
            "successful":    sum(1 for e in self._audit if e.success),
            "failed":        sum(1 for e in self._audit if not e.success),
            "total_cost_usd": round(total_cost, 6),
            "by_provider":   {k.value: round(v, 6) for k, v in by_provider.items()},
            "by_task":       {k.value: round(v, 6) for k, v in by_task.items()},
            "avg_latency_ms": (
                sum(e.latency_ms for e in self._audit if e.success)
                // max(1, sum(1 for e in self._audit if e.success))
            ),
        }

    @property
    def audit_log(self) -> list[GatewayAuditEntry]:
        return list(self._audit)

    @property
    def registered_providers(self) -> list[LLMProvider]:
        return list(self._configs.keys())


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

def create_default_gateway() -> AIGateway:
    """
    Cria e configura o AIGateway padrão a partir de variáveis de ambiente.
    Registra apenas os providers que têm API key configurada.
    """
    gw = AIGateway()

    if key := os.getenv("ANTHROPIC_API_KEY"):
        gw.register(LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            api_key=key,
            max_tokens=2000,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
        ))

    if key := os.getenv("OPENAI_API_KEY"):
        gw.register(LLMConfig(
            provider=LLMProvider.OPENAI,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=key,
            max_tokens=2000,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
        ))

    ollama_url = os.getenv("OLLAMA_BASE_URL")
    if ollama_url:
        gw.register(LLMConfig(
            provider=LLMProvider.OLLAMA,
            model=os.getenv("OLLAMA_MODEL", "llama3"),
            base_url=ollama_url,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
        ))

    log.info("ai_gateway_created",
             providers=[p.value for p in gw.registered_providers])
    return gw
