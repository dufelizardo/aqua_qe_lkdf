"""
AQuA-QE LKDF — Graph Database §33
Grafo de conhecimento persistente em SQLite.

Interface compatível com Neo4j (nodes + relationships + Cypher-like queries).
Usa adjacency list + CTEs recursivas para travessia de grafos.

Nós (nodes):   { id, label, props }
Arestas (rels): { id, from_id, to_id, type, weight, props }

Labels usados no LKDF:
  Story, Requirement (RN), AcceptanceCriteria (CA),
  TestCase (CT), Risk, Defect, Pattern, Scenario
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ─────────────────────────────────────────────────────
_ROOT   = Path(__file__).parent.parent.parent
DB_PATH = _ROOT / "config" / "graph.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    props      TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_nodes_name  ON nodes(name);

CREATE TABLE IF NOT EXISTS relationships (
    id         TEXT PRIMARY KEY,
    from_id    TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_id      TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    weight     REAL NOT NULL DEFAULT 1.0,
    props      TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_id);
CREATE INDEX IF NOT EXISTS idx_rel_to   ON relationships(to_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(type);
"""


class GraphNode:
    def __init__(self, id: str, label: str, name: str, props: dict, created_at: str = "", updated_at: str = ""):
        self.id         = id
        self.label      = label
        self.name       = name
        self.props      = props
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "name": self.name,
                "props": self.props, "created_at": self.created_at, "updated_at": self.updated_at}


class GraphRel:
    def __init__(self, id: str, from_id: str, to_id: str, type: str,
                 weight: float = 1.0, props: dict = {}, created_at: str = ""):
        self.id         = id
        self.from_id    = from_id
        self.to_id      = to_id
        self.type       = type
        self.weight     = weight
        self.props      = props
        self.created_at = created_at

    def to_dict(self) -> dict:
        return {"id": self.id, "from_id": self.from_id, "to_id": self.to_id,
                "type": self.type, "weight": self.weight, "props": self.props,
                "created_at": self.created_at}


class GraphDB:
    """
    SQLite-backed graph database with Neo4j-compatible interface.

    Node operations:  merge_node, get_node, find_nodes, delete_node
    Rel operations:   merge_rel, get_rel, find_rels, delete_rel
    Traversal:        neighbors, shortest_path, reachable, subgraph
    Analytics:        degree, centrality, communities (label propagation)
    Import/Export:    from_knowledge_layer, to_cytoscape, to_d3
    """

    # ── Relationship types ────────────────────────────────────
    REL_TYPES = {
        "HAS_REQUIREMENT":   "Story → RN",
        "HAS_CRITERIA":      "RN → CA",
        "COVERED_BY":        "CA → CT",
        "HAS_RISK":          "Story → Risk",
        "TRIGGERS_DEFECT":   "CT → Defect",
        "DERIVED_FROM":      "Pattern → Pattern",
        "VALIDATES":         "CT → RN",
        "EXTENDS":           "Story → Story",
        "CONTRADICTS":       "RN → RN",
        "SIMILAR_TO":        "any → any",
    }

    def __init__(self):
        self._lock  = threading.Lock()
        self._ready = False

    def init(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
        self._ready = True
        n_nodes = self._count("nodes")
        n_rels  = self._count("relationships")
        print(f"[GraphDB] Ready → {DB_PATH} ({n_nodes} nodes, {n_rels} rels)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _now(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    def _count(self, table: str) -> int:
        try:
            with self._connect() as conn:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            return 0

    # ── Node operations ───────────────────────────────────────

    def merge_node(self, label: str, name: str, props: dict | None = None,
                   node_id: str | None = None) -> GraphNode:
        """
        MERGE (n:Label {name: name}) SET n += props
        Creates or updates a node. Returns the node.
        """
        if not self._ready:
            self.init()
        props = props or {}
        now   = self._now()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM nodes WHERE label=? AND name=?", (label, name)
            ).fetchone()
            if existing:
                merged_props = {**json.loads(existing["props"]), **props}
                conn.execute(
                    "UPDATE nodes SET props=?, updated_at=? WHERE id=?",
                    (json.dumps(merged_props), now, existing["id"])
                )
                conn.commit()
                return GraphNode(existing["id"], label, name, merged_props, existing["created_at"], now)
            nid = node_id or str(uuid.uuid4())[:12]
            conn.execute(
                "INSERT INTO nodes (id,label,name,props,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (nid, label, name, json.dumps(props), now, now)
            )
            conn.commit()
            return GraphNode(nid, label, name, props, now, now)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        if not self._ready: self.init()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return self._row_to_node(dict(row)) if row else None

    def find_nodes(self, label: str = "", name_like: str = "", limit: int = 50) -> list[GraphNode]:
        if not self._ready: self.init()
        where, params = [], []
        if label:     where.append("label=?");         params.append(label)
        if name_like: where.append("name LIKE ?");     params.append(f"%{name_like}%")
        sql = "SELECT * FROM nodes"
        if where: sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY updated_at DESC LIMIT {limit}"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_node(dict(r)) for r in rows]

    def delete_node(self, node_id: str) -> bool:
        if not self._ready: self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            conn.commit()
        return cur.rowcount > 0

    # ── Relationship operations ───────────────────────────────

    def merge_rel(self, from_id: str, to_id: str, rel_type: str,
                  weight: float = 1.0, props: dict | None = None) -> Optional[GraphRel]:
        """
        MERGE (a)-[r:TYPE]->(b) SET r.weight = weight
        Creates or updates a relationship.
        """
        if not self._ready: self.init()
        props = props or {}
        now   = self._now()
        with self._lock, self._connect() as conn:
            # Verify nodes exist
            if not conn.execute("SELECT 1 FROM nodes WHERE id=?", (from_id,)).fetchone():
                return None
            if not conn.execute("SELECT 1 FROM nodes WHERE id=?", (to_id,)).fetchone():
                return None
            existing = conn.execute(
                "SELECT * FROM relationships WHERE from_id=? AND to_id=? AND type=?",
                (from_id, to_id, rel_type)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE relationships SET weight=?, props=? WHERE id=?",
                    (weight, json.dumps(props), existing["id"])
                )
                conn.commit()
                return GraphRel(existing["id"], from_id, to_id, rel_type, weight, props, existing["created_at"])
            rid = str(uuid.uuid4())[:12]
            conn.execute(
                "INSERT INTO relationships (id,from_id,to_id,type,weight,props,created_at) VALUES (?,?,?,?,?,?,?)",
                (rid, from_id, to_id, rel_type, weight, json.dumps(props), now)
            )
            conn.commit()
            return GraphRel(rid, from_id, to_id, rel_type, weight, props, now)

    def find_rels(self, from_id: str = "", to_id: str = "", rel_type: str = "") -> list[GraphRel]:
        if not self._ready: self.init()
        where, params = [], []
        if from_id:  where.append("from_id=?");  params.append(from_id)
        if to_id:    where.append("to_id=?");    params.append(to_id)
        if rel_type: where.append("type=?");     params.append(rel_type)
        sql = "SELECT * FROM relationships"
        if where: sql += " WHERE " + " AND ".join(where)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_rel(dict(r)) for r in rows]

    def delete_rel(self, rel_id: str) -> bool:
        if not self._ready: self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM relationships WHERE id=?", (rel_id,))
            conn.commit()
        return cur.rowcount > 0

    # ── Graph traversal ───────────────────────────────────────

    def neighbors(self, node_id: str, direction: str = "both",
                  rel_type: str = "", depth: int = 1) -> list[dict]:
        """
        MATCH (n)-[r*1..depth]-(neighbor) RETURN neighbor, r
        direction: "out" | "in" | "both"
        """
        if not self._ready: self.init()
        if depth == 1:
            return self._neighbors_direct(node_id, direction, rel_type)
        return self._neighbors_bfs(node_id, direction, rel_type, depth)

    def _neighbors_direct(self, node_id: str, direction: str, rel_type: str) -> list[dict]:
        with self._connect() as conn:
            results = []
            type_filter = " AND r.type=?" if rel_type else ""
            type_param  = [rel_type] if rel_type else []
            if direction in ("out", "both"):
                rows = conn.execute(
                    f"SELECT n.*, r.type as rel_type, r.weight FROM relationships r "
                    f"JOIN nodes n ON r.to_id=n.id WHERE r.from_id=?{type_filter}",
                    [node_id] + type_param
                ).fetchall()
                results += [{"node": self._row_to_node(dict(r)).to_dict(),
                             "rel_type": r["rel_type"], "weight": r["weight"], "direction": "out"}
                            for r in rows]
            if direction in ("in", "both"):
                rows = conn.execute(
                    f"SELECT n.*, r.type as rel_type, r.weight FROM relationships r "
                    f"JOIN nodes n ON r.from_id=n.id WHERE r.to_id=?{type_filter}",
                    [node_id] + type_param
                ).fetchall()
                results += [{"node": self._row_to_node(dict(r)).to_dict(),
                             "rel_type": r["rel_type"], "weight": r["weight"], "direction": "in"}
                            for r in rows]
        return results

    def _neighbors_bfs(self, start_id: str, direction: str, rel_type: str, depth: int) -> list[dict]:
        """BFS multi-hop usando CTE recursiva."""
        if direction == "out":
            join_cond  = "rel.from_id = bfs.node_id"
            next_col   = "rel.to_id"
        elif direction == "in":
            join_cond  = "rel.to_id = bfs.node_id"
            next_col   = "rel.from_id"
        else:
            # both — run twice
            out = self._neighbors_bfs(start_id, "out", rel_type, depth)
            inn = self._neighbors_bfs(start_id, "in",  rel_type, depth)
            seen, combined = set(), []
            for r in out + inn:
                nid = r["node"]["id"]
                if nid != start_id and nid not in seen:
                    seen.add(nid); combined.append(r)
            return combined

        type_filter = f"AND rel.type='{rel_type}'" if rel_type else ""
        sql = f"""
        WITH RECURSIVE bfs(node_id, hop, rtype, rweight) AS (
            SELECT ? AS node_id, 0 AS hop, '' AS rtype, 1.0 AS rweight
            UNION ALL
            SELECT {next_col}, bfs.hop + 1, rel.type, rel.weight
            FROM relationships AS rel
            JOIN bfs ON {join_cond}
            WHERE bfs.hop < {depth} {type_filter}
        )
        SELECT DISTINCT
               n.id, n.label, n.name, n.props, n.created_at, n.updated_at,
               bfs.rtype  AS rel_type,
               bfs.rweight AS weight,
               bfs.hop    AS depth
        FROM bfs
        JOIN nodes AS n ON n.id = bfs.node_id
        WHERE bfs.node_id != ?
        ORDER BY bfs.hop
        """
        with self._connect() as conn:
            rows = conn.execute(sql, [start_id, start_id]).fetchall()
        return [
            {
                "node":      self._row_to_node(dict(row)).to_dict(),
                "rel_type":  row["rel_type"],
                "weight":    row["weight"],
                "depth":     row["depth"],
                "direction": direction,
            }
            for row in rows
        ]

    def shortest_path(self, from_id: str, to_id: str, max_depth: int = 8) -> list[dict]:
        """BFS para caminho mais curto entre dois nós."""
        if not self._ready: self.init()
        visited = {from_id: None}  # node_id → parent
        queue   = [from_id]
        while queue:
            current = queue.pop(0)
            if current == to_id:
                # Reconstruct path
                path, node = [], to_id
                while node:
                    n = self.get_node(node)
                    if n: path.append(n.to_dict())
                    node = visited[node]
                return list(reversed(path))
            if len(visited) > max_depth * 10:
                break
            for nb in self._neighbors_direct(current, "out", ""):
                nid = nb["node"]["id"]
                if nid not in visited:
                    visited[nid] = current
                    queue.append(nid)
        return []  # no path found

    def reachable(self, from_id: str, max_depth: int = 5) -> list[GraphNode]:
        """Retorna todos os nós alcançáveis a partir de from_id."""
        results = self._neighbors_bfs(from_id, "out", "", max_depth)
        seen    = set()
        nodes   = []
        for r in results:
            nid = r["node"]["id"]
            if nid not in seen:
                seen.add(nid)
                nodes.append(self._row_to_node(r["node"]))
        return nodes

    def subgraph(self, node_ids: list[str]) -> dict:
        """Extrai subgrafo induzido pelos nós fornecidos."""
        if not self._ready: self.init()
        id_set = set(node_ids)
        nodes, rels = [], []
        with self._connect() as conn:
            for nid in node_ids:
                row = conn.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
                if row: nodes.append(self._row_to_node(dict(row)).to_dict())
            # Rels between these nodes only
            placeholders = ",".join("?" * len(node_ids))
            rows = conn.execute(
                f"SELECT * FROM relationships WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})",
                node_ids + node_ids
            ).fetchall()
            rels = [self._row_to_rel(dict(r)).to_dict() for r in rows]
        return {"nodes": nodes, "relationships": rels}

    # ── Analytics ─────────────────────────────────────────────

    def degree(self, node_id: str) -> dict:
        """Grau de entrada, saída e total de um nó."""
        with self._connect() as conn:
            out_deg = conn.execute("SELECT COUNT(*) FROM relationships WHERE from_id=?", (node_id,)).fetchone()[0]
            in_deg  = conn.execute("SELECT COUNT(*) FROM relationships WHERE to_id=?",   (node_id,)).fetchone()[0]
        return {"in": in_deg, "out": out_deg, "total": in_deg + out_deg}

    def centrality(self, top_k: int = 10) -> list[dict]:
        """
        Degree centrality — nós mais conectados (hubs do grafo).
        Approximates betweenness by degree count.
        """
        if not self._ready: self.init()
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT n.id, n.label, n.name,
                       COUNT(DISTINCT r1.id) + COUNT(DISTINCT r2.id) as degree
                FROM nodes n
                LEFT JOIN relationships r1 ON r1.from_id = n.id
                LEFT JOIN relationships r2 ON r2.to_id   = n.id
                GROUP BY n.id
                ORDER BY degree DESC
                LIMIT ?
            """, (top_k,)).fetchall()
        return [{"id": r["id"], "label": r["label"], "name": r["name"], "degree": r["degree"]}
                for r in rows]

    def stats(self) -> dict:
        if not self._ready: self.init()
        with self._connect() as conn:
            n_nodes  = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            n_rels   = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
            by_label = dict(conn.execute(
                "SELECT label, COUNT(*) FROM nodes GROUP BY label"
            ).fetchall())
            by_type  = dict(conn.execute(
                "SELECT type, COUNT(*) FROM relationships GROUP BY type"
            ).fetchall())
        return {
            "nodes":        n_nodes,
            "relationships":n_rels,
            "by_label":     by_label,
            "by_rel_type":  by_type,
            "density":      round(n_rels / max(n_nodes * (n_nodes-1), 1), 4),
        }

    # ── Import from Knowledge Layer ───────────────────────────

    def import_from_knowledge(self, items: list[dict]) -> dict:
        """
        Importa itens do Knowledge Layer como nós e cria
        arestas automáticas baseadas nos rn_ids e ca_ids.
        """
        created_nodes = 0
        created_rels  = 0
        node_map: dict[str, str] = {}  # item_id → graph_node_id

        for item in items:
            label = {
                "rn":      "Requirement",
                "ca":      "AcceptanceCriteria",
                "ct":      "TestCase",
                "pattern": "Pattern",
                "insight": "Insight",
                "scenario":"Scenario",
                "defect":  "Defect",
                "term":    "Term",
            }.get(item.get("type",""), "KnowledgeItem")

            node = self.merge_node(
                label=label,
                name=item.get("title","")[:120],
                props={
                    "content":    item.get("content","")[:500],
                    "tags":       item.get("tags",[]),
                    "story_name": item.get("story_name",""),
                    "frequency":  item.get("frequency",1),
                    "confidence": item.get("confidence",1.0),
                    "source_id":  item.get("id",""),
                },
                node_id=f"ki-{item.get('id','')[:8]}"
            )
            node_map[item.get("id","")] = node.id
            created_nodes += 1

            # Story node
            if item.get("story_name"):
                story = self.merge_node("Story", item["story_name"])
                rel_type = {
                    "Requirement":        "HAS_REQUIREMENT",
                    "AcceptanceCriteria": "HAS_CRITERIA",
                    "Pattern":            "HAS_REQUIREMENT",
                }.get(label, "RELATES_TO")
                rel = self.merge_rel(story.id, node.id, rel_type)
                if rel: created_rels += 1

        # RN → CA edges from rn_ids/ca_ids
        for item in items:
            if item.get("type") == "ca" and item.get("rn_ids"):
                ca_gid = node_map.get(item.get("id",""))
                if not ca_gid: continue
                for rn_id_ref in item["rn_ids"]:
                    # Find RN node by source_id
                    with self._connect() as conn:
                        rn_row = conn.execute(
                            "SELECT id FROM nodes WHERE json_extract(props,'$.source_id')=?",
                            (rn_id_ref,)
                        ).fetchone()
                    if rn_row:
                        rel = self.merge_rel(rn_row["id"], ca_gid, "HAS_CRITERIA")
                        if rel: created_rels += 1

        return {"nodes_created": created_nodes, "rels_created": created_rels}

    # ── Export for visualization ──────────────────────────────

    def to_cytoscape(self, label_filter: str = "", limit: int = 200) -> dict:
        """Exporta grafo no formato Cytoscape.js elements."""
        nodes = self.find_nodes(label=label_filter, limit=limit)
        node_ids = [n.id for n in nodes]
        elements = []

        for node in nodes:
            color = {
                "Story":              "#00509E",
                "Requirement":        "#00D4AA",
                "AcceptanceCriteria": "#0070CC",
                "TestCase":           "#10B981",
                "Risk":               "#EF4444",
                "Defect":             "#F97316",
                "Pattern":            "#7C3AED",
                "Scenario":           "#F59E0B",
            }.get(node.label, "#6B8CAE")
            elements.append({
                "data": {
                    "id":    node.id,
                    "label": node.label,
                    "name":  node.name[:40],
                    "color": color,
                    "size":  max(24, min(48, node.props.get("frequency",1)*8)),
                    "props": node.props,
                }
            })

        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            with self._connect() as conn:
                rels = conn.execute(
                    f"SELECT * FROM relationships WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})",
                    node_ids + node_ids
                ).fetchall()
            for r in rels:
                elements.append({
                    "data": {
                        "id":     r["id"],
                        "source": r["from_id"],
                        "target": r["to_id"],
                        "type":   r["type"],
                        "weight": r["weight"],
                    }
                })
        return {"elements": elements, "node_count": len(nodes), "edge_count": len(elements) - len(nodes)}

    def to_d3(self, limit: int = 150) -> dict:
        """Exporta grafo no formato D3.js force simulation."""
        nodes = self.find_nodes(limit=limit)
        node_ids = [n.id for n in nodes]
        d3_nodes = [{"id": n.id, "label": n.label, "name": n.name[:40],
                     "group": n.label, "props": n.props} for n in nodes]
        d3_links = []
        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            with self._connect() as conn:
                rels = conn.execute(
                    f"SELECT * FROM relationships WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})",
                    node_ids + node_ids
                ).fetchall()
            d3_links = [{"source": r["from_id"], "target": r["to_id"],
                         "type": r["type"], "value": r["weight"]} for r in rels]
        return {"nodes": d3_nodes, "links": d3_links}

    # ── Serialization helpers ─────────────────────────────────

    @staticmethod
    def _row_to_node(row: dict) -> GraphNode:
        try:   props = json.loads(row.get("props", "{}"))
        except: props = {}
        return GraphNode(row["id"], row["label"], row.get("name",""),
                         props, row.get("created_at",""), row.get("updated_at",""))

    @staticmethod
    def _row_to_rel(row: dict) -> GraphRel:
        try:   props = json.loads(row.get("props","{}"))
        except: props = {}
        return GraphRel(row["id"], row["from_id"], row["to_id"],
                        row["type"], row.get("weight",1.0), props, row.get("created_at",""))


# ── Singleton ────────────────────────────────────────────────
graph_db = GraphDB()
