"""
tests/unit/test_scenario_agent.py
AQuA-QE LKDF — Unit Tests: Scenario Agent & Cognitive Pipeline
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from ai_engine.scenario_agent.agent import (
    CrossImpactIssue,
    ScenarioAgent,
    ScenarioAgentResult,
    SecurityScenario,
)
from ai_engine.scenario_agent.pipeline import CognitivePipeline, CognitivePipelineResult
from runtime_core.parser.dsl_parser import DSLParser
from runtime_core.scenario_engine.engine import ScenarioCategory
from shared.models import AdapterType, Flow, Priority, ProjectContext, Scenario, SemanticStep, StepKeyword, StepType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LOGIN_DSL = """\
# Flow: LoginFlow
# Requirement: REQ-001 — Login deve ser autenticado
# Adapter: robot-framework
# Priority: HIGH

@flow LoginFlow
  @scenario ValidLogin
    Dado que o usuário está na página de login
    E que o usuário possui credenciais válidas
    Quando o usuário insere "usuario@empresa.com" no campo email
    E o usuário insere "senha123" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que o usuário seja redirecionado para o dashboard
    E é esperado que a mensagem "Login realizado com sucesso" seja exibida

  @scenario InvalidLogin
    Dado que o usuário está na página de login
    Quando o usuário insere "errado@test.com" no campo email
    E o usuário insere "senhaerrada" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Credenciais inválidas" seja exibida
"""

BLOCKED_DSL = """\
# Flow: BlockedUserFlow
# Requirement: REQ-007 — Usuário bloqueado não deve acessar sistema
# Adapter: robot-framework
# Priority: HIGH

@flow BlockedUserFlow
  @scenario BlockedUserAttempt
    Dado que o usuário "joao@empresa.com" está com conta bloqueada
    Quando o usuário tenta fazer login com credenciais corretas
    Então é esperado que o acesso seja negado
    E é esperado que a mensagem "Conta bloqueada" seja exibida
"""


def make_flow(dsl: str = LOGIN_DSL) -> Flow:
    return DSLParser().parse(dsl)


def make_agent(mode: str = "rules_only") -> ScenarioAgent:
    return ScenarioAgent(api_key="test", mode=mode)


# ---------------------------------------------------------------------------
# ScenarioAgent — rule-based mode
# ---------------------------------------------------------------------------

class TestScenarioAgentRulesOnly:

    @pytest.mark.asyncio
    async def test_analyze_returns_result(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert isinstance(result, ScenarioAgentResult)
        assert "REQ-001" in result.requirement_id

    @pytest.mark.asyncio
    async def test_original_scenarios_from_engine(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert len(result.original_scenarios) == 2  # ValidLogin + InvalidLogin

    @pytest.mark.asyncio
    async def test_ai_scenarios_generated(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert len(result.ai_scenarios) > 0

    @pytest.mark.asyncio
    async def test_security_scenarios_for_auth_flow(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert len(result.security_scenarios) > 0
        attack_types = {s.attack_type for s in result.security_scenarios}
        assert len(attack_types) > 0

    @pytest.mark.asyncio
    async def test_datasets_generated_for_auth(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert len(result.datasets) > 0
        for ds in result.datasets.values():
            assert len(ds.rows) > 0

    @pytest.mark.asyncio
    async def test_all_scenarios_combines_both(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert result.total_scenario_count == len(result.original_scenarios) + len(result.ai_scenarios)
        assert result.all_scenarios == result.original_scenarios + result.ai_scenarios

    @pytest.mark.asyncio
    async def test_coverage_score_above_base(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        assert result.coverage_score > 0.0
        assert result.coverage_score <= 100.0

    @pytest.mark.asyncio
    async def test_ai_scenarios_have_steps(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        for sc in result.ai_scenarios:
            assert len(sc.scenario.steps) > 0

    @pytest.mark.asyncio
    async def test_ai_scenarios_tagged_ai_generated(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        for sc in result.ai_scenarios:
            assert "ai-generated" in sc.scenario.tags

    @pytest.mark.asyncio
    async def test_ai_scenarios_have_valid_priority(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        for sc in result.ai_scenarios:
            assert 0.0 <= sc.priority_score <= 1.0

    @pytest.mark.asyncio
    async def test_ai_scenarios_have_valid_category(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        valid_cats = set(ScenarioCategory)
        for sc in result.ai_scenarios:
            assert sc.category in valid_cats

    @pytest.mark.asyncio
    async def test_security_scenario_has_steps(self):
        agent  = make_agent()
        flow   = make_flow()
        result = await agent.analyze(flow)

        for sec in result.security_scenarios:
            assert len(sec.dsl_steps) > 0
            assert sec.severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")

    @pytest.mark.asyncio
    async def test_blocked_user_flow(self):
        agent  = make_agent()
        flow   = make_flow(BLOCKED_DSL)
        result = await agent.analyze(flow)

        assert "REQ-007" in result.requirement_id
        assert result.total_scenario_count > 0

    @pytest.mark.asyncio
    async def test_enrich_from_requirement(self):
        from ai_engine.requirement_agent.agent import RequirementAnalysis, BusinessRule
        agent = make_agent()
        analysis = RequirementAnalysis(
            requirement_id="REQ-TEST",
            original_text="Usuário bloqueado não deve fazer login",
            interpreted_intent="Controle de acesso por status de conta",
            business_rules=[
                BusinessRule(
                    description="Conta bloqueada impede acesso",
                    entities=["usuário", "conta"],
                    conditions=["conta bloqueada"],
                    outcomes=["acesso negado"],
                )
            ],
            ambiguities=["Definição de bloqueado (temp vs perm?)"],
            risk_level="HIGH",
            generated_flow_dsl=BLOCKED_DSL,
        )
        result = await agent.enrich_from_requirement(analysis)

        assert "REQ-007" in result.requirement_id
        assert result.total_scenario_count > 0

    @pytest.mark.asyncio
    async def test_steps_from_list_resolves_intents(self):
        agent = make_agent()
        steps = agent._steps_from_list([
            "Dado que o usuário está na página de login",
            "Quando o usuário insere \"test@test.com\" no campo email",
            "Então é esperado que a mensagem de erro seja exibida",
        ])

        assert len(steps) == 3
        assert steps[0].step_type == StepType.GIVEN
        assert steps[1].step_type == StepType.WHEN
        assert steps[2].step_type == StepType.THEN
        for step in steps:
            assert step.intent != ""
            assert step.action != ""


# ---------------------------------------------------------------------------
# ScenarioAgent — with mocked Claude
# ---------------------------------------------------------------------------

MOCK_CLAUDE_RESPONSE = {
    "ai_scenarios": [
        {
            "name": "RaceConditionLogin",
            "category": "edge_case",
            "priority": "HIGH",
            "rationale": "Duas requisições de login simultâneas",
            "steps": [
                "Dado que dois clientes tentam login simultâneo com o mesmo usuário",
                "Quando ambas as requisições chegam ao servidor simultaneamente",
                "Então é esperado que apenas uma sessão seja criada",
            ],
            "tags": ["concurrent", "race-condition"],
        }
    ],
    "security_scenarios": [
        {
            "name": "TimingAttack",
            "attack_type": "timing_attack",
            "severity": "MEDIUM",
            "steps": [
                "Dado que o atacante mede o tempo de resposta do login",
                "Quando senhas incorretas são testadas sistematicamente",
                "Então é esperado que o tempo de resposta seja constante",
            ],
        }
    ],
    "datasets": {
        "email": {
            "description": "Emails para teste",
            "valid": ["user@domain.com", "admin@corp.com"],
            "invalid": ["nao-email", "", "a@"],
            "boundary": ["a@b.co", "x" * 63 + "@" + "d" * 63 + ".com"],
        }
    },
    "cross_impact": [
        {
            "req_a": "REQ-001",
            "req_b": "REQ-007",
            "issue_type": "dependency",
            "description": "Usuário bloqueado pode ainda ter sessão ativa",
            "suggested_scenario": "TestBlockedUserWithActiveSession",
        }
    ],
    "coverage_gaps": ["Nenhum teste de performance"],
    "recommendations": ["Adicione load test para o endpoint de login"],
}


class TestScenarioAgentWithMockedClaude:

    @pytest.mark.asyncio
    async def test_full_mode_uses_claude(self):
        agent = ScenarioAgent(api_key="sk-fake", mode="full")
        flow  = make_flow()

        with patch.object(agent, "_call_claude", new=AsyncMock(return_value=MOCK_CLAUDE_RESPONSE)):
            result = await agent.analyze(flow)

        assert len(result.ai_scenarios) == 1
        assert result.ai_scenarios[0].scenario.name == "RaceConditionLogin"
        assert result.ai_scenarios[0].category == ScenarioCategory.EDGE_CASE

    @pytest.mark.asyncio
    async def test_security_scenarios_parsed(self):
        agent = ScenarioAgent(api_key="sk-fake", mode="full")
        flow  = make_flow()

        with patch.object(agent, "_call_claude", new=AsyncMock(return_value=MOCK_CLAUDE_RESPONSE)):
            result = await agent.analyze(flow)

        assert len(result.security_scenarios) == 1
        assert result.security_scenarios[0].attack_type == "timing_attack"

    @pytest.mark.asyncio
    async def test_datasets_parsed(self):
        agent = ScenarioAgent(api_key="sk-fake", mode="full")
        flow  = make_flow()

        with patch.object(agent, "_call_claude", new=AsyncMock(return_value=MOCK_CLAUDE_RESPONSE)):
            result = await agent.analyze(flow)

        assert "email" in result.datasets
        assert len(result.datasets["email"].rows) > 0
        types = {r["type"] for r in result.datasets["email"].rows}
        assert "valid" in types
        assert "invalid" in types

    @pytest.mark.asyncio
    async def test_cross_impact_parsed(self):
        agent = ScenarioAgent(api_key="sk-fake", mode="full")
        flow  = make_flow()

        with patch.object(agent, "_call_claude", new=AsyncMock(return_value=MOCK_CLAUDE_RESPONSE)):
            result = await agent.analyze(flow)

        assert len(result.cross_impact) == 1
        assert result.cross_impact[0].req_a == "REQ-001"
        assert result.cross_impact[0].issue_type == "dependency"

    @pytest.mark.asyncio
    async def test_fallback_to_rules_on_claude_error(self):
        agent = ScenarioAgent(api_key="sk-fake", mode="full")
        flow  = make_flow()

        with patch.object(agent, "_call_claude", new=AsyncMock(side_effect=Exception("API down"))):
            result = await agent.analyze(flow)

        # Must still return a valid result (rule-based fallback)
        assert result.total_scenario_count > 0


# ---------------------------------------------------------------------------
# Cognitive Pipeline
# ---------------------------------------------------------------------------

MOCK_ANALYSIS_RESULT = {
    "interpreted_intent": "Controle de acesso por autenticação",
    "business_rules": [{"description": "Credenciais são obrigatórias", "entities": [], "conditions": [], "outcomes": []}],
    "ambiguities": ["Definição de sessão expirada"],
    "gaps": [],
    "suggested_scenarios": ["HappyPath: login válido", "NegativePath: senha errada"],
    "risk_level": "HIGH",
    "generated_flow_dsl": LOGIN_DSL,
}


class TestCognitivePipeline:

    @pytest.mark.asyncio
    async def test_pipeline_returns_result(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")

        with patch.object(
            pipeline._req_agent, "analyze",
            new=AsyncMock(return_value=_make_mock_analysis("REQ-001"))
        ):
            result = await pipeline.run("Login deve ser autenticado", "REQ-001")

        assert isinstance(result, CognitivePipelineResult)
        assert result.requirement_id == "REQ-001"

    @pytest.mark.asyncio
    async def test_pipeline_has_flow(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")

        with patch.object(
            pipeline._req_agent, "analyze",
            new=AsyncMock(return_value=_make_mock_analysis("REQ-001"))
        ):
            result = await pipeline.run("Login deve ser autenticado", "REQ-001")

        assert isinstance(result.flow, Flow)
        assert len(result.flow.scenarios) > 0

    @pytest.mark.asyncio
    async def test_pipeline_has_dsl(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")

        with patch.object(
            pipeline._req_agent, "analyze",
            new=AsyncMock(return_value=_make_mock_analysis("REQ-001"))
        ):
            result = await pipeline.run("Login deve ser autenticado", "REQ-001")

        assert result.dsl != ""
        assert "@flow" in result.dsl

    @pytest.mark.asyncio
    async def test_pipeline_coverage_score(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")

        with patch.object(
            pipeline._req_agent, "analyze",
            new=AsyncMock(return_value=_make_mock_analysis("REQ-001"))
        ):
            result = await pipeline.run("Login deve ser autenticado", "REQ-001")

        assert 0.0 <= result.coverage_score <= 100.0

    @pytest.mark.asyncio
    async def test_pipeline_summary_structure(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")

        with patch.object(
            pipeline._req_agent, "analyze",
            new=AsyncMock(return_value=_make_mock_analysis("REQ-001"))
        ):
            result = await pipeline.run("Login deve ser autenticado", "REQ-001")

        summary = result.summary()
        for key in ("requirement_id", "total_scenarios", "coverage_score",
                    "ai_scenarios", "security_scenarios"):
            assert key in summary

    @pytest.mark.asyncio
    async def test_pipeline_with_context(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")
        ctx = ProjectContext(framework="Angular", auth_type="JWT", base_url="http://app.com")

        with patch.object(
            pipeline._req_agent, "analyze",
            new=AsyncMock(return_value=_make_mock_analysis("REQ-002"))
        ):
            result = await pipeline.run(
                "Sessão deve expirar em 30 minutos",
                "REQ-002",
                context=ctx,
            )

        assert result.requirement_id == "REQ-002"

    @pytest.mark.asyncio
    async def test_pipeline_fallback_on_bad_dsl(self):
        pipeline = CognitivePipeline(api_key="sk-fake", mode="rules_only")

        bad_analysis = _make_mock_analysis("REQ-BAD")
        bad_analysis.generated_flow_dsl = "INVALID DSL CONTENT %%% NOT PARSEABLE"

        with patch.object(pipeline._req_agent, "analyze", new=AsyncMock(return_value=bad_analysis)):
            result = await pipeline.run("Requisito com DSL quebrado", "REQ-BAD")

        # Should not raise — falls back to minimal flow
        assert result.flow is not None
        assert result.total_scenarios > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_analysis(req_id: str):
    from ai_engine.requirement_agent.agent import RequirementAnalysis, BusinessRule
    return RequirementAnalysis(
        requirement_id=req_id,
        original_text="Requisito de teste para " + req_id,
        interpreted_intent="Verificar comportamento do sistema",
        business_rules=[
            BusinessRule(
                description="Sistema deve responder corretamente",
                entities=["usuário", "sistema"],
                conditions=["ação executada"],
                outcomes=["resultado esperado"],
            )
        ],
        ambiguities=["Definição de sucesso não especificada"],
        risk_level="MEDIUM",
        generated_flow_dsl=LOGIN_DSL,
    )
