"""
runtime_core/persistence/graph/repository.py
AQuA-QE LKDF v1.4 — GraphRepository Interface

Contrato universal do Repository Layer.
Nenhum módulo de domínio usa SQL, ORM ou driver de banco diretamente.
A troca SQLite → PostgreSQL → Neo4j é uma troca de adapter, sem impacto no domínio.

Regra arquitetural (seção 11.2 do Blueprint):
  "Nenhum módulo de domínio pode usar SQL diretamente — apenas a interface GraphRepository."
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from runtime_core.persistence.graph.models import Edge, Graph, Node, RelationType


class GraphRepository(ABC):
    """
    Contrato universal do Graph Repository.
    Implementado por SQLiteGraphAdapter (MVP) e Neo4jAdapter (evolução).
    """

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_node(self, node: Node) -> Node:
        """Persiste um Node e retorna com ID confirmado."""

    @abstractmethod
    async def get_node(self, node_id: UUID) -> Node | None:
        """Recupera Node por ID interno."""

    @abstractmethod
    async def get_node_by_external_id(self, external_id: str, label: str | None = None) -> Node | None:
        """Recupera Node por ID externo (ex: 'BFTG-127', 'REQ-001')."""

    @abstractmethod
    async def update_node(self, node: Node) -> Node:
        """Atualiza propriedades de um Node existente."""

    @abstractmethod
    async def delete_node(self, node_id: UUID) -> bool:
        """Remove Node e todas as suas arestas."""

    @abstractmethod
    async def find_nodes(
        self,
        label:      str | None            = None,
        properties: dict[str, Any] | None = None,
        limit:      int                   = 100,
    ) -> list[Node]:
        """Busca Nodes por label e/ou propriedades."""

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_edge(
        self,
        source_id: UUID,
        target_id: UUID,
        relation:  RelationType,
        properties: dict[str, Any] | None = None,
        weight:     float                 = 1.0,
    ) -> Edge:
        """Cria uma aresta entre dois Nodes."""

    @abstractmethod
    async def get_edge(self, edge_id: UUID) -> Edge | None:
        """Recupera Edge por ID."""

    @abstractmethod
    async def delete_edge(self, edge_id: UUID) -> bool:
        """Remove uma aresta."""

    @abstractmethod
    async def get_edges(
        self,
        source_id: UUID | None      = None,
        target_id: UUID | None      = None,
        relation:  RelationType | None = None,
    ) -> list[Edge]:
        """Busca arestas por source, target e/ou tipo de relação."""

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_neighbors(
        self,
        node_id:  UUID,
        relation: RelationType | None = None,
        direction: str                = "out",   # out | in | both
        depth:     int                = 1,
    ) -> list[Node]:
        """Retorna vizinhos diretos de um Node."""

    @abstractmethod
    async def get_impact_path(self, node_id: UUID) -> Graph:
        """
        Retorna o subgrafo de impacto a partir de um Node.
        Usado para análise de impacto de mudanças (ex: req mudou → o que é afetado?).
        """

    @abstractmethod
    async def find_by_intent(self, intent: str, limit: int = 10) -> list[Node]:
        """
        Busca semântica por intenção.
        No SQLite: LIKE search. No Neo4j/Weaviate: vector similarity.
        """

    @abstractmethod
    async def get_subgraph(
        self,
        root_id:    UUID,
        relations:  list[RelationType] | None = None,
        max_depth:  int                       = 3,
    ) -> Graph:
        """Retorna subgrafo a partir de um Node raiz até max_depth."""

    @abstractmethod
    async def shortest_path(self, source_id: UUID, target_id: UUID) -> list[Node]:
        """Caminho mais curto entre dois Nodes (BFS)."""

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_nodes_bulk(self, nodes: list[Node]) -> list[Node]:
        """Insere múltiplos Nodes em batch."""

    @abstractmethod
    async def add_edges_bulk(self, edges: list[Edge]) -> list[Edge]:
        """Insere múltiplas Edges em batch."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self) -> None:
        """Inicializa o banco (cria tabelas, índices, etc.)."""

    @abstractmethod
    async def close(self) -> None:
        """Fecha conexões."""

    # ------------------------------------------------------------------
    # Helper — upsert pattern
    # ------------------------------------------------------------------

    async def upsert_node(self, node: Node) -> Node:
        """
        Cria ou atualiza um Node por external_id.
        Evita duplicatas em pipelines idempotentes.
        """
        existing = await self.get_node_by_external_id(node.external_id, node.label)
        if existing:
            existing.properties.update(node.properties)
            existing.updated_at = node.updated_at
            return await self.update_node(existing)
        return await self.add_node(node)

    async def ensure_edge(
        self,
        source_id:  UUID,
        target_id:  UUID,
        relation:   RelationType,
        properties: dict[str, Any] | None = None,
    ) -> Edge:
        """
        Cria aresta apenas se não existir (idempotente).
        """
        existing = await self.get_edges(source_id=source_id, target_id=target_id, relation=relation)
        if existing:
            return existing[0]
        return await self.add_edge(source_id, target_id, relation, properties)
