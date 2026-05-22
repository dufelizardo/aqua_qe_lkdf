"""
runtime_core/quality_policy/engine.py
AQuA-QE LKDF v1.4 — Policy Engine

Orquestra a avaliação de quality policies:
  - Executa todos os gates de uma policy contra um contexto
  - Persiste relatórios no GraphRepository
  - Integra com o FanOut pipeline como PipelineStage
  - Suporta políticas compostas (story + release)
  - Gera relatórios estruturados para o RTM
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from runtime_core.persistence.graph.models import Node
from runtime_core.persistence.graph.repository import GraphRepository
from runtime_core.quality_policy.evaluators import EvaluationContext, get_evaluator
from runtime_core.quality_policy.models import (
    GateResult,
    PolicyAction,
    PolicyReport,
    QualityPolicy,
    default_release_policy,
    default_story_policy,
)
from runtime_core.pipeline.fanout import PipelineContext, PipelineStage

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    Motor central do Quality Policy Engine.
    Avalia policies, persiste no grafo e expõe interface para o pipeline.
    """

    def __init__(self, repository: GraphRepository | None = None) -> None:
        self._repo     = repository
        self._policies: dict[str, QualityPolicy] = {}
        self._reports:  list[PolicyReport]        = []

        # Register defaults
        self.register(default_story_policy())
        self.register(default_release_policy())

    # ------------------------------------------------------------------
    # Policy management
    # ------------------------------------------------------------------

    def register(self, policy: QualityPolicy) -> None:
        self._policies[policy.name] = policy
        log.debug("policy_registered", name=policy.name, gates=len(policy.gates))

    def get_policy(self, name: str) -> QualityPolicy | None:
        return self._policies.get(name)

    def list_policies(self) -> list[str]:
        return list(self._policies.keys())

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        policy:     QualityPolicy,
        ctx:        EvaluationContext,
        subject_id: str,
        subject_type: str = "story",
    ) -> PolicyReport:
        """
        Avalia todos os gates de uma policy contra um contexto.
        Persiste o relatório no GraphRepository se disponível.
        """
        log.info(
            "policy_evaluate_start",
            policy=policy.name,
            subject=subject_id,
            gates=len(policy.gates),
        )

        from runtime_core.quality_policy.models import GateEvaluation
        evaluations: list[GateEvaluation] = []
        blocking_failures = 0
        warnings = 0

        for gate in policy.gates:
            evaluator = get_evaluator(gate.gate_type)
            if not evaluator:
                log.warning("no_evaluator_for_gate", gate_type=gate.gate_type)
                continue

            evaluation = evaluator.evaluate(gate, ctx)
            evaluations.append(evaluation)

            if evaluation.result == GateResult.FAILED:
                if gate.action == PolicyAction.BLOCK:
                    blocking_failures += 1
                    log.warning(
                        "gate_failed_blocking",
                        gate=gate.name,
                        actual=evaluation.actual_value,
                        threshold=gate.threshold,
                    )
                else:
                    warnings += 1
                    log.info(
                        "gate_failed_warning",
                        gate=gate.name,
                        actual=evaluation.actual_value,
                    )
            elif evaluation.result == GateResult.WARNING:
                warnings += 1

            # fail_fast: stop at first blocking failure
            if policy.fail_fast and blocking_failures > 0:
                log.info("policy_fail_fast_triggered", gate=gate.name)
                break

        overall = (
            GateResult.PASSED  if blocking_failures == 0
            else GateResult.FAILED
        )

        report = PolicyReport(
            policy_name=policy.name,
            subject_id=subject_id,
            subject_type=subject_type,
            evaluations=evaluations,
            overall_result=overall,
            blocking_failures=blocking_failures,
            warnings=warnings,
        )

        # Persist to graph
        if self._repo:
            await self._persist_report(report)

        self._reports.append(report)

        log.info(
            "policy_evaluate_done",
            policy=policy.name,
            subject=subject_id,
            result=overall.value,
            blocking=blocking_failures,
            warnings=warnings,
        )
        return report

    async def evaluate_story(
        self,
        subject_id: str,
        ctx:        EvaluationContext,
    ) -> PolicyReport:
        """Avalia a política padrão de story."""
        policy = self.get_policy("Default Story Policy")
        if not policy:
            policy = default_story_policy()
        return await self.evaluate(policy, ctx, subject_id, "story")

    async def evaluate_release(
        self,
        release_id: str,
        ctx:        EvaluationContext,
    ) -> PolicyReport:
        """Avalia a política padrão de release."""
        policy = self.get_policy("Default Release Policy")
        if not policy:
            policy = default_release_policy()
        return await self.evaluate(policy, ctx, release_id, "release")

    async def evaluate_by_name(
        self,
        policy_name: str,
        subject_id:  str,
        ctx:         EvaluationContext,
    ) -> PolicyReport | None:
        policy = self.get_policy(policy_name)
        if not policy:
            log.warning("policy_not_found", name=policy_name)
            return None
        return await self.evaluate(policy, ctx, subject_id)

    # ------------------------------------------------------------------
    # Composite evaluation (multiple policies)
    # ------------------------------------------------------------------

    async def evaluate_composite(
        self,
        policies:   list[QualityPolicy],
        ctx:        EvaluationContext,
        subject_id: str,
    ) -> list[PolicyReport]:
        """Avalia múltiplas policies e retorna todos os relatórios."""
        reports: list[PolicyReport] = []
        for policy in policies:
            report = await self.evaluate(policy, ctx, subject_id)
            reports.append(report)
        return reports

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    @staticmethod
    def build_story_context(
        has_acceptance_criteria:  bool  = False,
        acceptance_criteria_count: int  = 0,
        criticality_classified:   bool  = False,
        open_p0_defects:          int   = 0,
        critical_ambiguities:     int   = 0,
        ambiguity_score:          float = 0.0,
        has_bidirectional_traceability: bool  = False,
        traceability_coverage:    float = 0.0,
        unreviewed_breaking_changes: int = 0,
    ) -> EvaluationContext:
        ctx = EvaluationContext()
        ctx.has_acceptance_criteria        = has_acceptance_criteria
        ctx.acceptance_criteria_count      = acceptance_criteria_count
        ctx.criticality_classified         = criticality_classified
        ctx.open_p0_defects                = open_p0_defects
        ctx.critical_ambiguities           = critical_ambiguities
        ctx.ambiguity_score                = ambiguity_score
        ctx.has_bidirectional_traceability = has_bidirectional_traceability
        ctx.traceability_coverage          = traceability_coverage
        ctx.unreviewed_breaking_changes    = unreviewed_breaking_changes
        return ctx

    @staticmethod
    def build_release_context(
        requirements_total:           int   = 0,
        requirements_with_scenarios:  int   = 0,
        requirements_in_rtm:          int   = 0,
        execution_total:              int   = 0,
        execution_passed:             int   = 0,
        open_p0_defects:              int   = 0,
        wcag_aa_violations:           int   = 0,
        wcag_aa_compliance_pct:       float = 1.0,
        traceability_coverage:        float = 0.0,
        has_bidirectional_traceability: bool = False,
    ) -> EvaluationContext:
        ctx = EvaluationContext()
        ctx.requirements_total            = requirements_total
        ctx.requirements_with_scenarios   = requirements_with_scenarios
        ctx.requirements_in_rtm           = requirements_in_rtm
        ctx.execution_total               = execution_total
        ctx.execution_passed              = execution_passed
        ctx.open_p0_defects               = open_p0_defects
        ctx.wcag_aa_violations            = wcag_aa_violations
        ctx.wcag_aa_compliance_pct        = wcag_aa_compliance_pct
        ctx.traceability_coverage         = traceability_coverage
        ctx.has_bidirectional_traceability = has_bidirectional_traceability
        return ctx

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def all_reports(self) -> list[PolicyReport]:
        return list(self._reports)

    def failed_subjects(self) -> list[str]:
        return [r.subject_id for r in self._reports if not r.passed]

    def compliance_summary(self) -> dict[str, Any]:
        total   = len(self._reports)
        passed  = sum(1 for r in self._reports if r.passed)
        return {
            "total_evaluations": total,
            "passed":            passed,
            "failed":            total - passed,
            "compliance_rate":   round(passed / total, 3) if total else 1.0,
            "blocking_failures": sum(r.blocking_failures for r in self._reports),
            "warnings":          sum(r.warnings for r in self._reports),
        }

    # ------------------------------------------------------------------
    # Graph persistence
    # ------------------------------------------------------------------

    async def _persist_report(self, report: PolicyReport) -> None:
        try:
            node = Node(
                label="PolicyReport",
                external_id=str(report.id),
                properties={
                    "policy_name":       report.policy_name,
                    "subject_id":        report.subject_id,
                    "subject_type":      report.subject_type,
                    "overall_result":    report.overall_result.value,
                    "blocking_failures": report.blocking_failures,
                    "warnings":          report.warnings,
                    "passed":            report.passed,
                    "gate_summary":      report.gate_summary,
                    "evaluated_at":      datetime.utcnow().isoformat(),
                },
            )
            await self._repo.add_node(node)
        except Exception as exc:
            log.warning("policy_report_persist_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Pipeline stage integration
# ---------------------------------------------------------------------------

class PolicyGateStage(PipelineStage):
    """
    PipelineStage que executa um quality gate check como etapa do Fan-Out Pipeline.
    Permite inserir gates em qualquer ponto do pipeline de CI/CD.

    Uso:
        pipeline = FanOutPipeline("ci-pipeline", stages=[
            ParseStage("parse", "DSL Parser"),
            SemanticStage("semantic", "Semantic", depends_on=["parse"]),
            PolicyGateStage("gate-story", "Quality Gate — Story",
                           policy_name="Default Story Policy",
                           depends_on=["semantic"]),
            ExecutionStage("execute", "Execute", depends_on=["gate-story"]),
        ])
    """

    def __init__(
        self,
        stage_id:    str,
        name:        str,
        policy_name: str,
        engine:      PolicyEngine,
        depends_on:  list[str] | None = None,
        optional:    bool             = False,
    ) -> None:
        super().__init__(stage_id, name, depends_on, optional)
        self.policy_name = policy_name
        self.engine      = engine

    async def execute(self, context: PipelineContext) -> PolicyReport:
        ctx        = context.inputs.get("evaluation_context", EvaluationContext())
        subject_id = context.inputs.get("subject_id", "unknown")

        report = await self.engine.evaluate_by_name(
            self.policy_name, subject_id, ctx
        )

        if report and not report.passed:
            blocking = [e.gate_name for e in report.failed_gates()
                        if e.blocking_failure]
            if blocking:
                raise RuntimeError(
                    f"Quality gate(s) bloqueante(s) falharam: {', '.join(blocking)}"
                )

        return report
