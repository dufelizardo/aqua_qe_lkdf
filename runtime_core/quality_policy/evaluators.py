"""
runtime_core/quality_policy/evaluators.py
AQuA-QE LKDF v1.4 — Quality Gate Evaluators

Lógica concreta de avaliação para cada GateType.
Cada avaliador recebe um contexto rico e retorna GateEvaluation.

Princípio: cada avaliador é puro — sem side effects, apenas calcula.
"""
from __future__ import annotations

from typing import Any, Protocol

from runtime_core.quality_policy.models import (
    GateDefinition,
    GateEvaluation,
    GateResult,
    GateType,
    PolicyAction,
)


# ---------------------------------------------------------------------------
# Evaluation context
# ---------------------------------------------------------------------------

class EvaluationContext:
    """
    Contexto rico passado para todos os avaliadores.
    Agrega dados de múltiplas fontes sem acoplar os avaliadores a repositórios.
    """

    def __init__(self) -> None:
        # Story data
        self.story_external_id: str = ""
        self.has_acceptance_criteria: bool = False
        self.acceptance_criteria_count: int = 0
        self.criticality_classified: bool = False
        self.open_p0_defects: int = 0
        self.open_defects_total: int = 0

        # Ambiguity data
        self.critical_ambiguities: int = 0
        self.ambiguity_score: float = 0.0

        # Coverage metrics
        self.requirements_total: int = 0
        self.requirements_with_scenarios: int = 0
        self.requirements_in_rtm: int = 0
        self.execution_total: int = 0
        self.execution_passed: int = 0

        # Traceability
        self.has_bidirectional_traceability: bool = False
        self.traceability_coverage: float = 0.0

        # Accessibility
        self.wcag_a_violations: int = 0
        self.wcag_aa_violations: int = 0
        self.wcag_aaa_violations: int = 0
        self.wcag_aa_compliance_pct: float = 1.0

        # Breaking changes
        self.unreviewed_breaking_changes: int = 0

        # Extra
        self.extra: dict[str, Any] = {}

    @classmethod
    def from_story_gate_check(cls, gate_result: dict[str, Any]) -> "EvaluationContext":
        """Constrói contexto a partir do resultado de StoryService.quality_gate_check()."""
        ctx = cls()
        ctx.criticality_classified = gate_result.get("criticality") in ("P0", "P1", "P2")
        ctx.open_p0_defects        = sum(
            1 for i in gate_result.get("issues", []) if "P0" in i
        )
        return ctx


# ---------------------------------------------------------------------------
# Evaluator protocol
# ---------------------------------------------------------------------------

class GateEvaluator(Protocol):
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        ...


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------

def _make_eval(
    gate: GateDefinition,
    result: GateResult,
    actual: Any,
    message: str,
    details: list[str] | None = None,
) -> GateEvaluation:
    return GateEvaluation(
        gate_id=gate.id,
        gate_type=gate.gate_type,
        gate_name=gate.name,
        result=result,
        actual_value=actual,
        threshold=gate.threshold,
        action=gate.action,
        message=message,
        details=details or [],
    )


class AcceptanceCriteriaEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        passed = ctx.has_acceptance_criteria and ctx.acceptance_criteria_count >= 1
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual=ctx.acceptance_criteria_count,
            message=(
                f"{ctx.acceptance_criteria_count} critério(s) de aceite definido(s)."
                if passed
                else "Nenhum critério de aceite definido. Story não está pronta para teste."
            ),
            details=[] if passed else [
                "Adicione ao menos 1 critério de aceite antes de prosseguir.",
                "Critérios devem ser verificáveis e mensuráveis.",
            ],
        )


class CriticalityClassifiedEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        passed = ctx.criticality_classified
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual=passed,
            message=(
                "Criticidade P0/P1/P2 classificada."
                if passed
                else "Criticidade não classificada. Execute classify_criticality() antes de prosseguir."
            ),
        )


class NoCriticalAmbiguityEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        passed = ctx.critical_ambiguities == 0
        result = GateResult.PASSED if passed else GateResult.FAILED
        return _make_eval(
            gate,
            result,
            actual=ctx.critical_ambiguities,
            message=(
                "Nenhuma ambiguidade CRITICAL detectada."
                if passed
                else f"{ctx.critical_ambiguities} ambiguidade(s) CRITICAL não resolvida(s)."
            ),
            details=[] if passed else [
                "Resolva todas as ambiguidades CRITICAL antes de gerar cenários.",
                "Use AmbiguityResolver.resolve() para cada ambiguidade CRITICAL.",
            ],
        )


class AmbiguityScoreEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        score  = ctx.ambiguity_score
        passed = score <= gate.threshold
        result = (
            GateResult.PASSED  if passed
            else GateResult.WARNING if gate.action == PolicyAction.WARN
            else GateResult.FAILED
        )
        return _make_eval(
            gate,
            result,
            actual=round(score, 2),
            message=f"Score de ambiguidade: {score:.2f} (máximo: {gate.threshold:.2f})",
            details=[] if passed else [
                f"Score {score:.2f} excede o limite {gate.threshold:.2f}.",
                "Resolva ambiguidades de maior severidade primeiro.",
            ],
        )


class NoOpenP0DefectsEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        passed = ctx.open_p0_defects == 0
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual=ctx.open_p0_defects,
            message=(
                "Nenhum defect P0 aberto."
                if passed
                else f"{ctx.open_p0_defects} defect(s) P0 aberto(s). Release bloqueada."
            ),
            details=[] if passed else [
                "Todos os defects P0 devem ser resolvidos antes da release.",
                "SLA P0: 4 horas.",
            ],
        )


class ScenarioCoverageEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        if ctx.requirements_total == 0:
            return _make_eval(
                gate, GateResult.SKIPPED, actual=None,
                message="Nenhum requisito encontrado — gate ignorado.",
            )
        coverage = ctx.requirements_with_scenarios / ctx.requirements_total
        passed   = coverage >= gate.threshold
        result   = (
            GateResult.PASSED  if passed
            else GateResult.WARNING if gate.action == PolicyAction.WARN
            else GateResult.FAILED
        )
        return _make_eval(
            gate,
            result,
            actual=round(coverage, 3),
            message=(
                f"Cobertura de cenários: {coverage*100:.1f}% "
                f"({ctx.requirements_with_scenarios}/{ctx.requirements_total} requisitos)."
            ),
            details=[] if passed else [
                f"Cobertura mínima: {gate.threshold*100:.0f}%.",
                f"Faltam cenários para {ctx.requirements_total - ctx.requirements_with_scenarios} requisito(s).",
            ],
        )


class ExecutionPassRateEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        if ctx.execution_total == 0:
            return _make_eval(
                gate, GateResult.SKIPPED, actual=None,
                message="Nenhuma execução registrada — gate ignorado.",
            )
        rate   = ctx.execution_passed / ctx.execution_total
        passed = rate >= gate.threshold
        result = GateResult.PASSED if passed else GateResult.FAILED
        return _make_eval(
            gate,
            result,
            actual=round(rate, 3),
            message=(
                f"Taxa de aprovação: {rate*100:.1f}% "
                f"({ctx.execution_passed}/{ctx.execution_total} execuções)."
            ),
            details=[] if passed else [
                f"Taxa mínima exigida: {gate.threshold*100:.0f}%.",
                f"{ctx.execution_total - ctx.execution_passed} execução(ões) falhando.",
            ],
        )


class RTMCoverageEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        if ctx.requirements_total == 0:
            return _make_eval(
                gate, GateResult.SKIPPED, actual=None,
                message="Nenhum requisito — gate ignorado.",
            )
        coverage = ctx.requirements_in_rtm / ctx.requirements_total
        passed   = coverage >= gate.threshold
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual=round(coverage, 3),
            message=f"Cobertura RTM: {coverage*100:.1f}%.",
            details=[] if passed else [
                f"RTM mínimo: {gate.threshold*100:.0f}%.",
                f"{ctx.requirements_total - ctx.requirements_in_rtm} requisito(s) sem entrada no RTM.",
            ],
        )


class WcagAAComplianceEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        violations = ctx.wcag_aa_violations
        compliance = ctx.wcag_aa_compliance_pct
        passed     = violations == 0 and compliance >= gate.threshold
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual={"violations": violations, "compliance_pct": round(compliance, 3)},
            message=(
                "WCAG 2.1 AA: conformidade total."
                if passed
                else f"WCAG 2.1 AA: {violations} violação(ões) detectada(s). "
                     f"Conformidade: {compliance*100:.1f}%."
            ),
            details=[] if passed else [
                "WCAG AA é gate mandatório — release bloqueada.",
                "Corrija todos os critérios de sucesso AA antes de prosseguir.",
                "Execute Accessibility Layer (axe-core / Pa11y) para lista completa.",
            ],
        )


class WcagAComplianceEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        violations = ctx.wcag_a_violations
        passed     = violations == 0
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual=violations,
            message=(
                "WCAG 2.1 A: conformidade total."
                if passed
                else f"WCAG 2.1 A: {violations} violação(ões) no nível A."
            ),
        )


class BiDirectionalTraceabilityEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        coverage = ctx.traceability_coverage
        passed   = ctx.has_bidirectional_traceability and coverage >= gate.threshold
        result   = (
            GateResult.PASSED  if passed
            else GateResult.WARNING if gate.action == PolicyAction.WARN
            else GateResult.FAILED
        )
        return _make_eval(
            gate,
            result,
            actual=round(coverage, 3),
            message=(
                f"Rastreabilidade bidirecional: {coverage*100:.1f}%."
                if passed
                else f"Rastreabilidade incompleta: {coverage*100:.1f}% (mínimo: {gate.threshold*100:.0f}%)."
            ),
            details=[] if passed else [
                "Toda evidência deve rastrear de volta ao requisito de origem.",
                "Verifique links Requirement → Flow → Scenario → Execution → Evidence.",
            ],
        )


class NoBreakingChangesUnreviewedEvaluator:
    def evaluate(self, gate: GateDefinition, ctx: EvaluationContext) -> GateEvaluation:
        count  = ctx.unreviewed_breaking_changes
        passed = count == 0
        return _make_eval(
            gate,
            GateResult.PASSED if passed else GateResult.FAILED,
            actual=count,
            message=(
                "Nenhuma breaking change sem revisão."
                if passed
                else f"{count} breaking change(s) sem revisão detectada(s)."
            ),
            details=[] if passed else [
                "Revise e aprove cada breaking change antes de prosseguir.",
                "Breaking changes podem invalidar cenários existentes.",
            ],
        )


# ---------------------------------------------------------------------------
# Evaluator registry
# ---------------------------------------------------------------------------

_EVALUATOR_MAP: dict[GateType, GateEvaluator] = {
    GateType.ACCEPTANCE_CRITERIA:              AcceptanceCriteriaEvaluator(),
    GateType.CRITICALITY_CLASSIFIED:           CriticalityClassifiedEvaluator(),
    GateType.NO_CRITICAL_AMBIGUITY:            NoCriticalAmbiguityEvaluator(),
    GateType.AMBIGUITY_SCORE:                  AmbiguityScoreEvaluator(),
    GateType.NO_OPEN_P0_DEFECTS:               NoOpenP0DefectsEvaluator(),
    GateType.SCENARIO_COVERAGE:                ScenarioCoverageEvaluator(),
    GateType.EXECUTION_PASS_RATE:              ExecutionPassRateEvaluator(),
    GateType.RTM_COVERAGE:                     RTMCoverageEvaluator(),
    GateType.WCAG_AA_COMPLIANCE:               WcagAAComplianceEvaluator(),
    GateType.WCAG_A_COMPLIANCE:                WcagAComplianceEvaluator(),
    GateType.BIDIRECTIONAL_TRACEABILITY:       BiDirectionalTraceabilityEvaluator(),
    GateType.NO_BREAKING_CHANGES_UNREVIEWED:   NoBreakingChangesUnreviewedEvaluator(),
}


def get_evaluator(gate_type: GateType) -> GateEvaluator | None:
    return _EVALUATOR_MAP.get(gate_type)
