"""
runtime_core/adapters/api/rest/adapter.py
AQuA-QE LKDF v1.4 — REST API Adapter

Executa testes de API REST via httpx com:
  - Autenticação: Bearer, Basic, API Key, Cookie
  - Retry com backoff exponencial
  - Extração de variáveis de resposta (para encadeamento de requests)
  - Motor de asserções integrado
  - Coleta de evidências (request/response log estruturado)
  - Suporte a environments (dev/staging/prod)
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from runtime_core.adapters.api.contracts.models import (
    ApiAssertion,
    ApiAssertionResult,
    ApiRequest,
    ApiResponse,
    AssertionOp,
    AuthConfig,
    AuthStrategy,
    ContentType,
    HttpMethod,
    _json_path,
)
from runtime_core.adapters.base import BaseAdapter, AdapterError
from shared.models import AdapterType, RuntimeContext

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Variable store for request chaining
# ---------------------------------------------------------------------------

class ApiVariableStore:
    """
    Armazena variáveis extraídas de respostas para uso em requests subsequentes.
    Suporta: ${variavel}, {{variavel}}
    """

    def __init__(self) -> None:
        self._vars: dict[str, Any] = {}

    def set(self, name: str, value: Any) -> None:
        self._vars[name] = value
        log.debug("api_var_set", name=name, value=str(value)[:50])

    def get(self, name: str, default: Any = None) -> Any:
        return self._vars.get(name, default)

    def extract_from_response(
        self,
        response:    ApiResponse,
        extractions: dict[str, str],   # var_name → json_path
    ) -> None:
        """Extrai múltiplos valores de uma resposta e armazena como variáveis."""
        for var_name, path in extractions.items():
            value = response.json_path(path)
            if value is not None:
                self.set(var_name, value)
            else:
                log.warning("api_extraction_failed", var=var_name, path=path)

    def resolve(self, text: str) -> str:
        """Substitui ${VAR} e {{VAR}} no texto."""
        import re
        result = re.sub(
            r'\$\{(\w+)\}|\{\{(\w+)\}\}',
            lambda m: str(self._vars.get(m.group(1) or m.group(2), m.group(0))),
            str(text)
        )
        return result

    def resolve_dict(self, d: dict) -> dict:
        """Resolve variáveis em todos os valores de um dict."""
        return {k: self.resolve(str(v)) if isinstance(v, str) else v
                for k, v in d.items()}

    def snapshot(self) -> dict[str, Any]:
        return dict(self._vars)


# ---------------------------------------------------------------------------
# REST execution result
# ---------------------------------------------------------------------------

@dataclass
class RestStepResult:
    """Resultado de uma chamada REST individual."""
    step_name:         str
    request:           ApiRequest
    response:          ApiResponse | None = None
    assertion_results: list[ApiAssertionResult] = field(default_factory=list)
    passed:            bool                     = False
    error:             str                      = ""
    elapsed_ms:        int                      = 0

    @property
    def all_assertions_passed(self) -> bool:
        return all(r.passed for r in self.assertion_results)

    def failed_assertions(self) -> list[ApiAssertionResult]:
        return [r for r in self.assertion_results if not r.passed]


# ---------------------------------------------------------------------------
# REST Adapter
# ---------------------------------------------------------------------------

class RestAdapter(BaseAdapter):
    """
    Adapter REST para o LKDF Runtime Core.

    Executa actions semânticas como chamadas HTTP reais.
    Mantém session com cookies, variáveis e autenticação entre steps.

    Uso no DSL:
        # Adapter: api

    Actions suportadas:
        api_request, api_assert_status, api_assert_body,
        api_extract, api_set_auth, api_set_base_url
    """

    adapter_type = AdapterType.API

    def __init__(
        self,
        base_url:     str        = "",
        auth:         AuthConfig | None = None,
        timeout_s:    int        = 30,
        max_retries:  int        = 3,
        verify_ssl:   bool       = True,
    ) -> None:
        self._base_url    = base_url.rstrip("/")
        self._auth        = auth or AuthConfig()
        self._timeout_s   = timeout_s
        self._max_retries = max_retries
        self._verify_ssl  = verify_ssl
        self._variables   = ApiVariableStore()
        self._client: Any = None
        self._history:    list[RestStepResult] = []
        self._work_dir:   Path | None          = None

    # ------------------------------------------------------------------
    # BaseAdapter contract
    # ------------------------------------------------------------------

    async def setup(self, context: RuntimeContext) -> None:
        import httpx
        if context.project.base_url:
            self._base_url = context.project.base_url.rstrip("/")

        self._client = httpx.AsyncClient(
            timeout=self._timeout_s,
            verify=self._verify_ssl,
            follow_redirects=True,
        )
        import tempfile
        self._work_dir = Path(tempfile.mkdtemp(prefix="lkdf_api_"))
        log.info("rest_adapter_setup", base_url=self._base_url)

    async def teardown(self, context: RuntimeContext) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        log.info("rest_adapter_teardown", requests=len(self._history))

    async def execute_action(
        self,
        action:     str,
        parameters: dict[str, Any],
        context:    RuntimeContext,
    ) -> Any:
        handler = self._HANDLERS.get(action)
        if handler:
            return await handler(self, parameters, context)

        # Generic fallback: treat as GET request to path
        if "url" in parameters or "path" in parameters:
            return await self._handle_request(parameters, context)

        log.warning("api_action_unknown", action=action)
        return None

    async def collect_evidence(self, context: RuntimeContext) -> list[str]:
        if not self._work_dir:
            return []
        paths: list[str] = []
        log_path = self._work_dir / "api_execution_log.json"
        log_path.write_text(
            json.dumps(
                {
                    "total_requests": len(self._history),
                    "passed":  sum(1 for r in self._history if r.passed),
                    "failed":  sum(1 for r in self._history if not r.passed),
                    "requests": [self._step_to_dict(r) for r in self._history],
                },
                indent=2, default=str
            ),
            encoding="utf-8",
        )
        paths.append(str(log_path))
        return paths

    async def take_screenshot(self, context: RuntimeContext, name: str) -> str:
        # APIs don't have screenshots — save response body as evidence
        if self._history and self._work_dir:
            last = self._history[-1]
            path = self._work_dir / f"{name}_response.json"
            if last.response:
                path.write_text(
                    json.dumps({"status": last.response.status_code,
                               "body": last.response.body}, indent=2, default=str),
                    encoding="utf-8",
                )
            return str(path)
        return ""

    def _action_registry(self) -> set[str]:
        return set(self._HANDLERS.keys())

    # ------------------------------------------------------------------
    # Core: HTTP execution
    # ------------------------------------------------------------------

    async def execute_request(
        self,
        request:    ApiRequest,
        assertions: list[ApiAssertion] | None = None,
        extractions: dict[str, str]   | None = None,
        step_name:  str                       = "",
    ) -> RestStepResult:
        """
        Executa uma requisição HTTP com retry e coleta resultados.
        """
        response = await self._do_request(request)
        assertion_results: list[ApiAssertionResult] = []

        for assertion in (assertions or []):
            result = assertion.evaluate(response)
            assertion_results.append(result)
            if not result.passed:
                log.warning("api_assertion_failed",
                            field=assertion.field,
                            expected=assertion.expected,
                            actual=result.actual)

        if extractions and response.is_success:
            self._variables.extract_from_response(response, extractions)

        all_passed = all(r.passed for r in assertion_results)

        step_result = RestStepResult(
            step_name=step_name or request.full_url,
            request=request,
            response=response,
            assertion_results=assertion_results,
            passed=all_passed and response.is_success,
            elapsed_ms=response.elapsed_ms,
        )
        self._history.append(step_result)

        if not all_passed:
            failed = [r.message for r in assertion_results if not r.passed]
            raise AssertionError(f"API assertions failed: {'; '.join(failed)}")

        return step_result

    async def _do_request(self, request: ApiRequest) -> ApiResponse:
        """Executa a requisição com retry."""
        if not self._client:
            raise AdapterError("api_request", "Client not initialized. Call setup() first.")

        url    = request.full_url or f"{self._base_url}{request.path}"
        headers = {**request.headers, **request.auth.to_headers()}
        if not headers.get("Content-Type") and request.body is not None:
            headers["Content-Type"] = request.content_type.value

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                t0 = time.perf_counter()
                resp = await self._client.request(
                    method=request.method.value,
                    url=url,
                    headers=headers,
                    params=request.query_params or None,
                    json=request.body if request.content_type == ContentType.JSON else None,
                    data=request.body if request.content_type == ContentType.FORM else None,
                    timeout=request.timeout_s,
                )
                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                # Parse body
                body: Any = resp.text
                try:
                    body = resp.json()
                except Exception:
                    pass

                return ApiResponse(
                    request_id=request.id,
                    status_code=resp.status_code,
                    headers=dict(resp.headers),
                    body=body,
                    raw_body=resp.text[:5000],
                    elapsed_ms=elapsed_ms,
                    url=str(resp.url),
                )
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt * 0.5)
                    log.warning("api_retry", attempt=attempt + 1, error=str(exc))

        raise AdapterError("api_request", f"All retries failed: {last_exc}")

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_request(self, p: dict, ctx: RuntimeContext) -> RestStepResult:
        method = HttpMethod(p.get("method", "GET").upper())
        path   = self._variables.resolve(p.get("path", p.get("url", "")))
        body   = p.get("body") or p.get("payload")
        if isinstance(body, str):
            body = self._variables.resolve(body)

        req = ApiRequest(
            method=method,
            url=self._base_url,
            path=path,
            headers=self._variables.resolve_dict(p.get("headers", {})),
            query_params=p.get("params", {}),
            body=json.loads(body) if isinstance(body, str) and body.startswith("{") else body,
            auth=self._auth,
            timeout_s=self._timeout_s,
        )
        assertions = self._parse_assertions(p.get("assert", []))
        extractions = p.get("extract", {})
        return await self.execute_request(req, assertions, extractions,
                                          step_name=p.get("name", path))

    async def _handle_assert_status(self, p: dict, ctx: RuntimeContext) -> None:
        expected = int(p.get("status_code", p.get("expected", 200)))
        if not self._history:
            raise AdapterError("api_assert_status", "Nenhuma requisição executada ainda.")
        last = self._history[-1]
        if last.response and last.response.status_code != expected:
            raise AssertionError(
                f"Status code esperado {expected}, "
                f"recebido {last.response.status_code}"
            )

    async def _handle_assert_body(self, p: dict, ctx: RuntimeContext) -> None:
        if not self._history or not self._history[-1].response:
            raise AdapterError("api_assert_body", "Nenhuma resposta disponível.")
        resp       = self._history[-1].response
        field_path = p.get("field", "")
        op         = AssertionOp(p.get("op", "eq"))
        expected   = p.get("expected")
        assertion  = ApiAssertion(field=field_path, op=op, expected=expected)
        result     = assertion.evaluate(resp)
        if not result.passed:
            raise AssertionError(result.message)

    async def _handle_extract(self, p: dict, ctx: RuntimeContext) -> None:
        if not self._history or not self._history[-1].response:
            return
        resp = self._history[-1].response
        for var_name, path in p.items():
            if var_name.startswith("_"):
                continue
            value = resp.json_path(path)
            if value is not None:
                self._variables.set(var_name, value)

    async def _handle_set_auth(self, p: dict, ctx: RuntimeContext) -> None:
        strategy = AuthStrategy(p.get("strategy", "bearer"))
        self._auth = AuthConfig(
            strategy=strategy,
            token=self._variables.resolve(p.get("token", "")),
            username=p.get("username", ""),
            password=p.get("password", ""),
            api_key=p.get("api_key", ""),
        )
        log.info("api_auth_set", strategy=strategy.value)

    async def _handle_set_base_url(self, p: dict, ctx: RuntimeContext) -> None:
        self._base_url = p.get("url", self._base_url).rstrip("/")

    async def _handle_navigate(self, p: dict, ctx: RuntimeContext) -> RestStepResult:
        """Mapeia 'navigate' do DSL para GET na URL da API."""
        path = p.get("page", p.get("target", "/"))
        return await self._handle_request({"method": "GET", "path": path}, ctx)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_assertions(raw: list | dict) -> list[ApiAssertion]:
        if isinstance(raw, dict):
            raw = [raw]
        assertions: list[ApiAssertion] = []
        for item in raw:
            if isinstance(item, dict):
                assertions.append(ApiAssertion(
                    field=item.get("field", "status_code"),
                    op=AssertionOp(item.get("op", "eq")),
                    expected=item.get("expected", 200),
                    message=item.get("message", ""),
                ))
        return assertions

    @staticmethod
    def _step_to_dict(step: RestStepResult) -> dict[str, Any]:
        return {
            "step":       step.step_name,
            "method":     step.request.method.value,
            "url":        step.request.full_url,
            "status":     step.response.status_code if step.response else None,
            "elapsed_ms": step.elapsed_ms,
            "passed":     step.passed,
            "assertions": [
                {"field": r.assertion.field, "passed": r.passed, "message": r.message}
                for r in step.assertion_results
            ],
        }

    # ------------------------------------------------------------------
    # Handler registry
    # ------------------------------------------------------------------

    _HANDLERS: dict[str, Any] = {
        # Semantic actions from Intent Resolver
        "navigate":          _handle_navigate,
        "open_page":         _handle_navigate,
        "open_url":          _handle_navigate,

        # API-specific actions
        "api_request":       _handle_request,
        "api_get":           _handle_request,
        "api_post":          _handle_request,
        "api_put":           _handle_request,
        "api_delete":        _handle_request,
        "api_patch":         _handle_request,

        # Assertions
        "api_assert_status": _handle_assert_status,
        "assert_status":     _handle_assert_status,
        "api_assert_body":   _handle_assert_body,
        "assert_text":       _handle_assert_body,
        "assert_result":     _handle_assert_body,
        "assert_message":    _handle_assert_body,

        # Variable extraction & auth
        "api_extract":       _handle_extract,
        "api_set_auth":      _handle_set_auth,
        "api_set_base_url":  _handle_set_base_url,
    }

    # ------------------------------------------------------------------
    # Variable access (for pipeline integration)
    # ------------------------------------------------------------------

    def get_variable(self, name: str) -> Any:
        return self._variables.get(name)

    def set_variable(self, name: str, value: Any) -> None:
        self._variables.set(name, value)

    @property
    def last_response(self) -> ApiResponse | None:
        return self._history[-1].response if self._history else None

    @property
    def execution_history(self) -> list[RestStepResult]:
        return list(self._history)
