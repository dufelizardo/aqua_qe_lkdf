"""
ai_engine/requirement_agent/agent.py
AQuA-QE LKDF — Requirement Agent

Agente cognitivo para:
  - Interpretação de requisitos em linguagem natural
  - Identificação de ambiguidades e gaps
  - Extração de regras de negócio
  - Geração automática de Flows semânticos (DSL)
  - RTM automático (Requirement → Flow linkage)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Requirement Analysis Result
# ---------------------------------------------------------------------------

@dataclass
class BusinessRule:
    description: str
    entities: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)


@dataclass
class RequirementAnalysis:
    requirement_id: str
    original_text: str
    interpreted_intent: str
    business_rules: list[BusinessRule] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    suggested_scenarios: list[str] = field(default_factory=list)
    risk_level: str = "MEDIUM"
    generated_flow_dsl: str = ""


# ---------------------------------------------------------------------------
# Requirement Agent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Você é o AQuA-QE LKDF Requirement Agent — um agente cognitivo especializado em \
Qualidade de Software e Engenharia de Requisitos.

Seu papel:
1. Analisar requisitos em linguagem natural
2. Identificar entidades, regras de negócio, ambiguidades e gaps
3. Gerar Flows semânticos no formato DSL do LKDF (Gherkin em português)
4. Sugerir cenários de cobertura (happy path, edge cases, negative tests)

FORMATO DSL LKDF:
```
# Flow: <NomeFlow>
# Requirement: <REQ-ID> — <texto>
# Adapter: robot-framework
# Priority: HIGH|MEDIUM|LOW

@flow <NomeFlow>
  @scenario <NomeScenario>
    Dado que <pré-condição>
    E <condição adicional>
    Quando <ação do usuário>
    E <ação adicional>
    Então é esperado que <resultado verificável>
    E é esperado que <resultado adicional>
```

REGRAS:
- Use exclusivamente português
- Cada step deve ser verificável e atômico
- Gere pelo menos 3 scenarios: happy path, negative path, edge case
- Identifique TODAS as ambiguidades explicitamente
- Extraia regras de negócio implícitas

Responda SOMENTE em JSON válido, sem markdown, no formato:
{
  "interpreted_intent": "string",
  "business_rules": [{"description": "...", "entities": [], "conditions": [], "outcomes": []}],
  "ambiguities": ["..."],
  "gaps": ["..."],
  "suggested_scenarios": ["HappyPath: ...", "NegativePath: ...", "EdgeCase: ..."],
  "risk_level": "HIGH|MEDIUM|LOW",
  "generated_flow_dsl": "# Flow completo aqui..."
}
"""


class RequirementAgent:
    """
    Agente de IA para análise e transformação de requisitos.
    Usa Claude para reasoning semântico complexo.
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model   = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if not self._client:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic package não instalado. Execute: pip install anthropic"
                )
        return self._client

    async def analyze(
        self,
        requirement_text: str,
        requirement_id: str = "REQ-AUTO",
        context: dict[str, Any] | None = None,
    ) -> RequirementAnalysis:
        """
        Analisa um requisito e retorna a análise completa com Flow gerado.
        """
        log.info("requirement_agent_start", req_id=requirement_id)

        user_message = f"Requisito [{requirement_id}]: \"{requirement_text}\""
        if context:
            user_message += f"\n\nContexto do projeto: {json.dumps(context, ensure_ascii=False)}"

        try:
            client   = self._get_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            raw_text = response.content[0].text
            data     = self._parse_response(raw_text)

        except Exception as exc:
            log.warning("requirement_agent_fallback", error=str(exc))
            data = self._fallback_analysis(requirement_text)

        rules = [
            BusinessRule(**r) if isinstance(r, dict) else BusinessRule(description=str(r))
            for r in data.get("business_rules", [])
        ]

        analysis = RequirementAnalysis(
            requirement_id=requirement_id,
            original_text=requirement_text,
            interpreted_intent=data.get("interpreted_intent", ""),
            business_rules=rules,
            ambiguities=data.get("ambiguities", []),
            gaps=data.get("gaps", []),
            suggested_scenarios=data.get("suggested_scenarios", []),
            risk_level=data.get("risk_level", "MEDIUM"),
            generated_flow_dsl=data.get("generated_flow_dsl", ""),
        )

        log.info(
            "requirement_agent_done",
            req_id=requirement_id,
            rules=len(rules),
            ambiguities=len(analysis.ambiguities),
            scenarios=len(analysis.suggested_scenarios),
        )
        return analysis

    def analyze_sync(
        self,
        requirement_text: str,
        requirement_id: str = "REQ-AUTO",
        context: dict[str, Any] | None = None,
    ) -> RequirementAnalysis:
        """Versão síncrona para uso em contextos não-async."""
        import asyncio
        return asyncio.run(self.analyze(requirement_text, requirement_id, context))

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        clean = raw.strip()
        # Strip markdown fences if present
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return json.loads(clean)

    @staticmethod
    def _fallback_analysis(requirement_text: str) -> dict[str, Any]:
        """Análise básica quando a API não está disponível."""
        words = requirement_text.split()
        entities = [w for w in words if w[0].isupper() and len(w) > 3][:4]
        return {
            "interpreted_intent": f"Verificar comportamento: {requirement_text[:80]}",
            "business_rules": [
                {
                    "description": requirement_text,
                    "entities": entities,
                    "conditions": ["sistema operacional", "usuário autenticado"],
                    "outcomes": ["comportamento esperado verificado"],
                }
            ],
            "ambiguities": [
                "Definição de 'sucesso' não especificada",
                "Critérios de aceite implícitos",
            ],
            "gaps": ["Pré-condições não detalhadas", "Cenários de erro não descritos"],
            "suggested_scenarios": [
                "HappyPath: fluxo principal com dados válidos",
                "NegativePath: dados inválidos devem retornar erro",
                "EdgeCase: estado de borda do sistema",
            ],
            "risk_level": "MEDIUM",
            "generated_flow_dsl": f"""\
# Flow: AutoGeneratedFlow
# Requirement: REQ-AUTO — {requirement_text[:60]}
# Adapter: robot-framework
# Priority: MEDIUM
# Generated-by: RequirementAgent (fallback mode)

@flow AutoGeneratedFlow
  @scenario HappyPath
    Dado que o sistema está operacional
    E que o usuário possui permissões adequadas
    Quando o usuário executa a ação principal
    Então é esperado que o sistema processe corretamente
    E é esperado que o resultado esperado seja exibido

  @scenario NegativePath
    Dado que o sistema está operacional
    Quando o usuário fornece dados inválidos
    Então é esperado que o sistema retorne mensagem de erro apropriada
    E é esperado que nenhum dado seja comprometido

  @scenario EdgeCase
    Dado que uma condição limite está presente
    Quando o usuário tenta executar a ação no limite
    Então é esperado que o sistema trate o caso limite adequadamente
""",
        }
