"""
AQuA-QE LKDF — AI Gateway Layer
Provider Adapters: implementações para cada provider
Inclui streaming real (SSE) para todos os providers.
"""
from __future__ import annotations
import time
import json
import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
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

    async def stream(self, request: GatewayRequest) -> AsyncIterator[str]:
        """
        Streaming real de tokens.
        Yield: chunks de texto à medida que chegam do provider.
        Default: fallback para complete() + yield por palavra (providers sem streaming nativo).
        """
        response = await self.complete(request)
        for word in response.content.split(" "):
            yield word + " "
            await asyncio.sleep(0.008)

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
# Anthropic Adapter — streaming nativo
# ─────────────────────────────────────────────

class AnthropicAdapter(BaseProviderAdapter):
    """Adapter para Anthropic Claude API com streaming real."""

    def _headers(self) -> dict:
        return {
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _payload(self, request: GatewayRequest, stream: bool = False) -> dict:
        model = request.metadata.get("resolved_model", self.config.default_model)
        p: dict = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": request.messages,
            "stream": stream,
        }
        if request.system_prompt:
            p["system"] = request.system_prompt
        return p

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(
                f"{self.config.base_url}/v1/messages",
                json=self._payload(request),
                headers=self._headers(),
            )
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            return self._build_response(
                request, "", 0, 0, latency_ms, RequestStatus.FAILED,
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

    async def stream(self, request: GatewayRequest) -> AsyncIterator[str]:
        """Streaming nativo via Anthropic SSE."""
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self.config.base_url}/v1/messages",
                json=self._payload(request, stream=True),
                headers=self._headers(),
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise RuntimeError(f"Anthropic {resp.status_code}: {error_body[:200]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]" or not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type", "")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield text
                    elif etype == "message_stop":
                        break

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.config.base_url}/v1/messages",
                    json={"model": self.config.default_model, "max_tokens": 10,
                          "messages": [{"role": "user", "content": "ping"}]},
                    headers=self._headers(),
                )
            return resp.status_code == 200
        except Exception:
            return False


# ─────────────────────────────────────────────
# OpenAI-Compatible Adapter — streaming nativo
# ─────────────────────────────────────────────

class OpenAICompatAdapter(BaseProviderAdapter):
    """Adapter genérico para qualquer API compatível com OpenAI, com streaming real."""

    def _get_headers(self) -> dict:
        headers = {"content-type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.name == ProviderName.AZURE and self.config.api_key:
            headers["api-key"] = self.config.api_key
            headers.pop("Authorization", None)
        return headers

    def _get_url(self, stream: bool = False) -> str:
        base = self.config.base_url or ""
        if self.config.name == ProviderName.AZURE:
            model = self.config.default_model.replace(".", "")
            version = self.config.api_version or "2024-02-01"
            return f"{base}/openai/deployments/{model}/chat/completions?api-version={version}"
        return f"{base}/chat/completions"

    def _build_messages(self, request: GatewayRequest) -> list:
        msgs = []
        if request.system_prompt:
            msgs.append({"role": "system", "content": request.system_prompt})
        msgs.extend(request.messages)
        return msgs

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        model = request.metadata.get("resolved_model", self.config.default_model)
        start = time.monotonic()
        payload = {
            "model": model,
            "messages": self._build_messages(request),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(self._get_url(), json=payload, headers=self._get_headers())
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            return self._build_response(
                request, "", 0, 0, latency_ms, RequestStatus.FAILED,
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

    async def stream(self, request: GatewayRequest) -> AsyncIterator[str]:
        """Streaming nativo OpenAI SSE."""
        model = request.metadata.get("resolved_model", self.config.default_model)
        payload = {
            "model": model,
            "messages": self._build_messages(request),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            async with client.stream(
                "POST", self._get_url(),
                json=payload, headers=self._get_headers(),
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(f"{self.config.name} {resp.status_code}: {body[:200]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]" or not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{self.config.base_url}/models",
                    headers=self._get_headers(),
                )
            return resp.status_code in (200, 401)
        except Exception:
            return False


# ─────────────────────────────────────────────
# Ollama Adapter — streaming nativo
# ─────────────────────────────────────────────

class OllamaAdapter(BaseProviderAdapter):
    """Adapter nativo para Ollama local com streaming real."""

    def _build_messages(self, request: GatewayRequest) -> list:
        msgs = []
        if request.system_prompt:
            msgs.append({"role": "system", "content": request.system_prompt})
        msgs.extend(request.messages)
        return msgs

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        model = request.metadata.get("resolved_model", self.config.default_model)
        start = time.monotonic()
        payload = {
            "model": model,
            "messages": self._build_messages(request),
            "stream": False,
            "options": {
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(f"{self.config.base_url}/api/chat", json=payload)
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            return self._build_response(
                request, "", 0, 0, latency_ms, RequestStatus.FAILED,
                f"Ollama HTTP {resp.status_code}: {resp.text[:200]}",
            )
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        return self._build_response(
            request, content,
            data.get("prompt_eval_count", 0),
            data.get("eval_count", 0),
            latency_ms,
        )

    async def stream(self, request: GatewayRequest) -> AsyncIterator[str]:
        """Streaming nativo Ollama (NDJSON)."""
        model = request.metadata.get("resolved_model", self.config.default_model)
        payload = {
            "model": model,
            "messages": self._build_messages(request),
            "stream": True,
            "options": {
                "num_predict": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            async with client.stream(
                "POST", f"{self.config.base_url}/api/chat", json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(f"Ollama {resp.status_code}: {body[:200]}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    text = event.get("message", {}).get("content", "")
                    if text:
                        yield text
                    if event.get("done"):
                        break

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.config.base_url}/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.config.base_url}/api/tags")
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []


# ─────────────────────────────────────────────
# Google Gemini Adapter — streaming nativo
# ─────────────────────────────────────────────

class GeminiAdapter(BaseProviderAdapter):
    """Adapter para Google Gemini API com streaming real."""

    _MODEL_ALIASES: dict[str, str] = {
        "gemini-pro":              "gemini-1.5-pro",
        "gemini-flash":            "gemini-2.0-flash",
        "gemini-1.5-flash":        "gemini-2.0-flash",
        "gemini-1.5-flash-8b":     "gemini-2.0-flash-lite",
        "gemini-1.5-flash-latest": "gemini-2.0-flash",
    }

    def _resolve_model(self, model: str) -> str:
        model = model.strip().replace(" ", "-")
        return self._MODEL_ALIASES.get(model, model)

    def _base_url(self) -> str:
        return (self.config.base_url or "https://generativelanguage.googleapis.com").rstrip("/")

    def _build_payload(self, request: GatewayRequest, stream: bool = False) -> tuple[str, dict]:
        """Returns (url, payload)."""
        raw_model = request.metadata.get("resolved_model", self.config.default_model)
        model = self._resolve_model(raw_model)
        action = "streamGenerateContent" if stream else "generateContent"
        url = f"{self._base_url()}/v1beta/models/{model}:{action}?key={self.config.api_key}"
        if stream:
            url += "&alt=sse"

        contents = []
        for msg in request.messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        if not contents or contents[0]["role"] != "user":
            contents.insert(0, {"role": "user", "parts": [{"text": "Olá"}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}

        return url, payload

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        if not self.config.api_key:
            return self._build_response(
                request, "", 0, 0, 0, RequestStatus.FAILED,
                "Gemini API key não configurada. Acesse Providers e insira a chave.",
            )
        start = time.monotonic()
        url, payload = self._build_payload(request)
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text[:300])
            except Exception:
                err_msg = resp.text[:300]
            return self._build_response(
                request, "", 0, 0, latency_ms, RequestStatus.FAILED,
                f"Gemini HTTP {resp.status_code}: {err_msg}",
            )
        data = resp.json()
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            block = data.get("promptFeedback", {}).get("blockReason", "")
            content = f"[Bloqueado pelo Gemini: {block}]" if block else ""
        usage = data.get("usageMetadata", {})
        return self._build_response(
            request, content,
            usage.get("promptTokenCount", 0),
            usage.get("candidatesTokenCount", 0),
            latency_ms,
        )

    async def stream(self, request: GatewayRequest) -> AsyncIterator[str]:
        """Streaming nativo Gemini via SSE."""
        if not self.config.api_key:
            raise RuntimeError("Gemini API key não configurada.")
        url, payload = self._build_payload(request, stream=True)
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            async with client.stream(
                "POST", url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    try:
                        err = json.loads(body).get("error", {}).get("message", body[:200])
                    except Exception:
                        err = body[:200]
                    raise RuntimeError(f"Gemini {resp.status_code}: {err}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        text = event["candidates"][0]["content"]["parts"][0]["text"]
                        if text:
                            yield text
                    except (KeyError, IndexError):
                        pass

    async def health_check(self) -> bool:
        if not self.config.api_key:
            return False
        try:
            url = f"{self._base_url()}/v1beta/models?key={self.config.api_key}"
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(url)
            return resp.status_code == 200
        except Exception:
            return False


# ─────────────────────────────────────────────
# Adapter Factory
# ─────────────────────────────────────────────

def create_adapter(config: ProviderConfig) -> BaseProviderAdapter:
    mapping = {
        ProviderName.ANTHROPIC:  AnthropicAdapter,
        ProviderName.GOOGLE:     GeminiAdapter,
        ProviderName.OLLAMA:     OllamaAdapter,
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



# ─────────────────────────────────────────────
# Base Adapter
# ─────────────────────────────────────────────
