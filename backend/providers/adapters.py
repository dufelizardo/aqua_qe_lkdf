"""
AQuA-QE LKDF — AI Gateway Layer
Provider Adapters: implementações para cada provider
"""
from __future__ import annotations
import time
import json
import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator
import httpx

from backend.models.schemas import (
    ProviderConfig, GatewayRequest, GatewayResponse,
    ProviderName, RequestStatus
)


# ─────────────────────────────────────────────
# Base Adapter
# ─────────────────────────────────────────────

class BaseProviderAdapter(ABC):
    """Contrato base para todos os adapters de provider."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.name = config.name

    @abstractmethod
    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        """Executa uma completion e retorna a resposta padronizada."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verifica se o provider está disponível."""
        ...

    def _calc_cost(self, input_tokens: int, output_tokens: int) -> float:
        cost_in  = (input_tokens  / 1000) * self.config.cost_input_per_1k
        cost_out = (output_tokens / 1000) * self.config.cost_output_per_1k
        return round(cost_in + cost_out, 8)

    def _build_response(
        self,
        request: GatewayRequest,
        content: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        status: RequestStatus = RequestStatus.SUCCESS,
        error: str | None = None,
    ) -> GatewayResponse:
        return GatewayResponse(
            request_id=request.id,
            engine=request.engine,
            provider_used=self.config.name,
            model_used=request.metadata.get("resolved_model", self.config.default_model),
            status=status,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=self._calc_cost(input_tokens, output_tokens),
            error_message=error,
        )


# ─────────────────────────────────────────────
# Anthropic Adapter
# ─────────────────────────────────────────────

class AnthropicAdapter(BaseProviderAdapter):
    """Adapter para Anthropic Claude API."""

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        model = request.metadata.get("resolved_model", self.config.default_model)
        start = time.monotonic()

        payload = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": request.messages,
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt

        headers = {
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(
                f"{self.config.base_url}/v1/messages",
                json=payload,
                headers=headers,
            )

        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            return self._build_response(
                request, "", 0, 0, latency_ms,
                RequestStatus.FAILED,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )

        data = resp.json()
        content = data["content"][0]["text"]
        usage = data.get("usage", {})
        return self._build_response(
            request, content,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            latency_ms,
        )

    async def health_check(self) -> bool:
        try:
            headers = {
                "x-api-key": self.config.api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.config.base_url}/v1/messages",
                    json={"model": self.config.default_model, "max_tokens": 10,
                          "messages": [{"role": "user", "content": "ping"}]},
                    headers=headers,
                )
            return resp.status_code == 200
        except Exception:
            return False


# ─────────────────────────────────────────────
# OpenAI-Compatible Adapter (OpenAI, Azure, Groq, Mistral, vLLM, LM Studio)
# ─────────────────────────────────────────────

class OpenAICompatAdapter(BaseProviderAdapter):
    """Adapter genérico para qualquer API compatível com OpenAI."""

    def _get_headers(self) -> dict:
        headers = {"content-type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        # Azure usa header diferente
        if self.config.name == ProviderName.AZURE and self.config.api_key:
            headers["api-key"] = self.config.api_key
            headers.pop("Authorization", None)
        return headers

    def _get_url(self) -> str:
        base = self.config.base_url or ""
        if self.config.name == ProviderName.AZURE:
            model = self.config.default_model.replace(".", "")
            version = self.config.api_version or "2024-02-01"
            return f"{base}/openai/deployments/{model}/chat/completions?api-version={version}"
        return f"{base}/chat/completions"

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        model = request.metadata.get("resolved_model", self.config.default_model)
        start = time.monotonic()

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(self._get_url(), json=payload, headers=self._get_headers())

        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            return self._build_response(
                request, "", 0, 0, latency_ms,
                RequestStatus.FAILED,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return self._build_response(
            request, content,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            latency_ms,
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{self.config.base_url}/models",
                    headers=self._get_headers(),
                )
            return resp.status_code in (200, 401)  # 401 = auth ok, provider ok
        except Exception:
            return False


# ─────────────────────────────────────────────
# Ollama Adapter
# ─────────────────────────────────────────────

class OllamaAdapter(BaseProviderAdapter):
    """Adapter nativo para Ollama local."""

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        model = request.metadata.get("resolved_model", self.config.default_model)
        start = time.monotonic()

        # Montar prompt unificado (Ollama chat API)
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
            },
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(
                f"{self.config.base_url}/api/chat",
                json=payload,
            )

        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            return self._build_response(
                request, "", 0, 0, latency_ms,
                RequestStatus.FAILED,
                f"Ollama HTTP {resp.status_code}: {resp.text[:200]}",
            )

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        # Ollama reporta tokens em eval_count / prompt_eval_count
        input_tokens  = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return self._build_response(request, content, input_tokens, output_tokens, latency_ms)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.config.base_url}/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Lista modelos instalados no Ollama."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.config.base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []


# ─────────────────────────────────────────────
# Google Gemini Adapter
# ─────────────────────────────────────────────

class GeminiAdapter(BaseProviderAdapter):
    """
    Adapter para Google Gemini API (v1beta).
    Usa a REST API nativa do Gemini (não OpenAI-compat) com:
    - systemInstruction separado (não concatenado no conteúdo)
    - contents[] com role 'user' / 'model' (não 'assistant')
    - API key como query param ?key=...
    """

    # Aliases apenas para erros de digitação históricos conhecidos
    # NÃO mapear modelos novos — deixar passar direto para a API
    _MODEL_ALIASES: dict[str, str] = {
        "gemini-pro":    "gemini-1.5-pro",   # nome antigo descontinuado
        "gemini-flash":  "gemini-2.0-flash",  # nome antigo descontinuado
    }

    def _resolve_model(self, model: str) -> str:
        """Normaliza apenas aliases históricos descontinuados. Demais passam direto."""
        return self._MODEL_ALIASES.get(model, model)

    def _base_url(self) -> str:
        return (self.config.base_url or "https://generativelanguage.googleapis.com").rstrip("/")

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        raw_model = request.metadata.get("resolved_model", self.config.default_model)
        model     = self._resolve_model(raw_model)
        start     = time.monotonic()

        if not self.config.api_key:
            return self._build_response(
                request, "", 0, 0, 0,
                RequestStatus.FAILED,
                "Gemini API key não configurada. Acesse Providers e insira a chave.",
            )

        # ── Montar contents[] com role correto (user / model) ──
        contents = []
        for msg in request.messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # Gemini exige que o primeiro turn seja 'user'
        if not contents or contents[0]["role"] != "user":
            contents.insert(0, {"role": "user", "parts": [{"text": "Olá"}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature":     request.temperature,
            },
        }

        # ── System instruction — campo separado (não dentro de contents) ──
        if request.system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": request.system_prompt}]
            }

        url = (f"{self._base_url()}/v1beta/models/{model}:generateContent"
               f"?key={self.config.api_key}")

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            # Tenta extrair a mensagem de erro do JSON do Gemini
            try:
                err_body = resp.json()
                err_msg  = err_body.get("error", {}).get("message", resp.text[:300])
            except Exception:
                err_msg = resp.text[:300]
            return self._build_response(
                request, "", 0, 0, latency_ms,
                RequestStatus.FAILED,
                f"Gemini HTTP {resp.status_code}: {err_msg}",
            )

        data = resp.json()
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            # Pode haver blockReason em vez de candidates
            block = data.get("promptFeedback", {}).get("blockReason", "")
            content = f"[Resposta bloqueada pelo Gemini: {block}]" if block else ""

        usage = data.get("usageMetadata", {})
        return self._build_response(
            request, content,
            usage.get("promptTokenCount", 0),
            usage.get("candidatesTokenCount", 0),
            latency_ms,
        )

    async def health_check(self) -> bool:
        """
        Verifica se a API key é válida listando os modelos disponíveis.
        Retorna False silenciosamente se a key não estiver configurada.
        """
        if not self.config.api_key:
            return False
        try:
            url = f"{self._base_url()}/v1beta/models?key={self.config.api_key}"
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(url)
            # 200 = ok, 400 = key inválida, 403 = key sem permissão
            return resp.status_code == 200
        except Exception:
            return False


# ─────────────────────────────────────────────
# Adapter Factory
# ─────────────────────────────────────────────

def create_adapter(config: ProviderConfig) -> BaseProviderAdapter:
    """Factory: cria o adapter correto para cada provider."""
    mapping = {
        ProviderName.ANTHROPIC:  AnthropicAdapter,
        ProviderName.GOOGLE:     GeminiAdapter,
        ProviderName.OLLAMA:     OllamaAdapter,
        # OpenAI-compat
        ProviderName.OPENAI:     OpenAICompatAdapter,
        ProviderName.AZURE:      OpenAICompatAdapter,
        ProviderName.GROQ:       OpenAICompatAdapter,
        ProviderName.MISTRAL:    OpenAICompatAdapter,
        ProviderName.VLLM:       OpenAICompatAdapter,
        ProviderName.LM_STUDIO:  OpenAICompatAdapter,
        ProviderName.LLAMACPP:   OpenAICompatAdapter,
    }
    cls = mapping.get(config.name, OpenAICompatAdapter)
    return cls(config)
