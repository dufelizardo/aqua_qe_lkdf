"""
ai_engine/knowledge/models.py
AQuA-QE LKDF v1.4 — Knowledge Layer Domain Models

Contratos para a camada de memória organizacional:
  - MemoryEntry: unidade de conhecimento persistida no grafo
  - DefectPattern: padrão aprendido de histórico de defeitos
  - PreventiveSuggestion: sugestão gerada para novos requisitos
  - OntologyNode: conceito de domínio com relacionamentos semânticos
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

class MemoryType(str, Enum):
    DEFECT_PATTERN     = "defect_pattern"      # padrão recorrente de defeitos
    TEST_PATTERN       = "test_pattern"        # padrão de cobertura eficaz
    AMBIGUITY_PATTERN  = "ambiguity_pattern"   # tipo de ambiguidade recorrente
    DOMAIN_CONCEPT     = "domain_concept"      # conceito do domínio da aplicação
    ANTI_PATTERN       = "anti_pattern"        # padrão a evitar
    BEST_PRACTICE      = "best_practice"       # prática recomendada
    FAILURE_MODE       = "failure_mode"        # modo de falha recorrente


class SuggestionType(str, Enum):
    SCENARIO_ADDITION    = "scenario_addition"    # adicionar cenário faltante
    AMBIGUITY_ALERT      = "ambiguity_alert"      # alerta de ambiguidade conhecida
    RISK_WARNING         = "risk_warning"         # risco baseado em histórico
    COVERAGE_GAP         = "coverage_gap"         # gap de cobertura recorrente
    ACCESSIBILITY_CHECK  = "accessibility_check"  # verificação de acessibilidade
    PATTERN_REUSE        = "pattern_reuse"        # reutilização de padrão de sucesso


class ConfidenceLevel(str, Enum):
    HIGH   = "HIGH"    # ≥ 0.80 — padrão altamente confiável
    MEDIUM = "MEDIUM"  # 0.50–0.79
    LOW    = "LOW"     # < 0.50 — sugestão especulativa


# ---------------------------------------------------------------------------
# Memory Entry
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """
    Unidade atômica de conhecimento organizacional.
    Persiste no GraphRepository como Node com label "KnowledgeMemory".
    """
    id:            UUID               = field(default_factory=uuid4)
    memory_type:   MemoryType         = MemoryType.DEFECT_PATTERN
    title:         str                = ""
    description:   str                = ""
    source_ids:    list[str]          = field(default_factory=list)  # story/defect IDs que geraram
    tags:          list[str]          = field(default_factory=list)
    frequency:     int                = 1        # quantas vezes foi observado
    confidence:    float              = 0.5      # 0.0–1.0
    domain:        str                = ""       # ex: "authentication", "payments"
    embedding:     list[float]        = field(default_factory=list)   # vetor semântico
    metadata:      dict[str, Any]     = field(default_factory=dict)
    created_at:    datetime           = field(default_factory=datetime.utcnow)
    updated_at:    datetime           = field(default_factory=datetime.utcnow)
    last_seen_at:  datetime           = field(default_factory=datetime.utcnow)

    @property
    def confidence_level(self) -> ConfidenceLevel:
        if self.confidence >= 0.80:
            return ConfidenceLevel.HIGH
        if self.confidence >= 0.50:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW

    def reinforce(self, source_id: str = "") -> None:
        """Reforça a memória ao observar o padrão novamente."""
        self.frequency  += 1
        self.confidence  = min(1.0, self.confidence + 0.05)
        self.last_seen_at = datetime.utcnow()
        self.updated_at   = datetime.utcnow()
        if source_id and source_id not in self.source_ids:
            self.source_ids.append(source_id)

    def decay(self, factor: float = 0.02) -> None:
        """Decai a confiança quando o padrão não é reforçado (esquecimento)."""
        self.confidence = max(0.0, self.confidence - factor)
        self.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Defect Pattern
# ---------------------------------------------------------------------------

@dataclass
class DefectPattern:
    """
    Padrão aprendido a partir de histórico de defeitos reais.
    Usado para gerar sugestões preventivas em novos requisitos similares.
    """
    id:             UUID            = field(default_factory=uuid4)
    pattern_name:   str             = ""
    description:    str             = ""
    trigger_keywords: list[str]     = field(default_factory=list)  # palavras que ativam
    trigger_domains:  list[str]     = field(default_factory=list)  # domínios relevantes
    defect_ids:     list[str]       = field(default_factory=list)  # defeitos de origem
    occurrences:    int             = 1
    avg_severity:   str             = "P1"
    prevention_steps: list[str]     = field(default_factory=list)  # como prevenir
    suggested_scenarios: list[str]  = field(default_factory=list)  # cenários recomendados
    confidence:     float           = 0.5
    domain:         str             = ""
    created_at:     datetime        = field(default_factory=datetime.utcnow)
    updated_at:     datetime        = field(default_factory=datetime.utcnow)

    @property
    def risk_score(self) -> float:
        """Score de risco 0.0–1.0 baseado em ocorrências e severidade."""
        sev_weight = {"P0": 1.0, "P1": 0.7, "P2": 0.4}.get(self.avg_severity, 0.5)
        freq_weight = min(1.0, self.occurrences / 10.0)
        return round((sev_weight * 0.6 + freq_weight * 0.4) * self.confidence, 3)

    def matches(self, text: str, domain: str = "") -> bool:
        """Verifica se um texto aciona este padrão."""
        text_lower = text.lower()
        keyword_match = any(kw.lower() in text_lower for kw in self.trigger_keywords)
        domain_match  = (
            not self.trigger_domains
            or not domain
            or domain.lower() in [d.lower() for d in self.trigger_domains]
        )
        return keyword_match and domain_match


# ---------------------------------------------------------------------------
# Preventive Suggestion
# ---------------------------------------------------------------------------

@dataclass
class PreventiveSuggestion:
    """
    Sugestão preventiva gerada para um novo requisito baseada em padrões históricos.
    """
    id:              UUID              = field(default_factory=uuid4)
    suggestion_type: SuggestionType   = SuggestionType.RISK_WARNING
    title:           str              = ""
    description:     str              = ""
    rationale:       str              = ""     # por que esta sugestão é relevante
    source_pattern:  str              = ""     # DefectPattern.id ou MemoryEntry.id
    target_story_id: str              = ""
    confidence:      float            = 0.5
    priority:        str              = "MEDIUM"
    action_items:    list[str]        = field(default_factory=list)
    scenarios:       list[str]        = field(default_factory=list)  # DSL steps sugeridos
    metadata:        dict[str, Any]   = field(default_factory=dict)
    created_at:      datetime         = field(default_factory=datetime.utcnow)
    accepted:        bool | None      = None   # None=pendente, True=aceita, False=rejeitada

    @property
    def confidence_level(self) -> ConfidenceLevel:
        if self.confidence >= 0.80:
            return ConfidenceLevel.HIGH
        if self.confidence >= 0.50:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW

    def accept(self) -> None:
        self.accepted = True

    def reject(self) -> None:
        self.accepted = False


# ---------------------------------------------------------------------------
# Ontology Node
# ---------------------------------------------------------------------------

@dataclass
class OntologyNode:
    """
    Conceito de domínio no grafo de conhecimento.
    Representa entidades, ações e relacionamentos do domínio da aplicação.
    """
    id:          UUID            = field(default_factory=uuid4)
    concept:     str             = ""       # ex: "Usuário", "Autenticação", "Pagamento"
    aliases:     list[str]       = field(default_factory=list)
    domain:      str             = ""
    description: str             = ""
    properties:  dict[str, Any]  = field(default_factory=dict)
    related_to:  list[str]       = field(default_factory=list)   # concept names
    embedding:   list[float]     = field(default_factory=list)
    created_at:  datetime        = field(default_factory=datetime.utcnow)

    def matches_text(self, text: str) -> bool:
        text_lower = text.lower()
        return (
            self.concept.lower() in text_lower
            or any(a.lower() in text_lower for a in self.aliases)
        )
