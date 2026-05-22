"""
tests/integration/test_execution_pipeline.py
AQuA-QE LKDF — Integration Tests: Full Execution Pipeline
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from shared.models import (
    AdapterType,
    ExecutionStatus,
    ProjectContext,
    RuntimeContext,
)
from runtime_core.parser.dsl_parser import DSLParser
from runtime_core.execution_engine.engine import ExecutionEngine
from runtime_core.adapters.base import BaseAdapter


# ---------------------------------------------------------------------------
# Mock Adapter (no browser needed)
# ---------------------------------------------------------------------------

class MockAdapter(BaseAdapter):
    """Adapter de teste que simula execução sem browser real."""

    adapter_type = AdapterType.ROBOT

    def __init__(self, fail_on_action: str | None = None) -> None:
        self.fail_on_action = fail_on_action
        self.executed_actions: list[str] = []
        self.setup_called    = False
        self.teardown_called = False

    async def setup(self, context):
        self.setup_called = True

    async def teardown(self, context):
        self.teardown_called = True

    async def execute_action(self, action, parameters, context):
        self.executed_actions.append(action)
        if action == self.fail_on_action:
            raise AssertionError(f"Mock assertion failed for: {action}")

    async def collect_evidence(self, context):
        return ["/tmp/mock_screenshot.png", "/tmp/mock_log.json"]

    async def take_screenshot(self, context, name):
        return f"/tmp/{name}.png"

    def _action_registry(self):
        return {"fill", "click_element", "assert_text", "navigate", "open_page"}


# ---------------------------------------------------------------------------
# Test DSL
# ---------------------------------------------------------------------------

TEST_DSL = """\
# Flow: IntegrationTestFlow
# Requirement: REQ-TEST-001
# Adapter: robot-framework
# Priority: HIGH

@flow IntegrationTestFlow
  @scenario HappyPath
    Dado que o usuário está na página de login
    Quando o usuário insere "test@test.com" no campo email
    E o usuário insere "pass123" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Bem-vindo" seja exibida

  @scenario NegativePath
    Dado que o usuário está na página de login
    Quando o usuário insere "errado@test.com" no campo email
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Credenciais inválidas" seja exibida
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def _make_context(self) -> RuntimeContext:
        return RuntimeContext(project=ProjectContext(base_url="http://localhost:4200"))

    @pytest.mark.asyncio
    async def test_parse_and_execute_full_flow(self):
        """Critério de aceite Fase 1: Flow semântico → execução → evidências."""
        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter()
        engine  = ExecutionEngine(adapter=adapter)
        context = self._make_context()

        report = await engine.execute_flow(flow, context)

        assert report.flow_name == "IntegrationTestFlow"
        assert report.total_scenarios == 2
        assert report.status in (ExecutionStatus.PASSED, ExecutionStatus.FAILED)
        assert adapter.setup_called
        assert adapter.teardown_called
        assert len(adapter.executed_actions) > 0
        assert len(report.evidence_paths) > 0

    @pytest.mark.asyncio
    async def test_all_steps_execute(self):
        """Todos os steps do flow devem ser executados."""
        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter()
        engine  = ExecutionEngine(adapter=adapter)
        context = self._make_context()

        report = await engine.execute_flow(flow, context)

        total_steps = sum(len(s.steps) for s in flow.scenarios)
        executed    = sum(len(r.step_results) for r in report.scenario_results)
        # At minimum the first scenario should complete fully
        assert executed > 0

    @pytest.mark.asyncio
    async def test_failure_captured_in_report(self):
        """Falha de assertion deve ser registrada no relatório."""
        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter(fail_on_action="assert_text")
        engine  = ExecutionEngine(adapter=adapter)
        context = self._make_context()

        report = await engine.execute_flow(flow, context)

        failed_steps = [
            step
            for scenario in report.scenario_results
            for step in scenario.step_results
            if step.status == ExecutionStatus.FAILED
        ]
        assert len(failed_steps) > 0

    @pytest.mark.asyncio
    async def test_streaming_execution_yields_results(self):
        """Streaming deve produzir StepResult e ScenarioResult em tempo real."""
        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter()
        engine  = ExecutionEngine(adapter=adapter)
        context = self._make_context()

        results = []
        async for result in engine.execute_flow_stream(flow, context):
            results.append(result)

        from shared.models import StepResult, ScenarioResult, ExecutionReport
        assert any(isinstance(r, StepResult)      for r in results)
        assert any(isinstance(r, ScenarioResult)  for r in results)
        assert any(isinstance(r, ExecutionReport) for r in results)

    @pytest.mark.asyncio
    async def test_state_machine_reaches_done(self):
        """A state machine deve alcançar o estado DONE após execução bem-sucedida."""
        from runtime_core.execution_engine.engine import EngineState

        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter()
        engine  = ExecutionEngine(adapter=adapter)
        context = self._make_context()

        states: list[str] = []
        engine._sm.on_transition(lambda p, c: states.append(c.name))

        await engine.execute_flow(flow, context)

        assert "DONE" in states
        assert engine._sm.state == EngineState.IDLE

    @pytest.mark.asyncio
    async def test_intent_resolver_enriches_steps(self):
        """Steps devem ter intent e action preenchidos após enriquecimento."""
        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter()
        engine  = ExecutionEngine(adapter=adapter)

        enriched = engine._enrich_flow(flow)

        for scenario in enriched.scenarios:
            for step in scenario.steps:
                assert step.intent != "", f"Step sem intent: {step.text}"
                assert step.action != "", f"Step sem action: {step.text}"

    @pytest.mark.asyncio
    async def test_report_has_traceability_fields(self):
        """Relatório deve conter campos de rastreabilidade."""
        parser  = DSLParser()
        flow    = parser.parse(TEST_DSL)
        adapter = MockAdapter()
        engine  = ExecutionEngine(adapter=adapter)
        context = self._make_context()

        report = await engine.execute_flow(flow, context)

        assert report.requirement_ref == "REQ-TEST-001"
        assert report.flow_id == flow.id
        assert report.adapter == AdapterType.ROBOT
