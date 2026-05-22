"""
ai_engine/scenario_agent/agent.py
AQuA-QE LKDF — Scenario Agent

Agente cognitivo para:
  - Geração de cenários além do óbvio (edge cases, segurança, concorrência)
  - Síntese de datasets semanticamente corretos para o domínio
  - Análise de impacto cruzado entre requisitos
  - Detecção de contradições e cenários faltantes
  - Sugestão automática de cenários de segurança
  - Enriquecimento dos ComposedScenarios do ScenarioEngine com IA
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import structlog

from ai_engine.requirement_agent.agent import RequirementAnalysis
from runtime_core.scenario_engine.engine import (
    ComposedScenario,
    ScenarioCategory,
    ScenarioEngine,
    TestDataset,
)
from shared.models import Flow, Priority, Scenario, SemanticStep, StepKeyword, StepType

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CrossImpactIssue:
    """Contradição ou dependência entre dois requisitos."""
    req_a:       str
    req_b:       str
    issue_type:  str        # contradiction | dependency | overlap
    description: str
    suggested_scenario: str = ""


@dataclass
class SecurityScenario:
    """Cenário de segurança gerado automaticamente."""
    name:        str
    attack_type: str        # sql_injection | xss | idor | csrf | auth_bypass | ...
    dsl_steps:   list[str] = field(default_factory=list)
    severity:    str = "HIGH"


@dataclass
class ScenarioAgentResult:
    """Resultado completo de uma análise do Scenario Agent."""
    requirement_id:     str
    original_scenarios: list[ComposedScenario]
    ai_scenarios:       list[ComposedScenario]
    security_scenarios: list[SecurityScenario]
    datasets:           dict[str, TestDataset]
    cross_impact:       list[CrossImpactIssue]
    coverage_score:     float
    coverage_gaps:      list[str]
    recommendations:    list[str]
    raw_ai_response:    dict[str, Any] = field(default_factory=dict)

    @property
    def all_scenarios(self) -> list[ComposedScenario]:
        return self.original_scenarios + self.ai_scenarios

    @property
    def total_scenario_count(self) -> int:
        return len(self.all_scenarios)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Você é o AQuA-QE LKDF Scenario Agent — um agente cognitivo especializado em \
Quality Engineering, Test Design e Análise de Risco.

Seu papel é analisar requisitos de software e gerar cenários de teste abrangentes, \
incluindo casos que QAs iniciantes tipicamente esquecem.

RESPONSABILIDADES:
1. Gerar edge cases não-óbvios (concorrência, estado parcial, timeout, encoding)
2. Sintetizar datasets semanticamente corretos para o domínio
3. Identificar cenários de segurança (OWASP Top 10 aplicável)
4. Detectar contradições e dependências entre requisitos
5. Avaliar cobertura e identificar gaps críticos

FORMATO DSL DE STEPS (para cenários gerados):
  "Dado que <pré-condição>"
  "E <condição adicional>"
  "Quando <ação>"
  "Então é esperado que <resultado>"

CATEGORIAS DE CENÁRIO:
  happy_path, negative, boundary, edge_case, security, performance, regression

RESPONDA APENAS em JSON válido, sem markdown, no formato:
{
  "ai_scenarios": [
    {
      "name": "NomeCamelCase",
      "category": "edge_case",
      "priority": "HIGH|MEDIUM|LOW",
      "rationale": "por que este cenário é importante",
      "steps": ["Dado que ...", "Quando ...", "Então é esperado que ..."],
      "tags": ["edge-case", "concurrent"]
    }
  ],
  "security_scenarios": [
    {
      "name": "NomeCamelCase",
      "attack_type": "sql_injection",
      "severity": "HIGH|MEDIUM|LOW",
      "steps": ["Dado que ...", "Quando ...", "Então é esperado que ..."]
    }
  ],
  "datasets": {
    "campo_nome": {
      "description": "Valores para o campo X",
      "valid": ["valor1", "valor2"],
      "invalid": ["val_invalido"],
      "boundary": ["valor_borda"]
    }
  },
  "cross_impact": [
    {
      "req_a": "REQ-001",
      "req_b": "REQ-007",
      "issue_type": "contradiction",
      "description": "descrição do conflito",
      "suggested_scenario": "cenário que testa a interseção"
    }
  ],
  "coverage_gaps": ["gap 1", "gap 2"],
  "recommendations": ["recomendação 1"]
}
"""


# ---------------------------------------------------------------------------
# Scenario Agent
# ---------------------------------------------------------------------------

class ScenarioAgent:
    """
    Agente cognitivo para geração e enriquecimento de cenários de teste.

    Combina:
      - ScenarioEngine (regras determinísticas — Fase 1)
      - Claude (reasoning semântico — Fase 2)

    O agente pode operar em dois modos:
      - full:     usa Claude para raciocínio completo
      - rules_only: usa apenas ScenarioEngine (sem API)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model:   str        = "claude-sonnet-4-20250514",
        mode:    str        = "full",   # full | rules_only
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model   = model
        self.mode    = mode
        self._engine = ScenarioEngine()
        self._client: Any = None

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        flow:              Flow,
        analysis:          RequirementAnalysis | None = None,
        related_req_ids:   list[str] | None           = None,
    ) -> ScenarioAgentResult:
        """
        Análise completa de um Flow com enriquecimento cognitivo.

        Args:
            flow:            Flow parseado pelo DSL Parser
            analysis:        RequirementAnalysis do Requirement Agent (opcional)
            related_req_ids: IDs de requisitos relacionados para análise de impacto
        """
        log.info(
            "scenario_agent_start",
            flow=flow.name,
            scenarios=len(flow.scenarios),
            mode=self.mode,
        )

        # 1. Cenários determinísticos via ScenarioEngine
        original = self._engine.compose(flow)
        coverage = self._engine.analyze_coverage(flow)

        # 2. Enriquecimento via IA
        if self.mode == "full" and self.api_key:
            try:
                ai_data = await self._call_claude(flow, analysis, related_req_ids)
            except Exception as exc:
                log.warning("scenario_agent_fallback", error=str(exc))
                ai_data = self._rule_based_enrichment(flow, original)
        else:
            ai_data = self._rule_based_enrichment(flow, original)

        # 3. Converte resposta da IA em ComposedScenarios
        ai_scenarios   = self._parse_ai_scenarios(ai_data.get("ai_scenarios", []), flow)
        sec_scenarios  = self._parse_security_scenarios(ai_data.get("security_scenarios", []))
        datasets       = self._parse_datasets(ai_data.get("datasets", {}))
        cross_impact   = self._parse_cross_impact(ai_data.get("cross_impact", []))
        gaps           = ai_data.get("coverage_gaps", coverage.gaps)
        recommendations = ai_data.get("recommendations", coverage.recommendations)

        result = ScenarioAgentResult(
            requirement_id=flow.requirement_ref,
            original_scenarios=original,
            ai_scenarios=ai_scenarios,
            security_scenarios=sec_scenarios,
            datasets=datasets,
            cross_impact=cross_impact,
            coverage_score=self._final_coverage_score(coverage.coverage_score, ai_scenarios, sec_scenarios),
            coverage_gaps=gaps,
            recommendations=recommendations,
            raw_ai_response=ai_data,
        )

        log.info(
            "scenario_agent_done",
            flow=flow.name,
            original=len(original),
            ai_generated=len(ai_scenarios),
            security=len(sec_scenarios),
            datasets=len(datasets),
            cross_impact=len(cross_impact),
            coverage=f"{result.coverage_score:.0f}%",
        )
        return result

    async def enrich_from_requirement(
        self,
        analysis: RequirementAnalysis,
    ) -> ScenarioAgentResult:
        """
        Conveniência: gera um Flow a partir da análise e analisa.
        Útil quando não há DSL existente.
        """
        from runtime_core.parser.dsl_parser import DSLParser

        dsl = analysis.generated_flow_dsl
        if not dsl or not dsl.strip():
            dsl = self._minimal_dsl_from_analysis(analysis)

        try:
            flow = DSLParser().parse(dsl)
        except Exception:
            flow = self._minimal_flow_from_analysis(analysis)

        return await self.analyze(flow, analysis)

    # ------------------------------------------------------------------
    # Claude call
    # ------------------------------------------------------------------

    async def _call_claude(
        self,
        flow:            Flow,
        analysis:        RequirementAnalysis | None,
        related_req_ids: list[str] | None,
    ) -> dict[str, Any]:
        try:
            client = self._get_client()
        except RuntimeError as exc:
            log.warning("claude_unavailable", error=str(exc))
            return self._rule_based_enrichment(flow, self._engine.compose(flow))

        # Build prompt
        scenarios_summary = "\n".join(
            f"  - {s.name}: {len(s.steps)} steps ({s.step_type if hasattr(s, 'step_type') else ''})"
            for s in flow.scenarios
        )
        analysis_ctx = ""
        if analysis:
            rules = "\n".join(f"  - {r.description}" for r in analysis.business_rules[:5])
            ambs  = "\n".join(f"  - {a}" for a in analysis.ambiguities[:3])
            analysis_ctx = f"""
Análise do Requirement Agent:
- Intenção: {analysis.interpreted_intent}
- Regras de negócio:
{rules}
- Ambiguidades identificadas:
{ambs}
- Risco: {analysis.risk_level}
"""

        related_ctx = ""
        if related_req_ids:
            related_ctx = f"\nRequisitos relacionados para análise de impacto: {', '.join(related_req_ids)}"

        steps_text = ""
        for scenario in flow.scenarios:
            steps_text += f"\n@scenario {scenario.name}\n"
            for step in scenario.steps:
                steps_text += f"  {step.text}\n"

        user_msg = f"""Flow: {flow.name}
Requisito: {flow.requirement_ref}
Adapter: {flow.adapter}
{analysis_ctx}
{related_ctx}

Scenarios existentes:
{steps_text}

Gere cenários adicionais, datasets, análise de segurança e cross-impact."""

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(clean)
        except json.JSONDecodeError as exc:
            log.warning("scenario_agent_json_error", error=str(exc))
            return self._rule_based_enrichment(flow, self._engine.compose(flow))
        except Exception as exc:
            log.error("scenario_agent_claude_error", error=str(exc))
            return self._rule_based_enrichment(flow, self._engine.compose(flow))

    # ------------------------------------------------------------------
    # Rule-based fallback (sem IA)
    # ------------------------------------------------------------------

    def _rule_based_enrichment(
        self,
        flow:     Flow,
        original: list[ComposedScenario],
    ) -> dict[str, Any]:
        """
        Enriquecimento determinístico quando a API não está disponível.
        Aplica heurísticas de domínio baseadas nos steps existentes.
        """
        all_text   = " ".join(s.text for sc in flow.scenarios for s in sc.steps).lower()
        has_auth   = any(kw in all_text for kw in ("login", "senha", "credencial", "autent"))
        has_form   = any(kw in all_text for kw in ("insere", "preenche", "campo", "email"))
        has_nav    = any(kw in all_text for kw in ("página", "redireciona", "acessa"))
        is_high    = flow.priority == Priority.HIGH

        ai_scenarios: list[dict] = []
        security_scenarios: list[dict] = []
        datasets: dict[str, dict] = {}
        gaps: list[str] = []
        recommendations: list[str] = []

        # --- Cenários por domínio detectado ---
        if has_auth:
            ai_scenarios += [
                {
                    "name": "SessionExpiration",
                    "category": "edge_case",
                    "priority": "HIGH",
                    "rationale": "Token JWT expira durante a sessão",
                    "steps": [
                        "Dado que o usuário está autenticado",
                        "E que o token de sessão está prestes a expirar",
                        "Quando o token expira durante navegação",
                        "Então é esperado que o usuário seja redirecionado para login",
                        "E é esperado que os dados não sejam perdidos",
                    ],
                    "tags": ["session", "edge-case"],
                },
                {
                    "name": "ConcurrentLogin",
                    "category": "edge_case",
                    "priority": "MEDIUM",
                    "rationale": "Mesmo usuário em dois dispositivos simultâneos",
                    "steps": [
                        "Dado que o usuário está autenticado no dispositivo A",
                        "Quando o usuário faz login no dispositivo B com as mesmas credenciais",
                        "Então é esperado que o sistema trate o acesso concorrente corretamente",
                    ],
                    "tags": ["concurrent", "edge-case"],
                },
            ]
            security_scenarios += [
                {
                    "name": "BruteForceProtection",
                    "attack_type": "brute_force",
                    "severity": "HIGH",
                    "steps": [
                        "Dado que o usuário tenta login com senha incorreta 5 vezes",
                        "Quando a sexta tentativa é realizada",
                        "Então é esperado que a conta seja temporariamente bloqueada",
                        "E é esperado que o administrador seja notificado",
                    ],
                },
                {
                    "name": "SqlInjectionLogin",
                    "attack_type": "sql_injection",
                    "severity": "CRITICAL",
                    "steps": [
                        "Dado que o usuário está na página de login",
                        "Quando o usuário insere \"' OR '1'='1\" no campo email",
                        "Então é esperado que o sistema rejeite a entrada",
                        "E é esperado que nenhum dado seja exposto",
                    ],
                },
            ]
            datasets["credenciais"] = {
                "description": "Datasets para campos de autenticação",
                "valid": ["usuario@empresa.com", "admin@empresa.com"],
                "invalid": ["nao-e-email", "", "a" * 256, "' OR '1'='1"],
                "boundary": ["a@b.co", "x" * 254 + "@empresa.com"],
            }

        if has_form:
            ai_scenarios.append({
                "name": "SpecialCharactersInput",
                "category": "boundary",
                "priority": "MEDIUM",
                "rationale": "Caracteres especiais e Unicode nos campos",
                "steps": [
                    "Dado que o usuário está no formulário",
                    "Quando o usuário insere \"<script>alert(1)</script>\" no campo nome",
                    "Então é esperado que o sistema sanitize a entrada",
                    "E é esperado que nenhum script seja executado",
                ],
                "tags": ["xss", "security", "boundary"],
            })
            ai_scenarios.append({
                "name": "EmptyFormSubmission",
                "category": "negative",
                "priority": "HIGH",
                "rationale": "Submissão sem preencher campos obrigatórios",
                "steps": [
                    "Dado que o usuário está no formulário",
                    "Quando o usuário tenta submeter sem preencher campos obrigatórios",
                    "Então é esperado que mensagens de validação sejam exibidas",
                    "E é esperado que o formulário não seja enviado",
                ],
                "tags": ["validation", "negative"],
            })

        if has_nav:
            ai_scenarios.append({
                "name": "DirectUrlAccess",
                "category": "security",
                "priority": "HIGH",
                "rationale": "Acesso direto a URL protegida sem autenticação",
                "steps": [
                    "Dado que o usuário não está autenticado",
                    "Quando o usuário tenta acessar a URL protegida diretamente",
                    "Então é esperado que seja redirecionado para login",
                    "E é esperado que a URL original seja preservada para redirect pós-login",
                ],
                "tags": ["security", "auth"],
            })

        if is_high:
            ai_scenarios.append({
                "name": "NetworkTimeoutRecovery",
                "category": "edge_case",
                "priority": "MEDIUM",
                "rationale": "Comportamento em perda de conexão durante operação crítica",
                "steps": [
                    "Dado que o usuário está executando uma operação crítica",
                    "Quando a conexão de rede é perdida durante a operação",
                    "Então é esperado que o sistema exiba mensagem de erro apropriada",
                    "E é esperado que a operação possa ser retomada após reconexão",
                ],
                "tags": ["network", "resilience"],
            })

        # Gaps e recomendações
        categories = {s["category"] for s in ai_scenarios}
        if "performance" not in categories:
            gaps.append("Nenhum cenário de performance/carga definido.")
            recommendations.append("Adicione um cenário de teste sob alta carga simultânea.")
        if "security" not in categories and not security_scenarios:
            gaps.append("Nenhum cenário de segurança identificado.")
            recommendations.append("Revise OWASP Top 10 aplicável ao contexto.")

        return {
            "ai_scenarios":       ai_scenarios,
            "security_scenarios": security_scenarios,
            "datasets":           datasets,
            "cross_impact":       [],
            "coverage_gaps":      gaps,
            "recommendations":    recommendations,
        }

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _parse_ai_scenarios(
        self,
        raw: list[dict],
        flow: Flow,
    ) -> list[ComposedScenario]:
        result: list[ComposedScenario] = []
        for item in raw:
            try:
                steps   = self._steps_from_list(item.get("steps", []))
                scenario = Scenario(
                    name=item.get("name", "AIScenario"),
                    description=item.get("rationale", ""),
                    steps=steps,
                    tags=item.get("tags", []) + ["ai-generated"],
                    requirement_ref=flow.requirement_ref,
                )
                priority_raw = item.get("priority", "MEDIUM").upper()
                try:
                    priority = Priority[priority_raw]
                except KeyError:
                    priority = Priority.MEDIUM

                cat_raw = item.get("category", "edge_case")
                try:
                    category = ScenarioCategory(cat_raw)
                except ValueError:
                    category = ScenarioCategory.EDGE_CASE

                composed = ComposedScenario(
                    scenario=scenario,
                    category=category,
                    priority_score={"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}.get(
                        priority_raw, 0.6
                    ),
                    estimated_duration_ms=len(steps) * 350,
                    tags=scenario.tags,
                )
                result.append(composed)
            except Exception as exc:
                log.warning("parse_ai_scenario_error", error=str(exc), item=item)
        return result

    def _parse_security_scenarios(self, raw: list[dict]) -> list[SecurityScenario]:
        result: list[SecurityScenario] = []
        for item in raw:
            try:
                result.append(SecurityScenario(
                    name=item.get("name", "SecurityScenario"),
                    attack_type=item.get("attack_type", "unknown"),
                    dsl_steps=item.get("steps", []),
                    severity=item.get("severity", "HIGH"),
                ))
            except Exception as exc:
                log.warning("parse_security_scenario_error", error=str(exc))
        return result

    def _parse_datasets(self, raw: dict[str, dict]) -> dict[str, TestDataset]:
        result: dict[str, TestDataset] = {}
        for field_name, spec in raw.items():
            rows: list[dict] = []
            for v in spec.get("valid", []):
                rows.append({field_name: v, "type": "valid", "expected": "success"})
            for v in spec.get("invalid", []):
                rows.append({field_name: v, "type": "invalid", "expected": "error"})
            for v in spec.get("boundary", []):
                rows.append({field_name: v, "type": "boundary", "expected": "boundary"})
            result[field_name] = TestDataset(
                name=f"dataset_{field_name}",
                rows=rows,
                description=spec.get("description", ""),
            )
        return result

    def _parse_cross_impact(self, raw: list[dict]) -> list[CrossImpactIssue]:
        result: list[CrossImpactIssue] = []
        for item in raw:
            try:
                result.append(CrossImpactIssue(
                    req_a=item.get("req_a", ""),
                    req_b=item.get("req_b", ""),
                    issue_type=item.get("issue_type", "dependency"),
                    description=item.get("description", ""),
                    suggested_scenario=item.get("suggested_scenario", ""),
                ))
            except Exception as exc:
                log.warning("parse_cross_impact_error", error=str(exc))
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _steps_from_list(self, raw_steps: list[str]) -> list[SemanticStep]:
        """Converte lista de strings DSL em SemanticStep objects."""
        from runtime_core.semantic_engine.intent_resolver import IntentResolver
        resolver = IntentResolver()
        steps: list[SemanticStep] = []

        _KW_MAP = {
            "dado":   (StepKeyword.DADO,  StepType.GIVEN),
            "quando": (StepKeyword.QUANDO, StepType.WHEN),
            "então":  (StepKeyword.ENTAO,  StepType.THEN),
            "entao":  (StepKeyword.ENTAO,  StepType.THEN),
            "e":      (StepKeyword.E,      StepType.AND),
        }
        last_type = StepType.GIVEN

        for raw in raw_steps:
            first = raw.split()[0].lower().rstrip("que").strip() if raw.split() else ""
            kw, stype = _KW_MAP.get(first, (StepKeyword.E, StepType.AND))
            if stype == StepType.AND:
                stype = last_type
            else:
                last_type = stype

            step = SemanticStep(keyword=kw, step_type=stype, text=raw, raw_line=raw)
            step = resolver.enrich_step(step)
            steps.append(step)

        return steps

    @staticmethod
    def _final_coverage_score(
        base: float,
        ai_scenarios: list[ComposedScenario],
        sec_scenarios: list[SecurityScenario],
    ) -> float:
        bonus = min(20.0, len(ai_scenarios) * 3.0 + len(sec_scenarios) * 5.0)
        return min(100.0, base + bonus)

    def _get_client(self) -> Any:
        if not self._client:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic não instalado. Execute: pip install anthropic"
                )
        return self._client

    @staticmethod
    def _minimal_dsl_from_analysis(analysis: RequirementAnalysis) -> str:
        return f"""# Flow: AnalysisFlow
# Requirement: {analysis.requirement_id}
# Adapter: robot-framework

@flow AnalysisFlow
  @scenario HappyPath
    Dado que o sistema está configurado corretamente
    Quando o usuário executa a ação principal
    Então é esperado que o resultado seja o esperado
"""

    @staticmethod
    def _minimal_flow_from_analysis(analysis: RequirementAnalysis) -> Flow:
        from shared.models import AdapterType
        step = SemanticStep(
            keyword=StepKeyword.ENTAO,
            step_type=StepType.THEN,
            text="Então é esperado que o sistema funcione",
        )
        scenario = Scenario(
            name="HappyPath",
            steps=[step],
            requirement_ref=analysis.requirement_id,
        )
        return Flow(
            name="AnalysisFlow",
            requirement_ref=analysis.requirement_id,
            adapter=AdapterType.ROBOT,
            scenarios=[scenario],
        )
