"""
runtime_core/adapters/api/graphql/adapter.py
AQuA-QE LKDF v1.4 — GraphQL Adapter

Estende o RestAdapter com suporte nativo a GraphQL:
  - Execução de queries e mutations
  - Introspection do schema
  - Asserções em campos do response via path
  - Extração de variáveis de dados GraphQL
  - Suporte a operações nomeadas e variáveis GraphQL
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from runtime_core.adapters.api.contracts.models import (
    ApiAssertion,
    ApiRequest,
    ApiResponse,
    AssertionOp,
    AuthConfig,
    ContentType,
    HttpMethod,
)
from runtime_core.adapters.api.rest.adapter import RestAdapter, RestStepResult
from shared.models import AdapterType, RuntimeContext

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GraphQL models
# ---------------------------------------------------------------------------

@dataclass
class GraphQLOperation:
    """Uma operação GraphQL (query ou mutation)."""
    name:       str                  = ""
    query:      str                  = ""       # GraphQL query/mutation string
    variables:  dict[str, Any]       = field(default_factory=dict)
    operation:  str                  = "query"  # query | mutation | subscription

    def to_payload(self) -> dict:
        payload: dict[str, Any] = {"query": self.query}
        if self.variables:
            payload["variables"] = self.variables
        if self.name:
            payload["operationName"] = self.name
        return payload


@dataclass
class GraphQLResponse:
    """Resposta GraphQL normalizada."""
    data:   dict[str, Any] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    status_code: int              = 200
    elapsed_ms:  int              = 0

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def is_success(self) -> bool:
        return self.status_code == 200 and not self.has_errors

    def get(self, path: str) -> Any:
        """Extrai valor do campo data por path. Ex: 'user.id', 'users[0].name'"""
        from runtime_core.adapters.api.contracts.models import _json_path
        return _json_path(self.data, path)

    def error_messages(self) -> list[str]:
        return [e.get("message", str(e)) for e in self.errors]


# ---------------------------------------------------------------------------
# GraphQL Adapter
# ---------------------------------------------------------------------------

class GraphQLAdapter(RestAdapter):
    """
    Adapter GraphQL para o LKDF Runtime Core.
    Herda toda a infra do RestAdapter e adiciona suporte GraphQL nativo.

    Uso no DSL:
        # Adapter: api
        # graphql: true

    Actions adicionais:
        graphql_query, graphql_mutation, graphql_assert_data, graphql_assert_no_errors
    """

    adapter_type = AdapterType.API

    def __init__(
        self,
        base_url:       str             = "",
        graphql_path:   str             = "/graphql",
        auth:           AuthConfig | None = None,
        timeout_s:      int             = 30,
        max_retries:    int             = 3,
    ) -> None:
        super().__init__(base_url, auth, timeout_s, max_retries)
        self._graphql_path = graphql_path
        self._last_gql_response: GraphQLResponse | None = None

    # ------------------------------------------------------------------
    # GraphQL execution
    # ------------------------------------------------------------------

    async def execute_operation(
        self,
        operation:   GraphQLOperation,
        assertions:  list[ApiAssertion] | None = None,
        extractions: dict[str, str]    | None = None,
        step_name:   str                       = "",
    ) -> GraphQLResponse:
        """
        Executa uma operação GraphQL (query ou mutation).
        Aplica asserções e extrai variáveis do campo `data`.
        """
        # Resolve variables from store
        resolved_vars = {
            k: self._variables.resolve(str(v)) if isinstance(v, str) else v
            for k, v in operation.variables.items()
        }
        payload = GraphQLOperation(
            name=operation.name,
            query=operation.query,
            variables=resolved_vars,
            operation=operation.operation,
        ).to_payload()

        req = ApiRequest(
            method=HttpMethod.POST,
            url=self._base_url,
            path=self._graphql_path,
            body=payload,
            content_type=ContentType.GRAPHQL,
            auth=self._auth,
            timeout_s=self._timeout_s,
        )

        http_response = await self._do_request(req)
        gql_response  = self._parse_gql_response(http_response)
        self._last_gql_response = gql_response

        # Run assertions on GraphQL response
        if gql_response.has_errors:
            error_msgs = gql_response.error_messages()
            log.warning("graphql_errors", errors=error_msgs)

        assertion_results = []
        for assertion in (assertions or []):
            # Remap field paths to look in data
            mapped = ApiAssertion(
                field=assertion.field,
                op=assertion.op,
                expected=assertion.expected,
                message=assertion.message,
            )
            # Wrap response for assertion evaluation
            result = mapped.evaluate(http_response)
            assertion_results.append(result)
            if not result.passed:
                raise AssertionError(result.message)

        # Extract from data
        if extractions:
            for var_name, path in extractions.items():
                value = gql_response.get(path)
                if value is not None:
                    self._variables.set(var_name, value)

        return gql_response

    async def query(
        self,
        query:       str,
        variables:   dict[str, Any] | None = None,
        name:        str                   = "",
        extractions: dict[str, str] | None = None,
    ) -> GraphQLResponse:
        """Executa uma GraphQL query."""
        op = GraphQLOperation(
            name=name, query=query,
            variables=variables or {}, operation="query",
        )
        return await self.execute_operation(op, extractions=extractions)

    async def mutate(
        self,
        mutation:    str,
        variables:   dict[str, Any] | None = None,
        name:        str                   = "",
        extractions: dict[str, str] | None = None,
    ) -> GraphQLResponse:
        """Executa uma GraphQL mutation."""
        op = GraphQLOperation(
            name=name, query=mutation,
            variables=variables or {}, operation="mutation",
        )
        return await self.execute_operation(op, extractions=extractions)

    async def introspect(self) -> dict[str, Any]:
        """Retorna o schema via introspection query."""
        introspection_query = """
        query IntrospectionQuery {
          __schema {
            queryType { name }
            mutationType { name }
            types {
              name
              kind
              fields { name type { name kind } }
            }
          }
        }
        """
        resp = await self.query(introspection_query, name="IntrospectionQuery")
        return resp.data or {}

    # ------------------------------------------------------------------
    # Action handlers (extends RestAdapter)
    # ------------------------------------------------------------------

    async def execute_action(
        self,
        action:     str,
        parameters: dict[str, Any],
        context:    RuntimeContext,
    ) -> Any:
        if action in ("graphql_query", "graphql_operation"):
            return await self._handle_gql_query(parameters, context)
        if action == "graphql_mutation":
            return await self._handle_gql_mutation(parameters, context)
        if action == "graphql_assert_data":
            return await self._handle_gql_assert_data(parameters, context)
        if action == "graphql_assert_no_errors":
            return await self._handle_gql_assert_no_errors(parameters, context)
        # Fallback to REST adapter
        return await super().execute_action(action, parameters, context)

    async def _handle_gql_query(self, p: dict, ctx: RuntimeContext) -> GraphQLResponse:
        query = self._variables.resolve(p.get("query", "{ __typename }"))
        variables = p.get("variables", {})
        return await self.query(
            query=query, variables=variables,
            name=p.get("name", ""), extractions=p.get("extract"),
        )

    async def _handle_gql_mutation(self, p: dict, ctx: RuntimeContext) -> GraphQLResponse:
        mutation = self._variables.resolve(p.get("mutation", p.get("query", "")))
        variables = p.get("variables", {})
        return await self.mutate(
            mutation=mutation, variables=variables,
            name=p.get("name", ""), extractions=p.get("extract"),
        )

    async def _handle_gql_assert_data(self, p: dict, ctx: RuntimeContext) -> None:
        if not self._last_gql_response:
            raise AssertionError("Nenhuma operação GraphQL executada.")
        field_path = p.get("field", "")
        expected   = p.get("expected")
        op_str     = p.get("op", "eq")

        actual = self._last_gql_response.get(field_path)
        op     = AssertionOp(op_str)
        assertion = ApiAssertion(field=field_path, op=op, expected=expected)

        # Evaluate manually since we have GraphQLResponse not ApiResponse
        fake_response = type("R", (), {"body": self._last_gql_response.data,
                                       "status_code": 200,
                                       "headers": {},
                                       "json_path": lambda self, p: _path(self.body, p),
                                       "header": lambda self, n: None})()

        from runtime_core.adapters.api.contracts.models import _json_path
        actual = _json_path(self._last_gql_response.data, field_path)

        from runtime_core.adapters.api.contracts.models import ApiResponse as AR
        dummy = AR(request_id=__import__("uuid").uuid4(), body=self._last_gql_response.data)
        result = assertion.evaluate(dummy)
        if not result.passed:
            raise AssertionError(result.message)

    async def _handle_gql_assert_no_errors(self, p: dict, ctx: RuntimeContext) -> None:
        if not self._last_gql_response:
            raise AssertionError("Nenhuma operação GraphQL executada.")
        if self._last_gql_response.has_errors:
            msgs = self._last_gql_response.error_messages()
            raise AssertionError(f"GraphQL errors: {'; '.join(msgs)}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_gql_response(http_response: ApiResponse) -> GraphQLResponse:
        body = http_response.body
        if isinstance(body, dict):
            return GraphQLResponse(
                data=body.get("data"),
                errors=body.get("errors", []),
                status_code=http_response.status_code,
                elapsed_ms=http_response.elapsed_ms,
            )
        return GraphQLResponse(
            status_code=http_response.status_code,
            elapsed_ms=http_response.elapsed_ms,
        )

    @property
    def last_graphql_response(self) -> GraphQLResponse | None:
        return self._last_gql_response
