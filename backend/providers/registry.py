"""
AQuA-QE LKDF — AI Gateway Layer
Provider Registry: catálogo de todos os providers e modelos suportados
"""
from backend.models.schemas import (
    ProviderConfig, ModelConfig, ProviderName,
    ProviderType, EngineType, RoutingStrategy
)


# ─────────────────────────────────────────────
# DEFAULT PROVIDER CONFIGS
# ─────────────────────────────────────────────

DEFAULT_PROVIDERS: dict[ProviderName, ProviderConfig] = {

    # ── CLOUD ───────────────────────────────

    ProviderName.ANTHROPIC: ProviderConfig(
        name=ProviderName.ANTHROPIC,
        provider_type=ProviderType.CLOUD,
        display_name="Anthropic Claude",
        priority=9,
        base_url="https://api.anthropic.com",
        available_models=[
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
        ],
        default_model="claude-sonnet-4-5",
        max_tokens=8192,
        cost_input_per_1k=0.003,
        cost_output_per_1k=0.015,
        supports_vision=True,
        max_context_tokens=200000,
    ),

    ProviderName.OPENAI: ProviderConfig(
        name=ProviderName.OPENAI,
        provider_type=ProviderType.CLOUD,
        display_name="OpenAI GPT",
        priority=8,
        base_url="https://api.openai.com/v1",
        available_models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1-mini"],
        default_model="gpt-4o",
        max_tokens=4096,
        cost_input_per_1k=0.005,
        cost_output_per_1k=0.015,
        supports_vision=True,
        max_context_tokens=128000,
    ),

    ProviderName.AZURE: ProviderConfig(
        name=ProviderName.AZURE,
        provider_type=ProviderType.CLOUD,
        display_name="Azure OpenAI",
        priority=7,
        base_url="https://{resource}.openai.azure.com",
        api_version="2024-02-01",
        available_models=["gpt-4o", "gpt-4-turbo", "gpt-35-turbo"],
        default_model="gpt-4o",
        max_tokens=4096,
        cost_input_per_1k=0.005,
        cost_output_per_1k=0.015,
        supports_vision=True,
        max_context_tokens=128000,
    ),

    ProviderName.GOOGLE: ProviderConfig(
        name=ProviderName.GOOGLE,
        provider_type=ProviderType.CLOUD,
        display_name="Google Gemini",
        priority=7,
        base_url="https://generativelanguage.googleapis.com",
        available_models=[
            "gemini-2.5-flash-lite",              # mais recente leve
            "gemini-2.5-flash-preview-04-17",     # raciocínio avançado
            "gemini-2.5-pro-preview-05-06",       # mais capaz da família 2.5
            "gemini-2.0-flash",                   # rápido, barato, multimodal
            "gemini-2.0-flash-lite",              # ainda mais barato
            "gemini-1.5-pro",                     # contexto 2M (ainda ativo)
        ],
        default_model="gemini-2.0-flash",
        max_tokens=8192,
        cost_input_per_1k=0.00010,
        cost_output_per_1k=0.00040,
        supports_vision=True,
        max_context_tokens=1000000,
    ),

    ProviderName.GROQ: ProviderConfig(
        name=ProviderName.GROQ,
        provider_type=ProviderType.CLOUD,
        display_name="Groq (Ultra-fast)",
        priority=6,
        base_url="https://api.groq.com/openai/v1",
        available_models=["llama-3.1-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        default_model="llama-3.1-70b-versatile",
        max_tokens=4096,
        cost_input_per_1k=0.00059,
        cost_output_per_1k=0.00079,
        max_context_tokens=128000,
    ),

    ProviderName.MISTRAL: ProviderConfig(
        name=ProviderName.MISTRAL,
        provider_type=ProviderType.CLOUD,
        display_name="Mistral AI",
        priority=6,
        base_url="https://api.mistral.ai/v1",
        available_models=["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
        default_model="mistral-large-latest",
        max_tokens=4096,
        cost_input_per_1k=0.004,
        cost_output_per_1k=0.012,
        max_context_tokens=32000,
    ),

    # ── LOCAL ───────────────────────────────

    ProviderName.OLLAMA: ProviderConfig(
        name=ProviderName.OLLAMA,
        provider_type=ProviderType.LOCAL,
        display_name="Ollama (Local)",
        priority=5,
        base_url="http://localhost:11434",
        available_models=["llama3.1:8b", "llama3.1:70b", "mistral:7b", "deepseek-coder:6.7b", "phi3:medium", "qwen2:7b"],
        default_model="llama3.1:8b",
        max_tokens=4096,
        cost_input_per_1k=0.0,
        cost_output_per_1k=0.0,
        timeout_seconds=120,
        max_context_tokens=128000,
    ),

    ProviderName.VLLM: ProviderConfig(
        name=ProviderName.VLLM,
        provider_type=ProviderType.LOCAL,
        display_name="vLLM (High Performance Local)",
        priority=5,
        base_url="http://localhost:8000/v1",
        available_models=["meta-llama/Llama-3.1-8B-Instruct", "mistralai/Mistral-7B-Instruct-v0.3"],
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        max_tokens=4096,
        cost_input_per_1k=0.0,
        cost_output_per_1k=0.0,
        timeout_seconds=120,
        max_context_tokens=128000,
    ),

    ProviderName.LM_STUDIO: ProviderConfig(
        name=ProviderName.LM_STUDIO,
        provider_type=ProviderType.LOCAL,
        display_name="LM Studio (Local UI)",
        priority=4,
        base_url="http://localhost:1234/v1",
        available_models=["local-model"],
        default_model="local-model",
        max_tokens=4096,
        cost_input_per_1k=0.0,
        cost_output_per_1k=0.0,
        timeout_seconds=180,
        max_context_tokens=32000,
    ),

    ProviderName.LLAMACPP: ProviderConfig(
        name=ProviderName.LLAMACPP,
        provider_type=ProviderType.LOCAL,
        display_name="llama.cpp (Lightweight)",
        priority=3,
        base_url="http://localhost:8080",
        available_models=["phi-3-mini", "qwen2-1.5b"],
        default_model="phi-3-mini",
        max_tokens=2048,
        cost_input_per_1k=0.0,
        cost_output_per_1k=0.0,
        timeout_seconds=300,
        max_context_tokens=4096,
    ),
}


# ─────────────────────────────────────────────
# MODEL CATALOG
# ─────────────────────────────────────────────

MODEL_CATALOG: list[ModelConfig] = [
    ModelConfig(
        provider=ProviderName.ANTHROPIC,
        model_id="claude-sonnet-4-5",
        display_name="Claude Sonnet 4.5",
        context_window=200000,
        cost_input_per_1k=0.003,
        cost_output_per_1k=0.015,
        strengths=["análise de ambiguidade", "raciocínio complexo", "português"],
        best_for_engines=[
            EngineType.VALIDATION, EngineType.REQUIREMENT,
            EngineType.CONSISTENCY, EngineType.COMPLIANCE,
        ],
    ),
    ModelConfig(
        provider=ProviderName.ANTHROPIC,
        model_id="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        context_window=200000,
        cost_input_per_1k=0.00025,
        cost_output_per_1k=0.00125,
        strengths=["velocidade", "baixo custo", "normalização"],
        best_for_engines=[EngineType.NORMALIZE, EngineType.SYNTHESIS],
    ),
    ModelConfig(
        provider=ProviderName.OPENAI,
        model_id="gpt-4o",
        display_name="GPT-4o",
        context_window=128000,
        cost_input_per_1k=0.005,
        cost_output_per_1k=0.015,
        strengths=["reasoning geral", "function calling"],
        best_for_engines=[EngineType.BUSINESS_RULE, EngineType.ARTIFACT],
    ),
    ModelConfig(
        provider=ProviderName.GOOGLE,
        model_id="gemini-2.0-flash",
        display_name="Gemini 1.5 Pro",
        context_window=1000000,
        cost_input_per_1k=0.0035,
        cost_output_per_1k=0.0105,
        strengths=["contexto enorme", "síntese", "sumarização"],
        best_for_engines=[EngineType.SYNTHESIS, EngineType.TRACEABILITY],
    ),
    ModelConfig(
        provider=ProviderName.GROQ,
        model_id="llama-3.1-70b-versatile",
        display_name="Llama 3.1 70B (Groq)",
        context_window=128000,
        cost_input_per_1k=0.00059,
        cost_output_per_1k=0.00079,
        strengths=["alta velocidade", "baixo custo"],
        best_for_engines=[EngineType.NORMALIZE, EngineType.RISK],
    ),
    ModelConfig(
        provider=ProviderName.OLLAMA,
        model_id="llama3.1:8b",
        display_name="Llama 3.1 8B (Local)",
        context_window=128000,
        cost_input_per_1k=0.0,
        cost_output_per_1k=0.0,
        strengths=["privacidade total", "offline", "gratuito"],
        best_for_engines=[EngineType.NORMALIZE, EngineType.BUSINESS_RULE],
    ),
    ModelConfig(
        provider=ProviderName.OLLAMA,
        model_id="deepseek-coder:6.7b",
        display_name="DeepSeek Coder 6.7B (Local)",
        context_window=16000,
        cost_input_per_1k=0.0,
        cost_output_per_1k=0.0,
        strengths=["geração técnica", "código", "artefatos"],
        best_for_engines=[EngineType.ARTIFACT],
    ),
]


# ─────────────────────────────────────────────
# DEFAULT ENGINE ROUTING TABLE
# ─────────────────────────────────────────────

DEFAULT_ENGINE_ROUTING = {
    EngineType.NORMALIZE: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-haiku-4-5",
        "fallbacks": [ProviderName.GROQ, ProviderName.OLLAMA],
        "strategy": RoutingStrategy.COST_OPTIMIZED,
    },
    EngineType.REQUIREMENT: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.OPENAI, ProviderName.OLLAMA],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
    EngineType.VALIDATION: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.OPENAI, ProviderName.MISTRAL],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
    EngineType.BUSINESS_RULE: {
        "primary": ProviderName.OPENAI,
        "model": "gpt-4o",
        "fallbacks": [ProviderName.ANTHROPIC, ProviderName.OLLAMA],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
    EngineType.ACCEPTANCE: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.OPENAI, ProviderName.MISTRAL],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
    EngineType.RISK: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.GROQ, ProviderName.OLLAMA],
        "strategy": RoutingStrategy.PERFORMANCE_FIRST,
    },
    EngineType.COVERAGE: {
        "primary": ProviderName.GOOGLE,
        "model": "gemini-2.0-flash",
        "fallbacks": [ProviderName.ANTHROPIC, ProviderName.OPENAI],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
    EngineType.INFERENCE: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.OPENAI, ProviderName.MISTRAL],
        "strategy": RoutingStrategy.PERFORMANCE_FIRST,
    },
    EngineType.SYNTHESIS: {
        "primary": ProviderName.GOOGLE,
        "model": "gemini-2.0-flash",
        "fallbacks": [ProviderName.ANTHROPIC, ProviderName.GROQ],
        "strategy": RoutingStrategy.COST_OPTIMIZED,
    },
    EngineType.CONSISTENCY: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.OPENAI],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
    EngineType.IMPACT: {
        "primary": ProviderName.OPENAI,
        "model": "gpt-4o",
        "fallbacks": [ProviderName.ANTHROPIC, ProviderName.MISTRAL],
        "strategy": RoutingStrategy.PERFORMANCE_FIRST,
    },
    EngineType.COMPLIANCE: {
        "primary": ProviderName.ANTHROPIC,
        "model": "claude-sonnet-4-5",
        "fallbacks": [ProviderName.OPENAI],
        "strategy": RoutingStrategy.PRIVACY_FIRST,
    },
    EngineType.TRACEABILITY: {
        "primary": ProviderName.GOOGLE,
        "model": "gemini-2.0-flash",
        "fallbacks": [ProviderName.ANTHROPIC, ProviderName.GROQ],
        "strategy": RoutingStrategy.COST_OPTIMIZED,
    },
    EngineType.ARTIFACT: {
        "primary": ProviderName.OPENAI,
        "model": "gpt-4o",
        "fallbacks": [ProviderName.OLLAMA, ProviderName.ANTHROPIC],
        "strategy": RoutingStrategy.CAPABILITY_MATCH,
    },
}
