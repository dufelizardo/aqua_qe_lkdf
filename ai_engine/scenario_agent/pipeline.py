"""
ai_engine/scenario_agent/pipeline.py
AQuA-QE LKDF — Cognitive Pipeline: Requirement → Scenario

Orquestra o fluxo completo de inteligência cognitiva:
  1. Requirement Agent analisa o requisito
  2. DSL Parser gera o Flow a partir do DSL gerado
  3. Scenario Agent enriquece com IA
  4. Retorna tudo pronto para execução

Uso:
    pipeline = CognitivePipeline()
    result   = await pipeline.run("Usuário bloqueado não deve acessar sistema")
    # result.flow     → Flow pronto para ExecutionEngine
    # result.scenarios → todos os cenários (regras + IA + segurança)
    # result.dsl      → DSL gerado para visualização
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import structlog

from ai_engine.requirement_agent.agent import RequirementAgent, RequirementAnalysis
from ai_engine.scenario_agent.agent import ScenarioAgent, ScenarioAgentResult
from runtime_core.scenario_engine.engine import ComposedScenario
from shared.models import Flow, ProjectContext

log = structlog.get_logger(__name__)


@dataclass
class CognitivePipelineResult:
    """Resultado completo do pipeline cognitivo."""
    requirement_id:   str
    requirement_text: str
    analysis:         RequirementAnalysis
    scenario_result:  ScenarioAgentResult
    flow:             Flow
    dsl:              str

    @property
    def all_scenarios(self) -> list[ComposedScenario]:
        return self.scenario_result.all_scenarios

    @property
    def total_scenarios(self) -> int:
        return self.scenario_result.total_scenario_count

    @property
    def coverage_score(self) -> float:
        return self.scenario_result.coverage_score

    def summary(self) -> dict[str, Any]:
        return {
            "requirement_id":    self.requirement_id,
            "requirement_text":  self.requirement_text[:80],
            "risk_level":        self.analysis.risk_level,
            "total_scenarios":   self.total_scenarios,
            "ai_scenarios":      len(self.scenario_result.ai_scenarios),
            "security_scenarios":len(self.scenario_result.security_scenarios),
            "datasets":          len(self.scenario_result.datasets),
            "cross_impact":      len(self.scenario_result.cross_impact),
            "coverage_score":    f"{self.coverage_score:.0f}%",
            "gaps":              self.scenario_result.coverage_gaps,
            "recommendations":   self.scenario_result.recommendations,
        }


class CognitivePipeline:
    """
    Pipeline cognitivo ponta-a-ponta do LKDF.

    Requirement (texto) → análise → DSL → Flow → cenários IA → resultado
    """

    def __init__(
        self,
        api_key: str | None = None,
        model:   str        = "claude-sonnet-4-20250514",
        mode:    str        = "full",
    ) -> None:
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._req_agent  = RequirementAgent(api_key=key, model=model)
        self._scen_agent = ScenarioAgent(api_key=key, model=model, mode=mode)

    async def run(
        self,
        requirement_text: str,
        requirement_id:   str              = "REQ-AUTO",
        context:          ProjectContext   | None = None,
        related_req_ids:  list[str]        | None = None,
    ) -> CognitivePipelineResult:
        """
        Executa o pipeline cognitivo completo.

        Args:
            requirement_text: Texto do requisito em linguagem natural
            requirement_id:   ID do requisito (ex: "REQ-007")
            context:          Contexto do projeto para personalização
            related_req_ids:  IDs de requisitos relacionados para cross-impact
        """
        ctx = context or ProjectContext()

        log.info("pipeline_start", req_id=requirement_id)

        # Fase 1: Requirement Agent
        log.info("pipeline_step", step="requirement_agent")
        analysis = await self._req_agent.analyze(
            requirement_text=requirement_text,
            requirement_id=requirement_id,
            context={
                "framework": ctx.framework,
                "auth_type":  ctx.auth_type,
                "base_url":   ctx.base_url,
            } if ctx else None,
        )

        # Fase 2: Parse do DSL gerado
        log.info("pipeline_step", step="dsl_parse")
        flow, dsl = self._parse_flow(analysis)

        # Fase 3: Scenario Agent
        log.info("pipeline_step", step="scenario_agent")
        scenario_result = await self._scen_agent.analyze(
            flow=flow,
            analysis=analysis,
            related_req_ids=related_req_ids,
        )

        result = CognitivePipelineResult(
            requirement_id=requirement_id,
            requirement_text=requirement_text,
            analysis=analysis,
            scenario_result=scenario_result,
            flow=flow,
            dsl=dsl,
        )

        log.info(
            "pipeline_done",
            req_id=requirement_id,
            scenarios=result.total_scenarios,
            coverage=f"{result.coverage_score:.0f}%",
        )
        return result

    @staticmethod
    def _parse_flow(analysis: RequirementAnalysis) -> tuple[Flow, str]:
        """Tenta parsear o DSL do Requirement Agent; usa fallback se necessário."""
        from runtime_core.parser.dsl_parser import DSLParser, DSLParseError

        dsl = analysis.generated_flow_dsl or ""
        if dsl.strip():
            try:
                flow = DSLParser().parse(dsl)
                return flow, dsl
            except DSLParseError as exc:
                log.warning("pipeline_dsl_parse_failed", error=str(exc))

        # Fallback: flow mínimo a partir da análise
        from shared.models import AdapterType, Scenario, SemanticStep, StepKeyword, StepType

        fallback_dsl = f"""# Flow: FallbackFlow
# Requirement: {analysis.requirement_id} — {analysis.original_text[:60]}
# Adapter: robot-framework

@flow FallbackFlow
  @scenario HappyPath
    Dado que o sistema está operacional
    Quando o usuário executa a ação principal
    Então é esperado que o resultado seja correto

  @scenario NegativePath
    Dado que uma condição inválida está presente
    Quando o usuário tenta executar a ação
    Então é esperado que o sistema retorne erro adequado
"""
        try:
            flow = DSLParser().parse(fallback_dsl)
        except DSLParseError:
            step = SemanticStep(
                keyword=StepKeyword.ENTAO, step_type=StepType.THEN,
                text="Então é esperado que o sistema funcione",
            )
            scenario = Scenario(
                name="HappyPath", steps=[step],
                requirement_ref=analysis.requirement_id,
            )
            flow = Flow(
                name="FallbackFlow",
                requirement_ref=analysis.requirement_id,
                adapter=AdapterType.ROBOT,
                scenarios=[scenario],
            )

        return flow, fallback_dsl
