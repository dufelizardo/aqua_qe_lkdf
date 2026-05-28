"""
AQuA-QE LKDF — Knowledge Layer Cognitivo §31
Memória organizacional viva: padrões reutilizáveis, histórico de análises,
extração de conhecimento de sessões e busca semântica simplificada.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


# ── Paths ──────────────────────────────────────────────────────
_ROOT   = Path(__file__).parent.parent.parent
DB_PATH = _ROOT / "config" / "knowledge.db"


# ── Schema ─────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_items (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,          -- pattern | insight | rn | ca | defect | term
    title        TEXT NOT NULL,
    content      TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '[]',
    source       TEXT NOT NULL DEFAULT '',  -- session_id, story id, etc.
    story_name   TEXT NOT NULL DEFAULT '',
    rn_ids       TEXT NOT NULL DEFAULT '[]',
    ca_ids       TEXT NOT NULL DEFAULT '[]',
    frequency    INTEGER NOT NULL DEFAULT 1,
    confidence   REAL NOT NULL DEFAULT 1.0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    embedding_hash TEXT NOT NULL DEFAULT ''  -- fingerprint para dedup
);

CREATE INDEX IF NOT EXISTS idx_kw_type ON knowledge_items(type);
CREATE INDEX IF NOT EXISTS idx_kw_updated ON knowledge_items(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kw_freq ON knowledge_items(frequency DESC);

CREATE TABLE IF NOT EXISTS knowledge_relations (
    id       TEXT PRIMARY KEY,
    from_id  TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
    to_id    TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
    rel_type TEXT NOT NULL,   -- relates_to | derived_from | contradicts | extends
    weight   REAL NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_rel_from ON knowledge_relations(from_id);
CREATE INDEX IF NOT EXISTS idx_rel_to ON knowledge_relations(to_id);
"""


# ── KnowledgeManager ───────────────────────────────────────────

class KnowledgeManager:
    """
    Gerencia o Knowledge Layer Cognitivo do AQuA-QE.
    Persiste padrões, insights, RNs e CAs reutilizáveis em SQLite.
    Suporta busca por texto livre, filtragem por tipo e detecção de duplicatas.
    """

    ITEM_TYPES = ["pattern", "insight", "rn", "ca", "defect", "term", "scenario"]

    def __init__(self):
        self._lock  = threading.Lock()
        self._ready = False

    def init(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
        self._ready = True
        n = self._count()
        print(f"[KnowledgeManager] DB ready → {DB_PATH} ({n} items)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── CRUD ──────────────────────────────────────────────────

    def add(
        self,
        item_type:  str,
        title:      str,
        content:    str,
        tags:       list[str] = [],
        source:     str = "",
        story_name: str = "",
        rn_ids:     list[str] = [],
        ca_ids:     list[str] = [],
        confidence: float = 1.0,
    ) -> dict:
        """Adiciona ou incrementa frequência se conteúdo duplicado."""
        if not self._ready:
            self.init()

        ehash = self._embed_hash(item_type, title, content)
        now   = datetime.utcnow().isoformat() + "Z"

        with self._lock, self._connect() as conn:
            # Check duplicate by hash
            existing = conn.execute(
                "SELECT id, frequency FROM knowledge_items WHERE embedding_hash=?",
                (ehash,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE knowledge_items SET frequency=frequency+1, updated_at=? WHERE id=?",
                    (now, existing["id"])
                )
                conn.commit()
                return self.get(existing["id"]) or {}

            sid = str(uuid.uuid4())
            row = {
                "id":             sid,
                "type":           item_type,
                "title":          title[:200],
                "content":        content[:4000],
                "tags":           json.dumps(tags),
                "source":         source,
                "story_name":     story_name,
                "rn_ids":         json.dumps(rn_ids),
                "ca_ids":         json.dumps(ca_ids),
                "frequency":      1,
                "confidence":     round(confidence, 3),
                "created_at":     now,
                "updated_at":     now,
                "embedding_hash": ehash,
            }
            conn.execute("""
                INSERT INTO knowledge_items
                  (id,type,title,content,tags,source,story_name,rn_ids,ca_ids,
                   frequency,confidence,created_at,updated_at,embedding_hash)
                VALUES
                  (:id,:type,:title,:content,:tags,:source,:story_name,:rn_ids,:ca_ids,
                   :frequency,:confidence,:created_at,:updated_at,:embedding_hash)
            """, row)
            conn.commit()

        return self._deserialize(row)

    def get(self, item_id: str) -> Optional[dict]:
        if not self._ready:
            self.init()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
        return self._deserialize(dict(row)) if row else None

    def list(
        self,
        item_type: str = "",
        limit:     int = 50,
        offset:    int = 0,
        sort:      str = "updated",  # updated | frequency | confidence
    ) -> list[dict]:
        if not self._ready:
            self.init()
        sort_col = {"updated":"updated_at DESC", "frequency":"frequency DESC", "confidence":"confidence DESC"}.get(sort,"updated_at DESC")
        where = f"WHERE type='{item_type}'" if item_type else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM knowledge_items {where} ORDER BY {sort_col} LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [self._deserialize(dict(r)) for r in rows]

    def search(self, query: str, item_type: str = "", limit: int = 20) -> list[dict]:
        """Busca textual em título, conteúdo e tags."""
        if not self._ready:
            self.init()
        pat = f"%{query}%"
        where = f"AND type='{item_type}'" if item_type else ""
        with self._connect() as conn:
            rows = conn.execute(f"""
                SELECT * FROM knowledge_items
                WHERE (title LIKE ? OR content LIKE ? OR tags LIKE ? OR story_name LIKE ?)
                {where}
                ORDER BY frequency DESC, updated_at DESC
                LIMIT ?
            """, (pat, pat, pat, pat, limit)).fetchall()
        return [self._deserialize(dict(r)) for r in rows]

    def delete(self, item_id: str) -> bool:
        if not self._ready:
            self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM knowledge_items WHERE id=?", (item_id,))
            conn.commit()
        return cur.rowcount > 0

    def update_tags(self, item_id: str, tags: list[str]) -> bool:
        if not self._ready:
            self.init()
        now = datetime.utcnow().isoformat() + "Z"
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE knowledge_items SET tags=?, updated_at=? WHERE id=?",
                (json.dumps(tags), now, item_id)
            )
            conn.commit()
        return cur.rowcount > 0

    # ── Extraction from sessions/responses ──────────────────────

    def extract_from_response(
        self,
        response_text: str,
        story_name:    str = "",
        source:        str = "",
    ) -> list[dict]:
        """
        Extrai RNs, CAs, padrões e insights automaticamente
        de uma resposta do LLM.
        """
        if not self._ready:
            self.init()

        added = []

        # Extract RNs
        rn_matches = re.findall(r"(RN-\d+):\s*(.+?)(?=\n|RN-\d+:|CA-\d+:|$)", response_text)
        for rn_id, rn_text in rn_matches:
            if len(rn_text.strip()) > 10:
                item = self.add(
                    item_type="rn",
                    title=f"{rn_id}: {rn_text.strip()[:80]}",
                    content=rn_text.strip(),
                    tags=["auto-extracted", "rn"],
                    source=source,
                    story_name=story_name,
                    rn_ids=[rn_id],
                    confidence=0.9,
                )
                if item:
                    added.append(item)

        # Extract CAs
        ca_matches = re.findall(r"(CA-\d+):\s*(.+?)(?=\n|CA-\d+:|RN-\d+:|$)", response_text)
        for ca_id, ca_text in ca_matches:
            if len(ca_text.strip()) > 10:
                item = self.add(
                    item_type="ca",
                    title=f"{ca_id}: {ca_text.strip()[:80]}",
                    content=ca_text.strip(),
                    tags=["auto-extracted", "ca"],
                    source=source,
                    story_name=story_name,
                    ca_ids=[ca_id],
                    confidence=0.85,
                )
                if item:
                    added.append(item)

        # Extract Gherkin scenarios as patterns
        gherkin_blocks = re.findall(r"(?:Cenário|Scenario):\s*(.+?)\n((?:.*\n)*?)(?=(?:Cenário|Scenario):|```|$)", response_text)
        for scenario_title, scenario_body in gherkin_blocks:
            if len(scenario_body.strip()) > 30:
                item = self.add(
                    item_type="scenario",
                    title=f"Scenario: {scenario_title.strip()[:80]}",
                    content=scenario_body.strip(),
                    tags=["auto-extracted", "gherkin", "scenario"],
                    source=source,
                    story_name=story_name,
                    confidence=0.8,
                )
                if item:
                    added.append(item)

        # Extract risk patterns (sentences with "Risco: Alto/Médio/Baixo")
        risk_matches = re.findall(r"(?:risco|risk)[:\s]+(?:alto|médio|baixo|high|medium|low)[^.!?]*[.!?]", response_text, re.IGNORECASE)
        for risk_text in risk_matches[:3]:
            item = self.add(
                item_type="pattern",
                title=f"Risco: {risk_text.strip()[:80]}",
                content=risk_text.strip(),
                tags=["auto-extracted", "risk", "pattern"],
                source=source,
                story_name=story_name,
                confidence=0.7,
            )
            if item:
                added.append(item)

        return added

    # ── Relations ──────────────────────────────────────────────

    def add_relation(self, from_id: str, to_id: str, rel_type: str, weight: float = 1.0) -> bool:
        if not self._ready:
            self.init()
        rid = str(uuid.uuid4())
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge_relations (id,from_id,to_id,rel_type,weight) VALUES (?,?,?,?,?)",
                    (rid, from_id, to_id, rel_type, weight)
                )
                conn.commit()
            return True
        except Exception:
            return False

    def get_related(self, item_id: str) -> list[dict]:
        if not self._ready:
            self.init()
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT ki.*, kr.rel_type, kr.weight
                FROM knowledge_relations kr
                JOIN knowledge_items ki ON (kr.to_id=ki.id OR kr.from_id=ki.id)
                WHERE (kr.from_id=? OR kr.to_id=?) AND ki.id!=?
                LIMIT 10
            """, (item_id, item_id, item_id)).fetchall()
        return [self._deserialize(dict(r)) for r in rows]

    # ── Stats ──────────────────────────────────────────────────

    def stats(self) -> dict:
        if not self._ready:
            self.init()
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
            by_type = dict(conn.execute(
                "SELECT type, COUNT(*) as n FROM knowledge_items GROUP BY type"
            ).fetchall())
            top = conn.execute(
                "SELECT title, frequency FROM knowledge_items ORDER BY frequency DESC LIMIT 5"
            ).fetchall()
            recent = conn.execute(
                "SELECT COUNT(*) FROM knowledge_items WHERE updated_at > ?",
                ((datetime.utcnow() - timedelta(days=7)).isoformat(),)
            ).fetchone()[0]
        return {
            "total":        total,
            "by_type":      by_type,
            "top_patterns": [{"title": r["title"], "frequency": r["frequency"]} for r in top],
            "added_last_7d":recent,
        }

    def _count(self) -> int:
        try:
            with self._connect() as conn:
                return conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
        except Exception:
            return 0

    # ── Serialization ──────────────────────────────────────────

    def _deserialize(self, row: dict) -> dict:
        try:
            tags   = json.loads(row.get("tags",   "[]"))
        except Exception:
            tags   = []
        try:
            rn_ids = json.loads(row.get("rn_ids", "[]"))
        except Exception:
            rn_ids = []
        try:
            ca_ids = json.loads(row.get("ca_ids", "[]"))
        except Exception:
            ca_ids = []
        return {
            "id":           row.get("id", ""),
            "type":         row.get("type", ""),
            "title":        row.get("title", ""),
            "content":      row.get("content", ""),
            "tags":         tags,
            "source":       row.get("source", ""),
            "story_name":   row.get("story_name", ""),
            "rn_ids":       rn_ids,
            "ca_ids":       ca_ids,
            "frequency":    row.get("frequency", 1),
            "confidence":   row.get("confidence", 1.0),
            "created_at":   row.get("created_at", ""),
            "updated_at":   row.get("updated_at", ""),
        }

    @staticmethod
    def _embed_hash(item_type: str, title: str, content: str) -> str:
        """Simple fingerprint for deduplication (not a real embedding)."""
        text = f"{item_type}:{title[:100]}:{content[:200]}"
        return hashlib.sha256(text.encode()).hexdigest()[:16]


# Singleton
knowledge_manager = KnowledgeManager()
