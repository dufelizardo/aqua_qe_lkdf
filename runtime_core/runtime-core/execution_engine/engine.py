"""
runtime_core/execution_engine/engine.py
AQuA-QE LKDF — Execution Engine

Responsável por:
  - Orquestrar o pipeline de execução ponta a ponta
  - Gerenciar a State Machine de execução
  - Despachar actions para o adapter correto
  - Coletar resultados e acionar o Evidence Engine
"""
from __future__ import annotations

import time
from enum import Enum, auto
from typing import AsyncIterator, Callable

import structlog

from shared.models import (
    ExecutionReport,
    ExecutionStatus,
    Flow,
    RuntimeContext,
    Scenario,
    ScenarioResult,
    SemanticStep,
    StepResult,
)
from runtime_core.semantic_engine.intent_resolver import IntentResolver
from runtime_core.context_engine.engine import ContextEngine
from runtime_core.scenario_engine.engine import ScenarioEngine
from runtime_core.adapters.base import BaseAdapter

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

class EngineState(Enum):
    IDLE        = auto()
    INITIALIZING= auto()
    PARSING     = auto()
    ENRICHING   = auto()
    DISPATCHING = auto()
    ASSERTING   = auto()
    COLLECTING  = auto()
    TRACING     = auto()
    DONE        = auto()
    ERROR       = auto()


class ExecutionStateMachine:
    """
    State Machine da execução conforme o Runtime Execution Flow do documento:
    Input → DSL Parser → Intent Resolver → Context Enrichment →
    Flow Resolver → Adapter Resolver → Action Dispatcher →
    Assertion Engine → Evidence Collector → Traceability Engine → Output
    """

    _TRANSITIONS: dict[EngineState, list[EngineState]] = {
        EngineState.IDLE:          [EngineState.INITIALIZING],
        EngineState.INITIALIZING:  [EngineState.PARSING, EngineState.ERROR],
        EngineState.PARSING:       [EngineState.ENRICHING, EngineState.ERROR],
        EngineState.ENRICHING:     [EngineState.DISPATCHING, EngineState.ERROR],
        EngineState.DISPATCHING:   [EngineState.ASSERTING, EngineState.COLLECTING, EngineState.ERROR],
        EngineState.ASSERTING:     [EngineState.COLLECTING, EngineState.ERROR],
        EngineState.COLLECTING:    [EngineState.TRACING, EngineState.ERROR],
        EngineState.TRACING:       [EngineState.DONE, EngineState.ERROR],
        EngineState.DONE:          [EngineState.IDLE],
        EngineState.ERROR:         [EngineState.IDLE],
    }

    def __init__(self) -> None:
        self.state = EngineState.IDLE
        self._listeners: list[Callable[[EngineState, EngineState], None]] = []

    def transition(self, target: EngineState) -> None:
        allowed = self._TRANSITIONS.get(self.state, [])
        if target not in allowed:
            raise InvalidTransitionError(
                f"Transição inválida: {self.state.name} → {target.name}"
            )
        prev = self.state
        self.state = target
        for listener in self._listeners:
            listener(prev, target)
        log.debug("state_transition", prev=prev.name, current=target.name)

    def on_transition(self, fn: Callable[[EngineState, EngineState], None]) -> None:
        self._listeners.append(fn)


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------

class ExecutionEngine:
    """
    Orquestrador principal do LKDF Runtime.
    Executa um Flow completo passando por todos os estágios do pipeline.
    """

    def __init__(self, adapter: BaseAdapter) -> None:
        self.adapter         = adapter
        self.resolver        = IntentResolver()
        self._sm             = ExecutionStateMachine()
        self._scenario_engine = ScenarioEngine()
        self._ctx_engine: ContextEngine | None = None

    # ------------------------------------------------------------------
    async def execute_flow(
        self,
        flow: Flow,
        context: RuntimeContext,
    ) -> ExecutionReport:
        """Executa um Flow completo e retorna o ExecutionReport."""

        report = ExecutionReport(
            flow_id=flow.id,
            flow_name=flow.name,
            adapter=flow.adapter,
            total_scenarios=len(flow.scenarios),
            requirement_ref=flow.requirement_ref,
        )

        self._sm.transition(EngineState.INITIALIZING)
        log.info("execution_start", flow=flow.name, scenarios=len(flow.scenarios))

        # Boot Context Engine for this execution
        self._ctx_engine = ContextEngine(project=context.project)
        self._ctx_engine.begin_flow(flow.name)

        start_total = time.perf_counter()

        try:
            # 1. Adapter setup
            await self.adapter.setup(context)
            self._sm.transition(EngineState.PARSING)

            # 2. Enrich all steps with resolved intents
            self._sm.transition(EngineState.ENRICHING)
            enriched_flow = self._enrich_flow(flow)

            # 3. Compose scenarios via Scenario Engine
            self._sm.transition(EngineState.DISPATCHING)
            composed = self._scenario_engine.compose(enriched_flow)
            report.status = ExecutionStatus.RUNNING

            for c_scenario in composed:
                if self._ctx_engine:
                    self._ctx_engine.begin_scenario(c_scenario.scenario.name)
                s_result = await self._execute_scenario(c_scenario.scenario, context)
                if self._ctx_engine:
                    self._ctx_engine.end_scenario(c_scenario.scenario.name, s_result.status)
                report.scenario_results.append(s_result)
                if s_result.status == ExecutionStatus.PASSED:
                    report.passed += 1
                elif s_result.status == ExecutionStatus.FAILED:
                    report.failed += 1
                else:
                    report.skipped += 1

            # 4. Collect evidence
            self._sm.transition(EngineState.COLLECTING)
            evidence = await self.adapter.collect_evidence(context)
            report.evidence_paths = evidence

            # 5. Finalize
            self._sm.transition(EngineState.TRACING)
            report.status = (
                ExecutionStatus.PASSED if report.failed == 0
                else ExecutionStatus.FAILED
            )
            self._sm.transition(EngineState.DONE)

        except Exception as exc:
            log.error("execution_error", error=str(exc))
            self._sm.transition(EngineState.ERROR)
            report.status = ExecutionStatus.ERROR
            self._sm.transition(EngineState.IDLE)
            raise

        finally:
            elapsed_ms = int((time.perf_counter() - start_total) * 1000)
            report.duration_ms = elapsed_ms
            if self._ctx_engine:
                self._ctx_engine.end_flow(flow.name, str(report.status))
            await self.adapter.teardown(context)
            if self._sm.state == EngineState.DONE:
                self._sm.transition(EngineState.IDLE)

        log.info(
            "execution_done",
            flow=flow.name,
            status=report.status,
            passed=report.passed,
            failed=report.failed,
            duration_ms=report.duration_ms,
        )
        return report

    # ------------------------------------------------------------------
    async def execute_flow_stream(
        self,
        flow: Flow,
        context: RuntimeContext,
    ) -> AsyncIterator[StepResult | ScenarioResult | ExecutionReport]:
        """
        Streaming execution — yields resultados em tempo real
        para o frontend ou CLI consumir progressivamente.
        """
        enriched_flow = self._enrich_flow(flow)
        await self.adapter.setup(context)

        report = ExecutionReport(
            flow_id=flow.id,
            flow_name=flow.name,
            adapter=flow.adapter,
            total_scenarios=len(flow.scenarios),
            requirement_ref=flow.requirement_ref,
            status=ExecutionStatus.RUNNING,
        )

        for scenario in enriched_flow.scenarios:
            s_result = ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                status=ExecutionStatus.RUNNING,
            )

            for step in scenario.steps:
                step_result = await self._execute_step(step, context)
                s_result.step_results.append(step_result)
                yield step_result

                if step_result.status == ExecutionStatus.FAILED:
                    s_result.status = ExecutionStatus.FAILED
                    break

            if s_result.status == ExecutionStatus.RUNNING:
                s_result.status = ExecutionStatus.PASSED

            report.scenario_results.append(s_result)
            if s_result.status == ExecutionStatus.PASSED:
                report.passed += 1
            else:
                report.failed += 1
            yield s_result

        report.status = ExecutionStatus.PASSED if report.failed == 0 else ExecutionStatus.FAILED
        report.evidence_paths = await self.adapter.collect_evidence(context)
        await self.adapter.teardown(context)
        yield report

    # ------------------------------------------------------------------
    async def _execute_scenario(
        self, scenario: Scenario, context: RuntimeContext
    ) -> ScenarioResult:
        log.info("scenario_start", name=scenario.name)
        result = ScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            status=ExecutionStatus.RUNNING,
        )
        start = time.perf_counter()

        # Adapter lifecycle hook (optional — só se o adapter suportar)
        if hasattr(self.adapter, "begin_scenario"):
            await self.adapter.begin_scenario(scenario.name)

        for step in scenario.steps:
            step_result = await self._execute_step(step, context)
            result.step_results.append(step_result)

            if step_result.status == ExecutionStatus.FAILED:
                result.status = ExecutionStatus.FAILED
                log.warning("scenario_failed_at_step", step=step.text[:60])
                break

        if result.status == ExecutionStatus.RUNNING:
            result.status = ExecutionStatus.PASSED

        result.duration_ms = int((time.perf_counter() - start) * 1000)

        # Adapter lifecycle hook (optional)
        if hasattr(self.adapter, "end_scenario"):
            passed = result.status == ExecutionStatus.PASSED
            await self.adapter.end_scenario(scenario.name, passed)

        log.info("scenario_done", name=scenario.name, status=result.status)
        return result

    async def _execute_step(
        self, step: SemanticStep, context: RuntimeContext
    ) -> StepResult:
        log.debug("step_start", action=step.action, intent=step.intent)
        start = time.perf_counter()

        try:
            await self.adapter.execute_action(
                action=step.action,
                parameters=step.parameters,
                context=context,
            )
            status = ExecutionStatus.PASSED
            msg    = f"OK — {step.action}"
        except AssertionError as exc:
            status = ExecutionStatus.FAILED
            msg    = f"Assertion falhou: {exc}"
            log.warning("step_assertion_failed", step=step.text[:60], error=str(exc))
        except Exception as exc:
            status = ExecutionStatus.FAILED
            msg    = f"Erro inesperado: {exc}"
            log.error("step_error", step=step.text[:60], error=str(exc))

        duration_ms = int((time.perf_counter() - start) * 1000)
        return StepResult(
            step_id=step.id,
            status=status,
            duration_ms=duration_ms,
            message=msg,
        )

    def _enrich_flow(self, flow: Flow) -> Flow:
        """Cria cópia do Flow com todos os steps enriquecidos pelo Intent Resolver."""
        enriched_scenarios = []
        for scenario in flow.scenarios:
            enriched_steps = [self.resolver.enrich_step(s) for s in scenario.steps]
            enriched_scenarios.append(scenario.model_copy(update={"steps": enriched_steps}))
        return flow.model_copy(update={"scenarios": enriched_scenarios})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidTransitionError(Exception):
    """Raised on illegal state machine transition."""
