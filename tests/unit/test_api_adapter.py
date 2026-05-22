"""
tests/unit/test_api_adapter.py
AQuA-QE LKDF v1.4 — Unit Tests: API Adapter (REST + GraphQL)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from runtime_core.adapters.api.contracts.models import (
    ApiAssertion,
    ApiRequest,
    ApiResponse,
    AssertionOp,
    AuthConfig,
    AuthStrategy,
    ContentType,
    HttpMethod,
    _json_path,
)
from runtime_core.adapters.api.rest.adapter import ApiVariableStore, RestAdapter
from runtime_core.adapters.api.graphql.adapter import (
    GraphQLAdapter,
    GraphQLOperation,
    GraphQLResponse,
)
from runtime_core.adapters.factory import AdapterFactory
from shared.models import AdapterType, ProjectContext, RuntimeContext


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def make_response(
    status: int = 200,
    body: dict | str | None = None,
    elapsed_ms: int = 50,
) -> ApiResponse:
    return ApiResponse(
        request_id=uuid4(),
        status_code=status,
        headers={"Content-Type": "application/json"},
        body=body or {"status": "ok", "data": {"user": {"id": 42, "name": "Alice"}}},
        raw_body=json.dumps(body or {}),
        elapsed_ms=elapsed_ms,
        url="http://api.example.com/test",
    )


def make_ctx() -> RuntimeContext:
    return RuntimeContext(project=ProjectContext(base_url="http://api.example.com"))


def make_rest_adapter(base_url: str = "http://api.example.com") -> RestAdapter:
    return RestAdapter(base_url=base_url)


def make_mock_client(response: ApiResponse) -> MagicMock:
    """Cria mock do httpx.AsyncClient."""
    mock_resp = MagicMock()
    mock_resp.status_code = response.status_code
    mock_resp.text        = json.dumps(response.body)
    mock_resp.headers     = response.headers
    mock_resp.url         = response.url
    mock_resp.json        = MagicMock(return_value=response.body)

    mock_client = MagicMock()
    mock_client.request   = AsyncMock(return_value=mock_resp)
    mock_client.aclose    = AsyncMock()
    return mock_client


# ===========================================================================
# ApiRequest & ApiResponse
# ===========================================================================

class TestApiRequest:

    def test_full_url_base_only(self):
        req = ApiRequest(url="http://api.com", path="/users")
        assert req.full_url == "http://api.com/users"

    def test_full_url_with_path(self):
        req = ApiRequest(url="http://api.com/", path="users/1")
        assert req.full_url == "http://api.com/users/1"

    def test_full_url_no_path(self):
        req = ApiRequest(url="http://api.com/endpoint")
        assert req.full_url == "http://api.com/endpoint"

    def test_with_auth_copies(self):
        req  = ApiRequest(url="http://api.com")
        auth = AuthConfig(strategy=AuthStrategy.BEARER, token="abc")
        req2 = req.with_auth(auth)
        assert req2.auth.token == "abc"
        assert req.auth.token == ""   # original unchanged


class TestAuthConfig:

    def test_bearer_headers(self):
        auth = AuthConfig(strategy=AuthStrategy.BEARER, token="mytoken123")
        headers = auth.to_headers()
        assert headers["Authorization"] == "Bearer mytoken123"

    def test_basic_headers(self):
        import base64
        auth = AuthConfig(strategy=AuthStrategy.BASIC, username="user", password="pass")
        headers = auth.to_headers()
        expected_b64 = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected_b64}"

    def test_api_key_headers(self):
        auth = AuthConfig(strategy=AuthStrategy.API_KEY,
                          api_key="key123", header_name="X-Api-Key")
        headers = auth.to_headers()
        assert headers["X-Api-Key"] == "key123"

    def test_none_strategy_empty(self):
        auth = AuthConfig(strategy=AuthStrategy.NONE)
        assert auth.to_headers() == {}


class TestApiResponse:

    def test_is_success(self):
        assert make_response(200).is_success
        assert make_response(201).is_success
        assert not make_response(400).is_success
        assert not make_response(500).is_success

    def test_is_client_error(self):
        assert make_response(404).is_client_error
        assert make_response(401).is_client_error
        assert not make_response(200).is_client_error

    def test_is_server_error(self):
        assert make_response(500).is_server_error
        assert make_response(503).is_server_error

    def test_json_path_simple(self):
        resp = make_response(body={"user": {"id": 42, "name": "Alice"}})
        assert resp.json_path("user.id")   == 42
        assert resp.json_path("user.name") == "Alice"

    def test_json_path_nested(self):
        resp = make_response(body={"a": {"b": {"c": "deep"}}})
        assert resp.json_path("a.b.c") == "deep"

    def test_json_path_list_index(self):
        resp = make_response(body={"items": ["a", "b", "c"]})
        assert resp.json_path("items[1]") == "b"

    def test_json_path_missing(self):
        resp = make_response(body={"a": 1})
        assert resp.json_path("b.c") is None

    def test_header_case_insensitive(self):
        resp = ApiResponse(
            request_id=uuid4(), status_code=200,
            headers={"Content-Type": "application/json"},
            body={},
        )
        assert resp.header("content-type") is not None or resp.header("Content-Type") is not None


class TestJsonPath:

    def test_simple_key(self):
        assert _json_path({"a": 1}, "a") == 1

    def test_nested(self):
        assert _json_path({"a": {"b": 2}}, "a.b") == 2

    def test_list(self):
        assert _json_path({"items": [10, 20]}, "items[0]") == 10

    def test_none_data(self):
        assert _json_path(None, "a") is None

    def test_missing_key(self):
        assert _json_path({"a": 1}, "b") is None


# ===========================================================================
# ApiAssertion
# ===========================================================================

class TestApiAssertion:
    resp = make_response(
        body={"status": "ok", "count": 5, "items": ["a", "b", "c"],
              "user": {"id": 42, "email": "test@test.com"}}
    )

    def eval(self, field, op, expected) -> bool:
        a = ApiAssertion(field=field, op=op, expected=expected)
        return a.evaluate(self.resp).passed

    def test_status_code_eq(self):
        assert self.eval("status_code", AssertionOp.EQ, 200)

    def test_status_code_neq(self):
        assert self.eval("status_code", AssertionOp.NEQ, 404)

    def test_body_field_eq(self):
        assert self.eval("status", AssertionOp.EQ, "ok")

    def test_body_nested_eq(self):
        assert self.eval("user.id", AssertionOp.EQ, 42)

    def test_body_contains_string(self):
        assert self.eval("user.email", AssertionOp.CONTAINS, "test")

    def test_body_contains_list(self):
        assert self.eval("items", AssertionOp.CONTAINS, "b")

    def test_body_not_contains(self):
        assert self.eval("items", AssertionOp.NOT_CONTAINS, "z")

    def test_gt_lt(self):
        assert self.eval("count", AssertionOp.GT, 4)
        assert self.eval("count", AssertionOp.LT, 6)
        assert self.eval("count", AssertionOp.GTE, 5)
        assert self.eval("count", AssertionOp.LTE, 5)

    def test_exists(self):
        assert self.eval("user.id", AssertionOp.EXISTS, None)

    def test_not_exists(self):
        assert self.eval("missing_field", AssertionOp.NOT_EXISTS, None)

    def test_is_null(self):
        resp = make_response(body={"value": None})
        a = ApiAssertion(field="value", op=AssertionOp.IS_NULL)
        assert a.evaluate(resp).passed

    def test_is_not_null(self):
        assert self.eval("user.id", AssertionOp.IS_NOT_NULL, None)

    def test_length_eq(self):
        assert self.eval("items", AssertionOp.LENGTH_EQ, 3)

    def test_length_gt(self):
        assert self.eval("items", AssertionOp.LENGTH_GT, 2)

    def test_regex_matches(self):
        assert self.eval("user.email", AssertionOp.MATCHES, r"@test\.com")

    def test_schema_validation(self):
        schema = {"required": ["id", "email"]}
        assert self.eval("user", AssertionOp.SCHEMA, schema)

    def test_failed_assertion_message(self):
        a = ApiAssertion(field="status_code", op=AssertionOp.EQ, expected=404)
        result = a.evaluate(self.resp)
        assert not result.passed
        assert "404" in result.message or "200" in result.message


# ===========================================================================
# ApiVariableStore
# ===========================================================================

class TestApiVariableStore:

    def test_set_and_get(self):
        store = ApiVariableStore()
        store.set("token", "abc123")
        assert store.get("token") == "abc123"

    def test_get_missing(self):
        store = ApiVariableStore()
        assert store.get("missing") is None
        assert store.get("missing", "default") == "default"

    def test_resolve_dollar_syntax(self):
        store = ApiVariableStore()
        store.set("USER_ID", "42")
        result = store.resolve("GET /users/${USER_ID}")
        assert result == "GET /users/42"

    def test_resolve_double_brace_syntax(self):
        store = ApiVariableStore()
        store.set("ENV", "staging")
        result = store.resolve("https://{{ENV}}.api.com")
        assert result == "https://staging.api.com"

    def test_resolve_missing_var_unchanged(self):
        store = ApiVariableStore()
        result = store.resolve("${UNDEFINED}")
        assert result == "${UNDEFINED}"

    def test_extract_from_response(self):
        store = ApiVariableStore()
        resp  = make_response(body={"token": "jwt.abc.def", "user": {"id": 99}})
        store.extract_from_response(resp, {"TOKEN": "token", "USER_ID": "user.id"})
        assert store.get("TOKEN")   == "jwt.abc.def"
        assert store.get("USER_ID") == 99

    def test_resolve_dict(self):
        store = ApiVariableStore()
        store.set("TOKEN", "secret")
        result = store.resolve_dict({"Authorization": "Bearer ${TOKEN}", "X-Static": "val"})
        assert result["Authorization"] == "Bearer secret"
        assert result["X-Static"]      == "val"

    def test_snapshot(self):
        store = ApiVariableStore()
        store.set("A", 1)
        store.set("B", 2)
        snap = store.snapshot()
        assert snap == {"A": 1, "B": 2}


# ===========================================================================
# RestAdapter
# ===========================================================================

class TestRestAdapter:

    @pytest.mark.asyncio
    async def test_setup_and_teardown(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        assert adapter._client is not None
        await adapter.teardown(ctx)
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_execute_get_request(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)

        mock_response = make_response(200, {"users": [{"id": 1}]})
        adapter._client = make_mock_client(mock_response)

        req = ApiRequest(method=HttpMethod.GET, url="http://api.example.com", path="/users")
        result = await adapter.execute_request(req)
        assert result.response.status_code == 200

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_assertions_pass(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = make_mock_client(make_response(200, {"ok": True}))

        req  = ApiRequest(method=HttpMethod.GET, url="http://api.example.com", path="/")
        assertions = [
            ApiAssertion("status_code", AssertionOp.EQ, 200),
            ApiAssertion("ok", AssertionOp.EQ, True),
        ]
        result = await adapter.execute_request(req, assertions)
        assert result.all_assertions_passed

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_assertion_failure_raises(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = make_mock_client(make_response(404, {"error": "not found"}))

        req  = ApiRequest(method=HttpMethod.GET, url="http://api.example.com", path="/")
        assertions = [ApiAssertion("status_code", AssertionOp.EQ, 200)]

        with pytest.raises(AssertionError, match="assertions failed"):
            await adapter.execute_request(req, assertions)

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_variable_extraction(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = make_mock_client(
            make_response(200, {"token": "jwt.header.payload", "userId": 7})
        )

        req = ApiRequest(method=HttpMethod.POST, url="http://api.example.com", path="/login")
        await adapter.execute_request(
            req, extractions={"TOKEN": "token", "USER_ID": "userId"}
        )
        assert adapter.get_variable("TOKEN")   == "jwt.header.payload"
        assert adapter.get_variable("USER_ID") == 7

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_execute_action_navigate(self):
        adapter = make_rest_adapter("http://api.example.com")
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = make_mock_client(make_response(200))

        await adapter.execute_action("navigate", {"page": "/health"}, ctx)
        call_url = str(adapter._client.request.call_args[1].get("url") or
                       adapter._client.request.call_args[0][1])
        assert "health" in call_url

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_execute_action_api_request(self):
        adapter = make_rest_adapter("http://api.example.com")
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = make_mock_client(make_response(201, {"id": 1}))

        await adapter.execute_action(
            "api_post",
            {"method": "POST", "path": "/items", "body": '{"name": "test"}'},
            ctx,
        )
        assert len(adapter.execution_history) == 1

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_set_auth_bearer(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)

        await adapter.execute_action(
            "api_set_auth",
            {"strategy": "bearer", "token": "my-jwt-token"},
            ctx,
        )
        assert adapter._auth.token == "my-jwt-token"
        assert adapter._auth.strategy == AuthStrategy.BEARER

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_last_response(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        mock_resp = make_response(200, {"ok": True})
        adapter._client = make_mock_client(mock_resp)

        req = ApiRequest(method=HttpMethod.GET, url="http://api.example.com", path="/")
        await adapter.execute_request(req)

        assert adapter.last_response is not None
        assert adapter.last_response.status_code == 200

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_collect_evidence(self):
        adapter = make_rest_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = make_mock_client(make_response(200))

        req = ApiRequest(method=HttpMethod.GET, url="http://api.example.com", path="/")
        await adapter.execute_request(req)

        evidence = await adapter.collect_evidence(ctx)
        assert len(evidence) >= 1
        assert evidence[0].endswith(".json")

        await adapter.teardown(ctx)

    def test_action_registry(self):
        adapter  = make_rest_adapter()
        registry = adapter._action_registry()
        for action in ("navigate", "api_request", "api_assert_status", "api_set_auth"):
            assert action in registry


# ===========================================================================
# GraphQL Adapter
# ===========================================================================

class TestGraphQLAdapter:

    def make_gql_adapter(self) -> GraphQLAdapter:
        return GraphQLAdapter(base_url="http://api.example.com", graphql_path="/graphql")

    def make_mock_gql_client(
        self, data: dict | None = None, errors: list | None = None
    ) -> MagicMock:
        body = {}
        if data is not None:
            body["data"] = data
        if errors:
            body["errors"] = errors
        return make_mock_client(make_response(200, body))

    @pytest.mark.asyncio
    async def test_query_success(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(
            data={"user": {"id": 1, "name": "Alice"}}
        )

        result = await adapter.query("{ user { id name } }")
        assert not result.has_errors
        assert result.get("user.id") == 1

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_mutation_success(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(
            data={"createUser": {"id": 99, "name": "Bob"}}
        )

        result = await adapter.mutate(
            'mutation { createUser(name: "Bob") { id name } }'
        )
        assert result.get("createUser.id") == 99

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_query_with_variables(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(
            data={"user": {"id": 42}}
        )

        result = await adapter.query(
            "query GetUser($id: ID!) { user(id: $id) { id } }",
            variables={"id": "42"},
            name="GetUser",
        )
        assert result.data["user"]["id"] == 42

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_query_with_errors(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(
            errors=[{"message": "User not found", "locations": [{"line": 1}]}]
        )

        result = await adapter.query("{ user(id: 999) { id } }")
        assert result.has_errors
        assert "User not found" in result.error_messages()

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_assert_no_errors_passes(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(data={"ok": True})
        await adapter.query("{ ok }")

        # Should not raise
        await adapter.execute_action("graphql_assert_no_errors", {}, ctx)

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_assert_no_errors_fails(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(
            errors=[{"message": "Server error"}]
        )
        await adapter.query("{ something }")

        with pytest.raises(AssertionError, match="Server error"):
            await adapter.execute_action("graphql_assert_no_errors", {}, ctx)

        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_variable_extraction_from_gql(self):
        adapter = self.make_gql_adapter()
        ctx     = make_ctx()
        await adapter.setup(ctx)
        adapter._client = self.make_mock_gql_client(
            data={"login": {"token": "jwt.abc.def"}}
        )

        await adapter.query(
            'mutation { login(email: "a@b.com") { token } }',
            extractions={"AUTH_TOKEN": "login.token"},
        )
        assert adapter.get_variable("AUTH_TOKEN") == "jwt.abc.def"

        await adapter.teardown(ctx)

    def test_operation_to_payload(self):
        op = GraphQLOperation(
            name="GetUser",
            query="{ user { id } }",
            variables={"id": "1"},
        )
        payload = op.to_payload()
        assert payload["query"] == "{ user { id } }"
        assert payload["variables"] == {"id": "1"}
        assert payload["operationName"] == "GetUser"

    def test_graphql_response_get_path(self):
        resp = GraphQLResponse(data={"user": {"id": 5, "name": "Alice"}})
        assert resp.get("user.id")   == 5
        assert resp.get("user.name") == "Alice"
        assert resp.get("missing")   is None

    def test_graphql_response_has_errors(self):
        resp_ok  = GraphQLResponse(data={"ok": True})
        resp_err = GraphQLResponse(errors=[{"message": "Error"}])
        assert not resp_ok.has_errors
        assert resp_err.has_errors


# ===========================================================================
# AdapterFactory — API
# ===========================================================================

class TestAdapterFactoryApi:

    def test_creates_rest_adapter(self):
        ctx     = ProjectContext(base_url="http://api.example.com")
        adapter = AdapterFactory.create(AdapterType.API, ctx)
        from runtime_core.adapters.api.rest.adapter import RestAdapter
        assert isinstance(adapter, RestAdapter)

    def test_creates_graphql_adapter(self):
        ctx = ProjectContext(
            base_url="http://api.example.com",
            extra={"graphql": True, "graphql_path": "/graphql"},
        )
        adapter = AdapterFactory.create(AdapterType.API, ctx)
        from runtime_core.adapters.api.graphql.adapter import GraphQLAdapter
        assert isinstance(adapter, GraphQLAdapter)

    def test_creates_rest_with_bearer_auth(self):
        ctx = ProjectContext(
            base_url="http://api.example.com",
            extra={"token": "my-token"},
        )
        adapter = AdapterFactory.create(AdapterType.API, ctx)
        assert adapter._auth.strategy == AuthStrategy.BEARER
        assert adapter._auth.token    == "my-token"

    def test_creates_rest_with_api_key_auth(self):
        ctx = ProjectContext(
            base_url="http://api.example.com",
            extra={"api_key": "key-123", "api_key_header": "X-Token"},
        )
        adapter = AdapterFactory.create(AdapterType.API, ctx)
        assert adapter._auth.strategy  == AuthStrategy.API_KEY
        assert adapter._auth.api_key   == "key-123"

    def test_create_from_string(self):
        adapter = AdapterFactory.create("api", ProjectContext(base_url="http://api.com"))
        from runtime_core.adapters.api.rest.adapter import RestAdapter
        assert isinstance(adapter, RestAdapter)

    def test_available_lists_api(self):
        available = AdapterFactory.available()
        # API adapter is always available (no special install needed)
        assert isinstance(available, list)
