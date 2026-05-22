"""
ai_engine/ambiguity_engine/models.py
AQuA-QE LKDF — Ambiguity Engine: Domain Models

Contratos de dados para toda a camada de análise de ambiguidade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AmbiguityType(str, Enum):
    LEXICAL      = "lexical"       # palavra com múltiplos significados
    REFERENTIAL  = "referential"   # pronome/artigo assume instância única
    SCOPE        = "scope"         # fronteira do comportamento indefinida
    IMPLICIT     = "implicit"      # caminho de falha ou exceção omitido
    TEMPORAL     = "temporal"      # timing / ordenação não especificados
    QUANTITATIVE = "quantitative"  # quantidade / limite numérico vago


class AmbiguitySeverity(str, Enum):
    CRITICAL = "CRITICAL"   # bloqueia implementação correta
    HIGH     = "HIGH"       # alto risco de interpretação divergente
    MEDIUM   = "MEDIUM"     # importante mas workaroundável
    LOW      = "LOW"        # cosmético ou preferência


class RiskLevel(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"


@dataclass
class Ambiguity:
    """Uma ambiguidade identificada em um requisito."""
    id:          str
    type:        AmbiguityType
    severity:    AmbiguitySeverity
    text:        str                    # descrição da ambiguidade
    question:    str                    # pergunta ao analista/PO
    excerpt:     str                    # trecho do requisito que é ambíguo
    options:     list[str] = field(default_factory=list)   # interpretações possíveis
    impact:      str = ""               # impacto se não resolvida
    scenario_hint: str = ""             # cenário de teste sugerido


@dataclass
class BusinessRule:
    """Regra de negócio extraída implicitamente do requisito."""
    id:          str
    description: str
    entities:    list[str] = field(default_factory=list)
    conditions:  list[str] = field(default_factory=list)
    outcomes:    list[str] = field(default_factory=list)
    source:      str = "inferred"       # explicit | inferred | assumed
    confidence:  float = 0.8            # 0.0 – 1.0


@dataclass
class CoverageGap:
    """Cenário ou condição não coberta pelo requisito."""
    id:          str
    description: str
    gap_type:    str    # missing_error_path | missing_edge_case | missing_actor | ...
    priority:    str = "MEDIUM"
    suggested_scenario: str = ""


@dataclass
class AmbiguityReport:
    """Relatório completo de análise de ambiguidade de um requisito."""
    requirement_id:   str
    requirement_text: str
    risk_level:       RiskLevel
    ambiguities:      list[Ambiguity]     = field(default_factory=list)
    business_rules:   list[BusinessRule]  = field(default_factory=list)
    gaps:             list[CoverageGap]   = field(default_factory=list)
    clarifying_questions: list[str]       = field(default_factory=list)
    recommendations:  list[str]           = field(default_factory=list)
    raw_ai:           dict[str, Any]      = field(default_factory=dict)

    # --- Derived metrics ---

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.ambiguities if a.severity == AmbiguitySeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for a in self.ambiguities if a.severity == AmbiguitySeverity.HIGH)

    @property
    def total_ambiguities(self) -> int:
        return len(self.ambiguities)

    @property
    def ambiguity_score(self) -> float:
        """0.0 = sem ambiguidade · 1.0 = completamente ambíguo."""
        if not self.ambiguities:
            return 0.0
        weights = {
            AmbiguitySeverity.CRITICAL: 1.0,
            AmbiguitySeverity.HIGH:     0.7,
            AmbiguitySeverity.MEDIUM:   0.4,
            AmbiguitySeverity.LOW:      0.1,
        }
        total = sum(weights[a.severity] for a in self.ambiguities)
        return min(1.0, total / 5.0)   # normalizado: 5 CRITICALs = score 1.0

    @property
    def is_ready_for_testing(self) -> bool:
        """True se não há ambiguidades críticas sem resolução."""
        return self.critical_count == 0

    def by_type(self, amb_type: AmbiguityType) -> list[Ambiguity]:
        return [a for a in self.ambiguities if a.type == amb_type]

    def summary(self) -> dict[str, Any]:
        return {
            "requirement_id":   self.requirement_id,
            "risk_level":       self.risk_level,
            "total_ambiguities": self.total_ambiguities,
            "critical":         self.critical_count,
            "high":             self.high_count,
            "ambiguity_score":  round(self.ambiguity_score, 2),
            "business_rules":   len(self.business_rules),
            "gaps":             len(self.gaps),
            "is_ready_for_testing": self.is_ready_for_testing,
            "clarifying_questions": self.clarifying_questions,
        }
