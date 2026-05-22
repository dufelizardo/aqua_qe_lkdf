"""
runtime_core/story_lifecycle/models.py
AQuA-QE LKDF v1.4 — Story Lifecycle Domain Models

Contratos de domínio para o ciclo de vida completo de uma história:
  Story → StoryVersion (DEF / IMP / REG) → Diff → Artifacts
  Taxonomia P0 / P1 / P2 por criticidade
  Artefatos filhos: Defect · Improvement · Regression
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StoryStatus(str, Enum):
    DRAFT      = "DRAFT"
    DEFINED    = "DEFINED"        # DEF — critérios de aceite definidos
    IMPLEMENTED= "IMPLEMENTED"    # IMP — implementação concluída
    REGRESSED  = "REGRESSED"      # REG — regressão detectada
    VALIDATED  = "VALIDATED"      # todos os quality gates passaram
    CLOSED     = "CLOSED"


class SnapshotType(str, Enum):
    DEF = "DEF"   # momento da definição (critérios de aceite)
    IMP = "IMP"   # momento da implementação (código entregue)
    REG = "REG"   # momento da regressão detectada


class ChildType(str, Enum):
    DEFECT      = "DEFECT"
    IMPROVEMENT = "IMPROVEMENT"
    REGRESSION  = "REGRESSION"


class DiffCategory(str, Enum):
    TEXT_CHANGE   = "text_change"     # texto do requisito mudou
    SCOPE_ADD     = "scope_add"       # escopo expandido
    SCOPE_REMOVE  = "scope_remove"    # escopo reduzido
    CRITERIA_ADD  = "criteria_add"    # novo critério de aceite
    CRITERIA_MOD  = "criteria_mod"    # critério alterado
    CRITERIA_DEL  = "criteria_del"    # critério removido
    PRIORITY_CHANGE = "priority_change"


# ---------------------------------------------------------------------------
# Taxonomia P0 / P1 / P2
# ---------------------------------------------------------------------------

class CriticalityLevel(str, Enum):
    P0 = "P0"   # crítico — bloqueia entrega, risco de dados ou segurança
    P1 = "P1"   # alto    — impacto significativo em funcionalidade core
    P2 = "P2"   # médio   — impacto em funcionalidade secundária ou UX


@dataclass
class CriticalityMatrix:
    """
    Matriz de criticidade P0/P1/P2 baseada em:
      - frequência de uso (high / medium / low)
      - impacto no usuário (blocking / degraded / cosmetic)
      - risco de dados ou segurança (yes / no)
    """
    frequency:     str   # high | medium | low
    user_impact:   str   # blocking | degraded | cosmetic
    data_risk:     bool  = False
    security_risk: bool  = False

    @property
    def level(self) -> CriticalityLevel:
        if self.data_risk or self.security_risk:
            return CriticalityLevel.P0
        if self.frequency == "high" and self.user_impact == "blocking":
            return CriticalityLevel.P0
        if self.user_impact == "blocking" or (
            self.frequency == "high" and self.user_impact == "degraded"
        ):
            return CriticalityLevel.P1
        return CriticalityLevel.P2

    @property
    def sla_hours(self) -> int:
        """SLA de resolução em horas por nível."""
        return {
            CriticalityLevel.P0: 4,
            CriticalityLevel.P1: 24,
            CriticalityLevel.P2: 72,
        }[self.level]


# ---------------------------------------------------------------------------
# Diff between versions
# ---------------------------------------------------------------------------

@dataclass
class VersionDiff:
    """Diferença semântica entre duas versões de uma Story."""
    id:            UUID                = field(default_factory=uuid4)
    from_version:  int                 = 0
    to_version:    int                 = 0
    changes:       list[DiffEntry]     = field(default_factory=list)
    ambiguities_introduced: list[str]  = field(default_factory=list)
    scenarios_impacted:     list[str]  = field(default_factory=list)   # scenario IDs
    risk_delta:    str                 = "none"   # none | increased | decreased
    generated_at:  datetime            = field(default_factory=datetime.utcnow)

    @property
    def is_breaking(self) -> bool:
        """True se a mudança pode quebrar scenarios existentes."""
        breaking_categories = {
            DiffCategory.SCOPE_REMOVE,
            DiffCategory.CRITERIA_DEL,
            DiffCategory.CRITERIA_MOD,
        }
        return any(c.category in breaking_categories for c in self.changes)

    @property
    def summary(self) -> str:
        if not self.changes:
            return "Sem mudanças detectadas."
        categories = [c.category.value for c in self.changes]
        return f"{len(self.changes)} mudança(s): {', '.join(set(categories))}"


@dataclass
class DiffEntry:
    """Uma mudança atômica entre versões."""
    category:    DiffCategory
    field_path:  str        # ex: "acceptance_criteria[2].text"
    old_value:   Any        = None
    new_value:   Any        = None
    description: str        = ""


# ---------------------------------------------------------------------------
# Story Version (snapshot imutável)
# ---------------------------------------------------------------------------

@dataclass
class StoryVersion:
    """
    Snapshot imutável de uma Story em um momento do SDLC.
    Uma vez criado, nunca é modificado — apenas lido.
    """
    id:                  UUID                   = field(default_factory=uuid4)
    story_external_id:   str                    = ""       # imutável: "BFTG-127"
    version_number:      int                    = 1
    snapshot_type:       SnapshotType           = SnapshotType.DEF
    title:               str                    = ""
    description:         str                    = ""
    acceptance_criteria: list[str]              = field(default_factory=list)
    priority:            CriticalityLevel       = CriticalityLevel.P1
    status:              StoryStatus            = StoryStatus.DEFINED
    tags:                list[str]              = field(default_factory=list)
    metadata:            dict[str, Any]         = field(default_factory=dict)
    created_at:          datetime               = field(default_factory=datetime.utcnow)
    created_by:          str                    = ""

    @property
    def is_def(self) -> bool:
        return self.snapshot_type == SnapshotType.DEF

    @property
    def is_imp(self) -> bool:
        return self.snapshot_type == SnapshotType.IMP

    @property
    def is_reg(self) -> bool:
        return self.snapshot_type == SnapshotType.REG


# ---------------------------------------------------------------------------
# Story (entidade raiz com ID externo imutável)
# ---------------------------------------------------------------------------

@dataclass
class Story:
    """
    Entidade raiz do Story Lifecycle.
    O external_id é imutável e vem do sistema externo (Jira, Linear, ADO...).
    Versões são adicionadas, nunca removidas.
    """
    external_id:    str                     = ""        # "BFTG-127" — imutável
    title:          str                     = ""
    description:    str                     = ""
    status:         StoryStatus             = StoryStatus.DRAFT
    current_version: int                    = 0
    criticality:    CriticalityLevel        = CriticalityLevel.P1
    versions:       list[StoryVersion]      = field(default_factory=list)
    children:       list[ChildArtifact]     = field(default_factory=list)
    node_id:        UUID | None             = None      # ID no GraphRepository
    created_at:     datetime                = field(default_factory=datetime.utcnow)
    updated_at:     datetime                = field(default_factory=datetime.utcnow)

    @property
    def latest_version(self) -> StoryVersion | None:
        if not self.versions:
            return None
        return max(self.versions, key=lambda v: v.version_number)

    @property
    def def_versions(self) -> list[StoryVersion]:
        return [v for v in self.versions if v.snapshot_type == SnapshotType.DEF]

    @property
    def imp_versions(self) -> list[StoryVersion]:
        return [v for v in self.versions if v.snapshot_type == SnapshotType.IMP]

    @property
    def has_regression(self) -> bool:
        return self.status == StoryStatus.REGRESSED

    @property
    def open_defects(self) -> list[ChildArtifact]:
        return [c for c in self.children
                if c.child_type == ChildType.DEFECT and c.resolved is False]

    def get_version(self, version_number: int) -> StoryVersion | None:
        return next((v for v in self.versions if v.version_number == version_number), None)


# ---------------------------------------------------------------------------
# Child Artifacts
# ---------------------------------------------------------------------------

@dataclass
class ChildArtifact:
    """Artefato filho de uma Story: Defect, Improvement ou Regression."""
    id:               UUID              = field(default_factory=uuid4)
    story_external_id: str              = ""
    child_type:       ChildType         = ChildType.DEFECT
    external_id:      str               = ""      # ID no sistema externo
    title:            str               = ""
    description:      str               = ""
    criticality:      CriticalityLevel  = CriticalityLevel.P1
    resolved:         bool              = False
    caused_by_version: int | None       = None    # versão que causou o problema
    fixed_in_version:  int | None       = None
    created_at:       datetime          = field(default_factory=datetime.utcnow)
    metadata:         dict[str, Any]    = field(default_factory=dict)

    @property
    def sla_hours(self) -> int:
        return CriticalityMatrix(
            frequency="high",
            user_impact="blocking" if self.criticality == CriticalityLevel.P0 else "degraded",
        ).sla_hours
