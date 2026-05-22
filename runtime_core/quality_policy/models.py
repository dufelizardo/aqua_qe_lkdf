"""
runtime_core/quality_policy/models.py
AQuA-QE LKDF v1.4 — Quality Policy Engine: Domain Models

Contratos para o sistema de quality gates configuráveis por módulo.
Implementa a seção 7 do Blueprint v1.4:
  - Quality gates por escopo (story / flow / module / release)
  - Conformidade WCAG AA como gate mandatório
  - Taxonomia P0/P1/P2 integrada aos gates
  - Rastreabilidade bidirecional mandatória como gate
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Gate types
# ---------------------------------------------------------------------------

class GateType(str, Enum):
    # Coverage gates
    SCENARIO_COVERAGE   = "scenario_coverage"    # % de requisitos com scenarios
    RTM_COVERAGE        = "rtm_coverage"         # % de requisitos no RTM
    EXECUTION_PASS_RATE = "execution_pass_rate"  # % de execuções passando

    # Ambiguity gates
    NO_CRITICAL_AMBIGUITY = "no_critical_ambiguity"  # zero ambiguidades CRITICAL abertas
    AMBIGUITY_SCORE       = "ambiguity_score"        # score máximo permitido

    # Story health
    ACCEPTANCE_CRITERIA   = "acceptance_criteria"    # toda story tem ≥1 critério
    CRITICALITY_CLASSIFIED = "criticality_classified" # toda story tem P0/P1/P2
    NO_OPEN_P0_DEFECTS    = "no_open_p0_defects"    # zero defects P0 abertos
    NO_BREAKING_CHANGES_UNREVIEWED = "no_breaking_changes_unreviewed"

    # Accessibility (WCAG — mandatório)
    WCAG_AA_COMPLIANCE   = "wcag_aa_compliance"      # nível AA obrigatório
    WCAG_A_COMPLIANCE    = "wcag_a_compliance"       # nível A (subconjunto)

    # Traceability (mandatório)
    BIDIRECTIONAL_TRACEABILITY = "bidirectional_traceability"  # req ↔ test ↔ evidence

    # Custom
    CUSTOM               = "custom"


class GateScope(str, Enum):
    STORY   = "story"     # aplicado a uma Story específica
    FLOW    = "flow"      # aplicado a um Flow
    MODULE  = "module"    # aplicado a um conjunto de Stories/Flows
    RELEASE = "release"   # aplicado a uma release completa


class GateResult(str, Enum):
    PASSED  = "PASSED"
    FAILED  = "FAILED"
    WARNING = "WARNING"   # threshold warning (não bloqueia)
    SKIPPED = "SKIPPED"   # gate não aplicável ao contexto


class PolicyAction(str, Enum):
    BLOCK   = "BLOCK"     # falha bloqueia o pipeline
    WARN    = "WARN"      # falha gera warning, não bloqueia
    LOG     = "LOG"       # apenas registra


# ---------------------------------------------------------------------------
# Gate Definition
# ---------------------------------------------------------------------------

@dataclass
class GateDefinition:
    """Definição de um quality gate."""
    id:            UUID          = field(default_factory=uuid4)
    gate_type:     GateType      = GateType.CUSTOM
    name:          str           = ""
    description:   str           = ""
    threshold:     float         = 1.0        # valor mínimo (0.0–1.0 ou %)
    action:        PolicyAction  = PolicyAction.BLOCK
    mandatory:     bool          = False      # True = não pode ser desabilitado
    scope:         GateScope     = GateScope.STORY
    tags:          list[str]     = field(default_factory=list)
    metadata:      dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.action == PolicyAction.BLOCK

    @property
    def display_threshold(self) -> str:
        if self.gate_type in (
            GateType.SCENARIO_COVERAGE,
            GateType.RTM_COVERAGE,
            GateType.EXECUTION_PASS_RATE,
        ):
            return f"{self.threshold * 100:.0f}%"
        return str(self.threshold)


# ---------------------------------------------------------------------------
# Gate Evaluation Result
# ---------------------------------------------------------------------------

@dataclass
class GateEvaluation:
    """Resultado da avaliação de um gate específico."""
    gate_id:       UUID
    gate_type:     GateType
    gate_name:     str
    result:        GateResult
    actual_value:  Any           = None
    threshold:     Any           = None
    action:        PolicyAction  = PolicyAction.BLOCK
    message:       str           = ""
    details:       list[str]     = field(default_factory=list)
    evidence:      dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.result == GateResult.PASSED

    @property
    def blocking_failure(self) -> bool:
        return self.result == GateResult.FAILED and self.action == PolicyAction.BLOCK


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass
class QualityPolicy:
    """
    Política de qualidade configurável por módulo/equipe.
    Agrupa gates com suas configurações e define comportamento global.
    """
    id:            UUID               = field(default_factory=uuid4)
    name:          str                = ""
    description:   str                = ""
    scope:         GateScope          = GateScope.MODULE
    gates:         list[GateDefinition] = field(default_factory=list)
    fail_fast:     bool               = False   # para no primeiro gate bloqueante
    metadata:      dict[str, Any]     = field(default_factory=dict)

    @property
    def mandatory_gates(self) -> list[GateDefinition]:
        return [g for g in self.gates if g.mandatory]

    @property
    def blocking_gates(self) -> list[GateDefinition]:
        return [g for g in self.gates if g.is_blocking]

    def get_gate(self, gate_type: GateType) -> GateDefinition | None:
        return next((g for g in self.gates if g.gate_type == gate_type), None)

    def has_gate(self, gate_type: GateType) -> bool:
        return any(g.gate_type == gate_type for g in self.gates)


# ---------------------------------------------------------------------------
# Policy Evaluation Report
# ---------------------------------------------------------------------------

@dataclass
class PolicyReport:
    """Resultado completo da avaliação de uma política contra um artefato."""
    id:              UUID               = field(default_factory=uuid4)
    policy_name:     str                = ""
    subject_id:      str                = ""   # story/flow/module ID
    subject_type:    str                = ""
    evaluations:     list[GateEvaluation] = field(default_factory=list)
    overall_result:  GateResult         = GateResult.PASSED
    blocking_failures: int              = 0
    warnings:        int                = 0

    @property
    def passed(self) -> bool:
        return self.overall_result == GateResult.PASSED

    @property
    def gate_summary(self) -> dict[str, int]:
        return {
            "total":    len(self.evaluations),
            "passed":   sum(1 for e in self.evaluations if e.result == GateResult.PASSED),
            "failed":   sum(1 for e in self.evaluations if e.result == GateResult.FAILED),
            "warning":  sum(1 for e in self.evaluations if e.result == GateResult.WARNING),
            "skipped":  sum(1 for e in self.evaluations if e.result == GateResult.SKIPPED),
        }

    def failed_gates(self) -> list[GateEvaluation]:
        return [e for e in self.evaluations if e.result == GateResult.FAILED]

    def summary(self) -> dict[str, Any]:
        return {
            "policy":           self.policy_name,
            "subject":          self.subject_id,
            "overall":          self.overall_result.value,
            "passed":           self.passed,
            "blocking_failures": self.blocking_failures,
            "warnings":         self.warnings,
            "gates":            self.gate_summary,
            "failed_gates":     [e.gate_name for e in self.failed_gates()],
        }


# ---------------------------------------------------------------------------
# Built-in policy templates
# ---------------------------------------------------------------------------

def default_story_policy() -> QualityPolicy:
    """Política padrão para avaliação de Stories individuais."""
    return QualityPolicy(
        name="Default Story Policy",
        description="Gates padrão para Stories individuais do LKDF v1.4",
        scope=GateScope.STORY,
        gates=[
            GateDefinition(
                gate_type=GateType.ACCEPTANCE_CRITERIA,
                name="Critérios de aceite",
                description="Toda story deve ter ao menos 1 critério de aceite definido",
                threshold=1.0,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.STORY,
            ),
            GateDefinition(
                gate_type=GateType.CRITICALITY_CLASSIFIED,
                name="Criticidade classificada",
                description="Toda story deve ter P0/P1/P2 classificado",
                threshold=1.0,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.STORY,
            ),
            GateDefinition(
                gate_type=GateType.NO_CRITICAL_AMBIGUITY,
                name="Sem ambiguidades críticas",
                description="Nenhuma ambiguidade CRITICAL não resolvida",
                threshold=0.0,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.STORY,
            ),
            GateDefinition(
                gate_type=GateType.NO_OPEN_P0_DEFECTS,
                name="Sem defects P0 abertos",
                description="Nenhum defect P0 pode estar aberto",
                threshold=0.0,
                action=PolicyAction.BLOCK,
                mandatory=False,
                scope=GateScope.STORY,
            ),
            GateDefinition(
                gate_type=GateType.BIDIRECTIONAL_TRACEABILITY,
                name="Rastreabilidade bidirecional",
                description="Requirement ↔ Test ↔ Evidence deve estar completa",
                threshold=1.0,
                action=PolicyAction.WARN,
                mandatory=True,
                scope=GateScope.STORY,
            ),
        ],
    )


def default_release_policy() -> QualityPolicy:
    """Política padrão para releases — gates mais rigorosos."""
    return QualityPolicy(
        name="Default Release Policy",
        description="Gates para validação de release completa",
        scope=GateScope.RELEASE,
        fail_fast=False,
        gates=[
            GateDefinition(
                gate_type=GateType.SCENARIO_COVERAGE,
                name="Cobertura de cenários",
                description="≥80% dos requisitos têm cenários de teste",
                threshold=0.80,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.RELEASE,
            ),
            GateDefinition(
                gate_type=GateType.EXECUTION_PASS_RATE,
                name="Taxa de aprovação",
                description="≥90% das execuções passando",
                threshold=0.90,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.RELEASE,
            ),
            GateDefinition(
                gate_type=GateType.RTM_COVERAGE,
                name="Cobertura RTM",
                description="≥85% de rastreabilidade no RTM",
                threshold=0.85,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.RELEASE,
            ),
            GateDefinition(
                gate_type=GateType.WCAG_AA_COMPLIANCE,
                name="WCAG AA (mandatório)",
                description="100% de conformidade WCAG 2.1 nível AA",
                threshold=1.0,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.RELEASE,
            ),
            GateDefinition(
                gate_type=GateType.NO_OPEN_P0_DEFECTS,
                name="Sem P0 abertos",
                description="Nenhum defect P0 pode estar aberto na release",
                threshold=0.0,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.RELEASE,
            ),
            GateDefinition(
                gate_type=GateType.BIDIRECTIONAL_TRACEABILITY,
                name="Rastreabilidade completa",
                description="100% de rastreabilidade bidirecional",
                threshold=1.0,
                action=PolicyAction.BLOCK,
                mandatory=True,
                scope=GateScope.RELEASE,
            ),
        ],
    )
