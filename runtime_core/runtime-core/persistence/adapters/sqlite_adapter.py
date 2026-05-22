"""
runtime_core/persistence/adapters/sqlite_adapter.py
AQuA-QE LKDF v1.4 — SQLiteGraphAdapter

Implementação concreta do GraphRepository sobre SQLite + SQLAlchemy async.
MVP do Blueprint v1.4 — mesma interface que o futuro Neo4jAdapter.

Schema:
  nodes(id, label, external_id, properties JSON, created_at, updated_at)
  edges(id, source_id, target_id, relation, properties JSON, weight, created_at)
  idx_nodes_label, idx_nodes_external_id, idx_edges_source, idx_edges_target, idx_edges_relation
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from runtime_core.persistence.graph.models import Edge, Graph, Node, RelationType
from runtime_core.persistence.graph.repository import GraphRepository

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    properties  TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,
    properties  TEXT NOT NULL DEFAULT '{}',
    weight      REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_label       ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_nodes_external_id ON nodes(external_id);
CREATE INDEX IF NOT EXISTS idx_edges_source      ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target      ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation    ON edges(relation);
CREATE INDEX IF NOT EXISTS idx_edges_source_rel  ON edges(source_id, relation);
"""


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _row_to_node(row: Any) -> Node:
    return Node(
        id=UUID(row.id),
        label=row.label,
        external_id=row.external_id,
        properties=json.loads(row.properties),
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _row_to_edge(row: Any) -> Edge:
    return Edge(
        id=UUID(row.id),
        source_id=UUID(row.source_id),
        target_id=UUID(row.target_id),
        relation=RelationType(row.relation),
        properties=json.loads(row.properties),
        weight=row.weight,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _ts(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# SQLiteGraphAdapter
# ---------------------------------------------------------------------------

class SQLiteGraphAdapter(GraphRepository):
    """
    GraphRepository sobre SQLite com SQLAlchemy async.

    Uso:
        adapter = SQLiteGraphAdapter("sqlite+aiosqlite:///./data/lkdf.db")
        await adapter.initialize()

        node = await adapter.add_node(Node(label="Requirement", external_id="REQ-001"))
        edge = await adapter.add_edge(node.id, other.id, RelationType.HAS_FLOW)
        await adapter.close()
    """

    def __init__(self, db_url: str = "sqlite+aiosqlite:///./data/lkdf.db") -> None:
        self._db_url = db_url
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        self._engine = create_async_engine(
            self._db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        async with self._engine.begin() as conn:
            for statement in _DDL.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    await conn.execute(text(stmt))
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        log.info("sqlite_graph_initialized", url=self._db_url)

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
        log.info("sqlite_graph_closed")

    def _session(self) -> AsyncSession:
        if not self._session_factory:
            raise RuntimeError("SQLiteGraphAdapter not initialized. Call initialize() first.")
        return self._session_factory()

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    async def add_node(self, node: Node) -> Node:
        async with self._session() as s:
            await s.execute(text("""
                INSERT INTO nodes (id, label, external_id, properties, created_at, updated_at)
                VALUES (:id, :label, :external_id, :properties, :created_at, :updated_at)
            """), {
                "id":          str(node.id),
                "label":       node.label,
                "external_id": node.external_id,
                "properties":  json.dumps(node.properties, default=str),
                "created_at":  _ts(node.created_at),
                "updated_at":  _ts(node.updated_at),
            })
            await s.commit()
        log.debug("node_added", label=node.label, external_id=node.external_id)
        return node

    async def get_node(self, node_id: UUID) -> Node | None:
        async with self._session() as s:
            result = await s.execute(
                text("SELECT * FROM nodes WHERE id = :id"),
                {"id": str(node_id)},
            )
            row = result.fetchone()
        return _row_to_node(row) if row else None

    async def get_node_by_external_id(
        self, external_id: str, label: str | None = None
    ) -> Node | None:
        async with self._session() as s:
            q = "SELECT * FROM nodes WHERE external_id = :eid"
            params: dict[str, Any] = {"eid": external_id}
            if label:
                q += " AND label = :label"
                params["label"] = label
            q += " ORDER BY created_at DESC LIMIT 1"
            result = await s.execute(text(q), params)
            row = result.fetchone()
        return _row_to_node(row) if row else None

    async def update_node(self, node: Node) -> Node:
        node.updated_at = datetime.utcnow()
        async with self._session() as s:
            await s.execute(text("""
                UPDATE nodes
                SET label = :label, external_id = :external_id,
                    properties = :properties, updated_at = :updated_at
                WHERE id = :id
            """), {
                "id":          str(node.id),
                "label":       node.label,
                "external_id": node.external_id,
                "properties":  json.dumps(node.properties, default=str),
                "updated_at":  _ts(node.updated_at),
            })
            await s.commit()
        return node

    async def delete_node(self, node_id: UUID) -> bool:
        async with self._session() as s:
            result = await s.execute(
                text("DELETE FROM nodes WHERE id = :id"), {"id": str(node_id)}
            )
            await s.commit()
        return result.rowcount > 0

    async def find_nodes(
        self,
        label:      str | None            = None,
        properties: dict[str, Any] | None = None,
        limit:      int                   = 100,
    ) -> list[Node]:
        async with self._session() as s:
            q = "SELECT * FROM nodes WHERE 1=1"
            params: dict[str, Any] = {}
            if label:
                q += " AND label = :label"
                params["label"] = label
            if properties:
                # SQLite JSON filtering via LIKE — replaced by json_extract in production
                for k, v in properties.items():
                    q += f" AND json_extract(properties, '$.{k}') = :prop_{k}"
                    params[f"prop_{k}"] = v
            q += " ORDER BY created_at DESC LIMIT :limit"
            params["limit"] = limit
            result = await s.execute(text(q), params)
            rows = result.fetchall()
        return [_row_to_node(r) for r in rows]

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        source_id:  UUID,
        target_id:  UUID,
        relation:   RelationType,
        properties: dict[str, Any] | None = None,
        weight:     float                 = 1.0,
    ) -> Edge:
        edge = Edge(
            id=uuid4(),
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            properties=properties or {},
            weight=weight,
        )
        async with self._session() as s:
            await s.execute(text("""
                INSERT INTO edges (id, source_id, target_id, relation, properties, weight, created_at)
                VALUES (:id, :source_id, :target_id, :relation, :properties, :weight, :created_at)
            """), {
                "id":         str(edge.id),
                "source_id":  str(source_id),
                "target_id":  str(target_id),
                "relation":   relation.value,
                "properties": json.dumps(edge.properties, default=str),
                "weight":     weight,
                "created_at": _ts(edge.created_at),
            })
            await s.commit()
        log.debug("edge_added", relation=relation.value)
        return edge

    async def get_edge(self, edge_id: UUID) -> Edge | None:
        async with self._session() as s:
            result = await s.execute(
                text("SELECT * FROM edges WHERE id = :id"), {"id": str(edge_id)}
            )
            row = result.fetchone()
        return _row_to_edge(row) if row else None

    async def delete_edge(self, edge_id: UUID) -> bool:
        async with self._session() as s:
            result = await s.execute(
                text("DELETE FROM edges WHERE id = :id"), {"id": str(edge_id)}
            )
            await s.commit()
        return result.rowcount > 0

    async def get_edges(
        self,
        source_id: UUID | None          = None,
        target_id: UUID | None          = None,
        relation:  RelationType | None  = None,
    ) -> list[Edge]:
        async with self._session() as s:
            q = "SELECT * FROM edges WHERE 1=1"
            params: dict[str, Any] = {}
            if source_id:
                q += " AND source_id = :source_id"
                params["source_id"] = str(source_id)
            if target_id:
                q += " AND target_id = :target_id"
                params["target_id"] = str(target_id)
            if relation:
                q += " AND relation = :relation"
                params["relation"] = relation.value
            result = await s.execute(text(q), params)
            rows = result.fetchall()
        return [_row_to_edge(r) for r in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    async def get_neighbors(
        self,
        node_id:   UUID,
        relation:  RelationType | None = None,
        direction: str                 = "out",
        depth:     int                 = 1,
    ) -> list[Node]:
        if depth == 1:
            return await self._direct_neighbors(node_id, relation, direction)

        # BFS for depth > 1
        visited: set[UUID] = {node_id}
        frontier: list[UUID] = [node_id]
        result_ids: set[UUID] = set()

        for _ in range(depth):
            next_frontier: list[UUID] = []
            for nid in frontier:
                neighbors = await self._direct_neighbors(nid, relation, direction)
                for n in neighbors:
                    if n.id not in visited:
                        visited.add(n.id)
                        result_ids.add(n.id)
                        next_frontier.append(n.id)
            frontier = next_frontier

        all_nodes: list[Node] = []
        for rid in result_ids:
            node = await self.get_node(rid)
            if node:
                all_nodes.append(node)
        return all_nodes

    async def _direct_neighbors(
        self,
        node_id:   UUID,
        relation:  RelationType | None,
        direction: str,
    ) -> list[Node]:
        async with self._session() as s:
            if direction in ("out", "both"):
                q = """
                    SELECT n.* FROM nodes n
                    JOIN edges e ON e.target_id = n.id
                    WHERE e.source_id = :nid
                """
                params: dict[str, Any] = {"nid": str(node_id)}
                if relation:
                    q += " AND e.relation = :rel"
                    params["rel"] = relation.value
                result = await s.execute(text(q), params)
                out_rows = result.fetchall()
            else:
                out_rows = []

            if direction in ("in", "both"):
                q = """
                    SELECT n.* FROM nodes n
                    JOIN edges e ON e.source_id = n.id
                    WHERE e.target_id = :nid
                """
                params = {"nid": str(node_id)}
                if relation:
                    q += " AND e.relation = :rel"
                    params["rel"] = relation.value
                result = await s.execute(text(q), params)
                in_rows = result.fetchall()
            else:
                in_rows = []

        seen: set[str] = set()
        nodes: list[Node] = []
        for row in out_rows + in_rows:
            if row.id not in seen:
                seen.add(row.id)
                nodes.append(_row_to_node(row))
        return nodes

    async def get_subgraph(
        self,
        root_id:   UUID,
        relations: list[RelationType] | None = None,
        max_depth: int                       = 3,
    ) -> Graph:
        visited_nodes: dict[UUID, Node] = {}
        all_edges: list[Edge] = []
        queue: deque[tuple[UUID, int]] = deque([(root_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if current_id in visited_nodes or depth > max_depth:
                continue

            node = await self.get_node(current_id)
            if not node:
                continue
            visited_nodes[current_id] = node

            edges = await self.get_edges(source_id=current_id)
            if relations:
                edges = [e for e in edges if e.relation in relations]
            all_edges.extend(edges)

            for e in edges:
                if e.target_id not in visited_nodes:
                    queue.append((e.target_id, depth + 1))

        return Graph(nodes=list(visited_nodes.values()), edges=all_edges)

    async def get_impact_path(self, node_id: UUID) -> Graph:
        """
        Traversal de impacto: todos os artefatos que dependem ou são gerados
        a partir de um Node (ex: Requirement mudou → o que é afetado?).
        """
        impact_relations = [
            RelationType.HAS_FLOW,
            RelationType.HAS_SCENARIO,
            RelationType.HAS_TEST,
            RelationType.HAS_EXECUTION,
            RelationType.HAS_EVIDENCE,
            RelationType.IMPACTS,
            RelationType.COVERED_BY,
        ]
        return await self.get_subgraph(node_id, relations=impact_relations, max_depth=5)

    async def find_by_intent(self, intent: str, limit: int = 10) -> list[Node]:
        """LIKE search no SQLite — substituído por vector similarity no Neo4j."""
        import unicodedata

        def normalize(s: str) -> str:
            return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

        norm_intent = normalize(intent)

        async with self._session() as s:
            result = await s.execute(
                text("SELECT * FROM nodes ORDER BY updated_at DESC LIMIT 2000")
            )
            rows = result.fetchall()

        matched = []
        for row in rows:
            props_raw = row.properties or "{}"
            # Decode unicode escapes for comparison
            try:
                props_decoded = json.loads(props_raw)
                props_str = json.dumps(props_decoded, ensure_ascii=False)
            except Exception:
                props_str = props_raw

            if (
                intent.lower()   in props_str.lower()
                or norm_intent   in normalize(props_str)
                or intent.lower() in (row.label or "").lower()
                or intent.lower() in (row.external_id or "").lower()
            ):
                matched.append(_row_to_node(row))
            if len(matched) >= limit:
                break
        return matched

    async def shortest_path(self, source_id: UUID, target_id: UUID) -> list[Node]:
        """BFS para caminho mais curto."""
        if source_id == target_id:
            node = await self.get_node(source_id)
            return [node] if node else []

        visited: dict[UUID, UUID | None] = {source_id: None}
        queue: deque[UUID] = deque([source_id])

        while queue:
            current = queue.popleft()
            neighbors = await self._direct_neighbors(current, None, "both")
            for n in neighbors:
                if n.id not in visited:
                    visited[n.id] = current
                    if n.id == target_id:
                        return await self._reconstruct_path(visited, source_id, target_id)
                    queue.append(n.id)

        return []  # no path

    async def _reconstruct_path(
        self,
        visited:   dict[UUID, UUID | None],
        source_id: UUID,
        target_id: UUID,
    ) -> list[Node]:
        path: list[Node] = []
        current: UUID | None = target_id
        while current is not None:
            node = await self.get_node(current)
            if node:
                path.append(node)
            current = visited.get(current)
        path.reverse()
        return path

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    async def add_nodes_bulk(self, nodes: list[Node]) -> list[Node]:
        async with self._session() as s:
            for node in nodes:
                await s.execute(text("""
                    INSERT OR IGNORE INTO nodes
                    (id, label, external_id, properties, created_at, updated_at)
                    VALUES (:id, :label, :external_id, :properties, :created_at, :updated_at)
                """), {
                    "id":          str(node.id),
                    "label":       node.label,
                    "external_id": node.external_id,
                    "properties":  json.dumps(node.properties, default=str),
                    "created_at":  _ts(node.created_at),
                    "updated_at":  _ts(node.updated_at),
                })
            await s.commit()
        log.info("nodes_bulk_added", count=len(nodes))
        return nodes

    async def add_edges_bulk(self, edges: list[Edge]) -> list[Edge]:
        async with self._session() as s:
            for edge in edges:
                await s.execute(text("""
                    INSERT OR IGNORE INTO edges
                    (id, source_id, target_id, relation, properties, weight, created_at)
                    VALUES (:id, :source_id, :target_id, :relation, :properties, :weight, :created_at)
                """), {
                    "id":         str(edge.id),
                    "source_id":  str(edge.source_id),
                    "target_id":  str(edge.target_id),
                    "relation":   edge.relation.value,
                    "properties": json.dumps(edge.properties, default=str),
                    "weight":     edge.weight,
                    "created_at": _ts(edge.created_at),
                })
            await s.commit()
        log.info("edges_bulk_added", count=len(edges))
        return edges
