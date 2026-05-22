"""
runtime_core/persistence/graph/models.py
AQuA-QE LKDF v1.4 — Graph Domain Models

Contratos universais de grafo. Nenhum módulo de domínio
conhece SQL — apenas Node, Edge e RelationType.

A persistência é um detalhe de infraestrutura;
o domínio fala grafo desde o dia zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Relation types — vocabulário semântico do Knowledge Graph
# ---------------------------------------------------------------------------

class RelationType(str, Enum):
    # Requirement chain
    HAS_RULE          = "HAS_RULE"           # Requirement → BusinessRule
    HAS_CRITERION     = "HAS_CRITERION"      # Requirement → AcceptanceCriterion
    HAS_FLOW          = "HAS_FLOW"           # Requirement → Flow
    HAS_SCENARIO      = "HAS_SCENARIO"       # Flow → Scenario
    HAS_TEST          = "HAS_TEST"           # Scenario → TestCase
    HAS_EXECUTION     = "HAS_EXECUTION"      # TestCase → Execution
    HAS_EVIDENCE      = "HAS_EVIDENCE"       # Execution → Evidence
    HAS_DEFECT        = "HAS_DEFECT"         # Execution → Defect

    # Story lifecycle
    HAS_VERSION       = "HAS_VERSION"        # Story → StoryVersion
    NEXT_VERSION      = "NEXT_VERSION"       # StoryVersion → StoryVersion
    HAS_CHILD         = "HAS_CHILD"          # Story → Defect | Improvement | Regression
    CAUSED_BY         = "CAUSED_BY"          # Regression → Story (that caused it)
    FIXED_IN          = "FIXED_IN"           # Defect → StoryVersion (where fixed)

    # Impact
    IMPACTS           = "IMPACTS"            # Requirement → Requirement (change impact)
    DEPENDS_ON        = "DEPENDS_ON"         # Requirement → Requirement
    CONTRADICTS       = "CONTRADICTS"        # Requirement → Requirement
    COVERED_BY        = "COVERED_BY"         # Requirement → TestCase

    # Accessibility & quality
    VIOLATES          = "VIOLATES"           # Component → WcagCriterion
    SATISFIES         = "SATISFIES"          # Component → WcagCriterion
    HAS_RISK          = "HAS_RISK"           # Requirement → Risk

    # Knowledge
    SIMILAR_TO        = "SIMILAR_TO"         # Node → Node (semantic similarity)
    INSTANCE_OF       = "INSTANCE_OF"        # Node → ConceptNode
    LEARNED_FROM      = "LEARNED_FROM"       # Pattern → HistoricalDefect


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """Unidade universal do Knowledge Graph."""
    id:         UUID                  = field(default_factory=uuid4)
    label:      str                   = ""          # tipo: "Requirement", "Flow", "Story"...
    external_id: str                  = ""          # ex: "BFTG-127", "REQ-001"
    properties: dict[str, Any]        = field(default_factory=dict)
    created_at: datetime              = field(default_factory=datetime.utcnow)
    updated_at: datetime              = field(default_factory=datetime.utcnow)

    def get(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.properties[key] = value
        self.updated_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"Node({self.label}:{self.external_id or str(self.id)[:8]})"


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """Relacionamento direcional entre dois Nodes."""
    id:           UUID               = field(default_factory=uuid4)
    source_id:    UUID               = field(default_factory=uuid4)
    target_id:    UUID               = field(default_factory=uuid4)
    relation:     RelationType       = RelationType.HAS_FLOW
    properties:   dict[str, Any]     = field(default_factory=dict)
    weight:       float              = 1.0           # relevância semântica 0.0–1.0
    created_at:   datetime           = field(default_factory=datetime.utcnow)

    def __repr__(self) -> str:
        return f"Edge({self.source_id!s:.8}→{self.relation}→{self.target_id!s:.8})"


# ---------------------------------------------------------------------------
# Graph — resultado de queries
# ---------------------------------------------------------------------------

@dataclass
class Graph:
    """Subgrafo retornado por queries do GraphRepository."""
    nodes: list[Node]  = field(default_factory=list)
    edges: list[Edge]  = field(default_factory=list)

    @property
    def node_ids(self) -> set[UUID]:
        return {n.id for n in self.nodes}

    def find_node(self, node_id: UUID) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def find_by_label(self, label: str) -> list[Node]:
        return [n for n in self.nodes if n.label == label]

    def find_by_external_id(self, external_id: str) -> Node | None:
        return next((n for n in self.nodes if n.external_id == external_id), None)

    def edges_from(self, node_id: UUID) -> list[Edge]:
        return [e for e in self.edges if e.source_id == node_id]

    def edges_to(self, node_id: UUID) -> list[Edge]:
        return [e for e in self.edges if e.target_id == node_id]

    def neighbors(self, node_id: UUID, relation: RelationType | None = None) -> list[Node]:
        edges = self.edges_from(node_id)
        if relation:
            edges = [e for e in edges if e.relation == relation]
        target_ids = {e.target_id for e in edges}
        return [n for n in self.nodes if n.id in target_ids]

    def __len__(self) -> int:
        return len(self.nodes)

    def is_empty(self) -> bool:
        return not self.nodes

    def merge(self, other: "Graph") -> "Graph":
        """Une dois subgrafos sem duplicar nós ou arestas."""
        existing_node_ids = self.node_ids
        existing_edge_ids = {e.id for e in self.edges}
        return Graph(
            nodes=self.nodes + [n for n in other.nodes if n.id not in existing_node_ids],
            edges=self.edges + [e for e in other.edges if e.id not in existing_edge_ids],
        )
