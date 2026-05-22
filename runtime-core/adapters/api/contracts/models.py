"""
runtime_core/adapters/api/contracts/models.py
AQuA-QE LKDF v1.4 — API Adapter: Domain Contracts

Modelos de request/response, autenticação e asserções para
testes de API REST e GraphQL sem acoplamento a biblioteca HTTP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HttpMethod(str, Enum):
    GET     = "GET"
    POST    = "POST"
    PUT     = "PUT"
    PATCH   = "PATCH"
    DELETE  = "DELETE"
    HEAD    = "HEAD"
    OPTIONS = "OPTIONS"


class AuthStrategy(str, Enum):
    NONE        = "none"
    BEARER      = "bearer"          # Authorization: Bearer <token>
    BASIC       = "basic"           # Authorization: Basic <b64>
    API_KEY     = "api_key"         # X-API-Key header
    OAUTH2      = "oauth2"          # OAuth2 flow
    COOKIE      = "cookie"          # Session cookie


class ContentType(str, Enum):
    JSON        = "application/json"
    FORM        = "application/x-www-form-urlencoded"
    MULTIPART   = "multipart/form-data"
    XML         = "application/xml"
    TEXT        = "text/plain"
    GRAPHQL     = "application/json"   # GraphQL uses JSON transport


class AssertionOp(str, Enum):
    EQ          = "eq"              # ==
    NEQ         = "neq"             # !=
    GT          = "gt"              # >
    GTE         = "gte"             # >=
    LT          = "lt"              # <
    LTE         = "lte"             # <=
    CONTAINS    = "contains"        # substring or list membership
    NOT_CONTAINS= "not_contains"
    MATCHES     = "matches"         # regex
    EXISTS      = "exists"          # field present
    NOT_EXISTS  = "not_exists"
    IS_NULL     = "is_null"
    IS_NOT_NULL = "is_not_null"
    LENGTH_EQ   = "length_eq"
    LENGTH_GT   = "length_gt"
    LENGTH_LT   = "length_lt"
    SCHEMA      = "schema"          # JSON schema validation


# ---------------------------------------------------------------------------
# Auth configuration
# ---------------------------------------------------------------------------

@dataclass
class AuthConfig:
    strategy:    AuthStrategy    = AuthStrategy.NONE
    token:       str             = ""        # Bearer token
    username:    str             = ""        # Basic auth
    password:    str             = ""
    api_key:     str             = ""
    header_name: str             = "X-API-Key"
    token_prefix: str            = "Bearer"
    cookie_name: str             = "session"
    extra:       dict[str, Any]  = field(default_factory=dict)

    def to_headers(self) -> dict[str, str]:
        if self.strategy == AuthStrategy.BEARER:
            return {"Authorization": f"{self.token_prefix} {self.token}"}
        if self.strategy == AuthStrategy.BASIC:
            import base64
            creds = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            return {"Authorization": f"Basic {creds}"}
        if self.strategy == AuthStrategy.API_KEY:
            return {self.header_name: self.api_key}
        return {}


# ---------------------------------------------------------------------------
# API Request
# ---------------------------------------------------------------------------

@dataclass
class ApiRequest:
    """Requisição HTTP normalizada — agnóstica de biblioteca."""
    id:           UUID              = field(default_factory=uuid4)
    method:       HttpMethod        = HttpMethod.GET
    url:          str               = ""
    path:         str               = ""            # appended to base_url
    headers:      dict[str, str]    = field(default_factory=dict)
    query_params: dict[str, Any]    = field(default_factory=dict)
    body:         Any               = None
    content_type: ContentType       = ContentType.JSON
    auth:         AuthConfig        = field(default_factory=AuthConfig)
    timeout_s:    int               = 30
    follow_redirects: bool          = True
    metadata:     dict[str, Any]    = field(default_factory=dict)

    @property
    def full_url(self) -> str:
        base = self.url.rstrip("/")
        path = ("/" + self.path.lstrip("/")) if self.path else ""
        return f"{base}{path}"

    def with_auth(self, auth: AuthConfig) -> "ApiRequest":
        import copy
        req = copy.copy(self)
        req.auth = auth
        return req


# ---------------------------------------------------------------------------
# API Response
# ---------------------------------------------------------------------------

@dataclass
class ApiResponse:
    """Resposta HTTP normalizada."""
    request_id:   UUID
    status_code:  int               = 200
    headers:      dict[str, str]    = field(default_factory=dict)
    body:         Any               = None          # parsed JSON or raw str
    raw_body:     str               = ""
    elapsed_ms:   int               = 0
    url:          str               = ""

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        return self.status_code >= 500

    def json_path(self, path: str) -> Any:
        """
        Extrai valor por JSON path simples.
        Ex: "data.user.id", "items[0].name"
        """
        return _json_path(self.body, path)

    def header(self, name: str) -> str | None:
        return self.headers.get(name) or self.headers.get(name.lower())


def _json_path(data: Any, path: str) -> Any:
    """Resolve JSON path simples: 'a.b.c' e 'items[0].name'."""
    import re
    if data is None:
        return None
    segments = re.split(r'\.|\[(\d+)\]', path)
    current  = data
    for seg in segments:
        if seg is None or seg == "":
            continue
        if isinstance(current, dict) and seg in current:
            current = current[seg]
        elif isinstance(current, list):
            try:
                current = current[int(seg)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------

@dataclass
class ApiAssertion:
    """Uma asserção sobre a resposta de uma requisição."""
    field:     str              = "status_code"   # "status_code", "body.user.id", etc.
    op:        AssertionOp      = AssertionOp.EQ
    expected:  Any              = 200
    message:   str              = ""

    def evaluate(self, response: ApiResponse) -> "ApiAssertionResult":
        actual = self._extract(response)
        passed = self._check(actual)
        return ApiAssertionResult(
            assertion=self,
            actual=actual,
            passed=passed,
            message=self.message or self._default_message(actual, passed),
        )

    def _extract(self, response: ApiResponse) -> Any:
        if self.field == "status_code":
            return response.status_code
        if self.field == "elapsed_ms":
            return response.elapsed_ms
        if self.field.startswith("header."):
            return response.header(self.field[7:])
        if self.field.startswith("body") or self.field.startswith("data"):
            path = self.field[5:] if self.field.startswith("body.") else self.field
            return response.json_path(path)
        return response.json_path(self.field)

    def _check(self, actual: Any) -> bool:
        exp = self.expected
        try:
            match self.op:
                case AssertionOp.EQ:          return actual == exp
                case AssertionOp.NEQ:         return actual != exp
                case AssertionOp.GT:          return actual > exp
                case AssertionOp.GTE:         return actual >= exp
                case AssertionOp.LT:          return actual < exp
                case AssertionOp.LTE:         return actual <= exp
                case AssertionOp.CONTAINS:
                    if isinstance(actual, str):   return str(exp) in actual
                    if isinstance(actual, list):  return exp in actual
                    if isinstance(actual, dict):  return exp in actual
                    return False
                case AssertionOp.NOT_CONTAINS:
                    if isinstance(actual, str):   return str(exp) not in actual
                    if isinstance(actual, list):  return exp not in actual
                    return True
                case AssertionOp.MATCHES:
                    import re
                    return bool(re.search(str(exp), str(actual)))
                case AssertionOp.EXISTS:      return actual is not None
                case AssertionOp.NOT_EXISTS:  return actual is None
                case AssertionOp.IS_NULL:     return actual is None
                case AssertionOp.IS_NOT_NULL: return actual is not None
                case AssertionOp.LENGTH_EQ:   return len(actual) == exp
                case AssertionOp.LENGTH_GT:   return len(actual) > exp
                case AssertionOp.LENGTH_LT:   return len(actual) < exp
                case AssertionOp.SCHEMA:
                    return self._validate_schema(actual, exp)
                case _:                       return False
        except (TypeError, AttributeError):
            return False

    @staticmethod
    def _validate_schema(data: Any, schema: dict) -> bool:
        """Validação de schema JSON simplificada."""
        if not isinstance(schema, dict):
            return False
        required = schema.get("required", [])
        if isinstance(data, dict):
            return all(field in data for field in required)
        return False

    def _default_message(self, actual: Any, passed: bool) -> str:
        status = "✓" if passed else "✗"
        return f"{status} {self.field} {self.op.value} {self.expected!r} (actual: {actual!r})"


@dataclass
class ApiAssertionResult:
    assertion: ApiAssertion
    actual:    Any
    passed:    bool
    message:   str = ""

    def __bool__(self) -> bool:
        return self.passed
