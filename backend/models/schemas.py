"""
AQuA-QE LKDF — AI Gateway Layer
Schemas e modelos de dados compartilhados
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import uuid


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class ProviderType(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"


class ProviderName(str, Enum):
    # Cloud
    ANTHROPIC  = "anthropic"
    OPENAI     = "openai"
    AZURE      = "azure_openai"
    GOOGLE     = "google_gemini"
    GROQ       = "groq"
    MISTRAL    = "mistral"
    # Local
    OLLAMA     = "ollama"
    VLLM       = "vllm"
    LM_STUDIO  = "lm_studio"
    LLAMACPP   = "llamacpp"


class DeploymentMode(str, Enum):
    CLOUD      = "cloud"
    HYBRID     = "hybrid"
    LOCAL      = "local"


class EngineType(str, Enum):
    NORMALIZE        = "normalize"
    REQUIREMENT      = "requirement"
    VALIDATION       = "validation"
    BUSINESS_RULE    = "business_rule"
    ACCEPTANCE       = "acceptance_criteria"
    RISK             = "risk"
    COVERAGE         = "coverage"
    INFERENCE        = "inference"
    SYNTHESIS        = "synthesis"
    CONSISTENCY      = "consistency"
    IMPACT           = "impact"
    COMPLIANCE       = "compliance"
    TRACEABILITY     = "traceability"
    ARTIFACT         = "artifact"


class RoutingStrategy(str, Enum):
    COST_OPTIMIZED    = "cost_optimized"
    PERFORMANCE_FIRST = "performance_first"
    PRIVACY_FIRST     = "privacy_first"
    ROUND_ROBIN       = "round_robin"
    CAPABILITY_MATCH  = "capability_match"


class RequestStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    SUCCESS    = "success"
    FALLBACK   = "fallback"
    FAILED     = "failed"


# ─────────────────────────────────────────────
# Provider Config
# ─────────────────────────────────────────────

class ProviderConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: ProviderName
    provider_type: ProviderType
    display_name: str
    enabled: bool = True
    priority: int = Field(default=5, ge=1, le=10)

    # Connection
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    api_version: Optional[str] = None

    # Models available
    available_models: list[str] = []
    default_model: str = ""

    # Limits
    max_tokens: int = 4096
    timeout_seconds: int = 60
    max_retries: int = 3

    # Cost (per 1k tokens, USD)
    cost_input_per_1k: float = 0.0
    cost_output_per_1k: float = 0.0

    # Capabilities
    supports_streaming: bool = True
    supports_function_calling: bool = True
    supports_vision: bool = False
    max_context_tokens: int = 128000

    # Health
    is_healthy: bool = True
    last_health_check: Optional[datetime] = None
    consecutive_failures: int = 0

    model_config = ConfigDict(use_enum_values=True)


class ModelConfig(BaseModel):
    # Suppress protected namespace warning for model_id
    model_config = ConfigDict(protected_namespaces=())

    provider: ProviderName
    model_id: str
    display_name: str
    context_window: int
    cost_input_per_1k: float
    cost_output_per_1k: float
    strengths: list[str] = []
    best_for_engines: list[EngineType] = []


# ─────────────────────────────────────────────
# Engine Routing
# ─────────────────────────────────────────────

class EngineRouteConfig(BaseModel):
    engine: EngineType
    primary_provider: ProviderName
    primary_model: str
    fallback_providers: list[ProviderName] = []
    strategy: RoutingStrategy = RoutingStrategy.CAPABILITY_MATCH
    max_cost_per_call: Optional[float] = None


# ─────────────────────────────────────────────
# Gateway Request / Response
# ─────────────────────────────────────────────

class GatewayRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    engine: EngineType
    messages: list[dict[str, str]]
    system_prompt: Optional[str] = None
    max_tokens: int = 2000
    temperature: float = 0.3
    stream: bool = False
    deployment_mode: DeploymentMode = DeploymentMode.CLOUD
    force_provider: Optional[ProviderName] = None
    metadata: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GatewayResponse(BaseModel):
    # Suppress protected namespace warning for model_used
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    engine: EngineType
    provider_used: ProviderName
    model_used: str
    status: RequestStatus
    content: str
    fallback_used: bool = False
    fallback_from: Optional[ProviderName] = None

    # Observability
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    confidence_score: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None


# ─────────────────────────────────────────────
# Observability
# ─────────────────────────────────────────────

class ExecutionLog(BaseModel):
    """Log completo de uma execução — §29 AI Observability."""
    id:          str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id:  str
    trace_id:    str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    # What
    engine:      EngineType
    provider:    ProviderName
    model:       str
    status:      RequestStatus

    # Performance
    input_tokens:  int   = 0
    output_tokens: int   = 0
    latency_ms:    float = 0.0
    ttft_ms:       float = 0.0   # Time To First Token
    cost_usd:      float = 0.0

    # Quality
    confidence_score: float = 1.0   # 0–1, estimated from status/fallback
    fallback_used:    bool  = False
    fallback_from:    Optional[str] = None
    retry_count:      int   = 0

    # Prompt observability
    prompt_hash:      str  = ""     # SHA8 do system prompt
    prompt_type:      str  = ""     # elicitation, rtm, risk, etc.
    system_prompt_len: int = 0
    user_prompt_len:   int = 0

    # Reasoning trace (simplified)
    reasoning_steps:   list[str] = []   # engine pipeline steps
    engine_chain:      list[str] = []   # engines invoked in sequence

    # Error
    error:       Optional[str] = None
    error_type:  Optional[str] = None   # timeout, auth, rate_limit, model_error

    # Context
    deployment_mode: str = "cloud"
    session_id:      Optional[str] = None
    user_label:      Optional[str] = None   # custom tag from caller

    timestamp:   datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class GatewayStats(BaseModel):
    total_requests: int = 0
    success_rate: float = 0.0
    fallback_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    requests_by_provider: dict[str, int] = {}
    requests_by_engine: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
