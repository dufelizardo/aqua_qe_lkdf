"""
AQuA-QE LKDF — Session Manager
Persistência de sessões de chat em SQLite (§18 MVP → §33 evolutivo).

Estrutura da tabela sessions:
  id           TEXT PK  — UUID
  title        TEXT     — título gerado (primeiros 60 chars da 1ª mensagem)
  summary      TEXT     — resumo automático (RNs, CTs, provider)
  created_at   TEXT     — ISO datetime
  updated_at   TEXT     — ISO datetime
  provider     TEXT     — provider usado
  model        TEXT     — modelo usado
  engine       TEXT     — engine principal
  messages     TEXT     — JSON [{role, content}]
  rtm_items    TEXT     — JSON [RTM rows]
  metadata     TEXT     — JSON {cost, tokens, msg_count, rn_count, ct_count}
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ── Paths ──────────────────────────────────────────────────────
_ROOT   = Path(__file__).parent.parent.parent   # aqua-gateway/
DB_PATH = _ROOT / "config" / "sessions.db"


# ── Helpers ────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _ensure_db_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── SessionManager ─────────────────────────────────────────────

class SessionManager:
    """
    Thread-safe SQLite session store.
    Cada sessão = uma conversa completa do chat com histórico,
    RTM items, metadados de custo/tokens e provider usado.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ready = False

    def init(self):
        """Inicializa o banco. Chamado no startup."""
        _ensure_db_dir()
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL DEFAULT '',
                    summary     TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    provider    TEXT NOT NULL DEFAULT '',
                    model       TEXT NOT NULL DEFAULT '',
                    engine      TEXT NOT NULL DEFAULT 'requirement',
                    messages    TEXT NOT NULL DEFAULT '[]',
                    rtm_items   TEXT NOT NULL DEFAULT '[]',
                    metadata    TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions (updated_at DESC)
            """)
            conn.commit()
        self._ready = True
        print(f"[SessionManager] DB ready → {DB_PATH}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── CRUD ──────────────────────────────────────────────────

    def create_session(
        self,
        messages: list[dict],
        rtm_items: list[dict] = [],
        provider: str = "",
        model: str = "",
        engine: str = "requirement",
        metadata: dict = {},
    ) -> dict:
        """Cria uma nova sessão e retorna o objeto completo."""
        if not self._ready:
            self.init()

        sid   = str(uuid.uuid4())
        now   = _now()
        title = self._generate_title(messages)
        summary = self._generate_summary(messages, rtm_items, provider, metadata)

        row = {
            "id":         sid,
            "title":      title,
            "summary":    summary,
            "created_at": now,
            "updated_at": now,
            "provider":   provider,
            "model":      model,
            "engine":     engine,
            "messages":   json.dumps(messages,  ensure_ascii=False),
            "rtm_items":  json.dumps(rtm_items, ensure_ascii=False),
            "metadata":   json.dumps(metadata,  ensure_ascii=False),
        }
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO sessions
                  (id,title,summary,created_at,updated_at,provider,model,engine,messages,rtm_items,metadata)
                VALUES
                  (:id,:title,:summary,:created_at,:updated_at,:provider,:model,:engine,:messages,:rtm_items,:metadata)
            """, row)
            conn.commit()

        return self._deserialize(row)

    def update_session(
        self,
        session_id: str,
        messages: list[dict] | None = None,
        rtm_items: list[dict] | None = None,
        provider: str | None = None,
        model:    str | None = None,
        engine:   str | None = None,
        metadata: dict | None = None,
    ) -> Optional[dict]:
        """Atualiza uma sessão existente."""
        if not self._ready:
            self.init()

        existing = self.get_session(session_id)
        if not existing:
            return None

        now = _now()
        merged_messages  = messages  if messages  is not None else existing["messages"]
        merged_rtm       = rtm_items if rtm_items is not None else existing["rtm_items"]
        merged_provider  = provider  if provider  is not None else existing["provider"]
        merged_model     = model     if model     is not None else existing["model"]
        merged_engine    = engine    if engine    is not None else existing["engine"]
        merged_meta      = {**existing["metadata"], **(metadata or {})}

        title   = self._generate_title(merged_messages)
        summary = self._generate_summary(merged_messages, merged_rtm, merged_provider, merged_meta)

        with self._lock, self._connect() as conn:
            conn.execute("""
                UPDATE sessions SET
                    title=?, summary=?, updated_at=?,
                    provider=?, model=?, engine=?,
                    messages=?, rtm_items=?, metadata=?
                WHERE id=?
            """, (
                title, summary, now,
                merged_provider, merged_model, merged_engine,
                json.dumps(merged_messages,  ensure_ascii=False),
                json.dumps(merged_rtm,       ensure_ascii=False),
                json.dumps(merged_meta,      ensure_ascii=False),
                session_id,
            ))
            conn.commit()

        return self.get_session(session_id)

    def get_session(self, session_id: str) -> Optional[dict]:
        if not self._ready:
            self.init()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._deserialize(dict(row)) if row else None

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if not self._ready:
            self.init()
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT id,title,summary,created_at,updated_at,provider,model,engine,metadata
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
        return [self._deserialize_light(dict(r)) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        if not self._ready:
            self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            conn.commit()
        return cur.rowcount > 0

    def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        if not self._ready:
            self.init()
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT id,title,summary,created_at,updated_at,provider,model,engine,metadata
                FROM sessions
                WHERE title LIKE ? OR summary LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
            """, (pattern, pattern, limit)).fetchall()
        return [self._deserialize_light(dict(r)) for r in rows]

    def count(self) -> int:
        if not self._ready:
            self.init()
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    # ── Serialization ──────────────────────────────────────────

    def _deserialize(self, row: dict) -> dict:
        """Full deserialization including messages and rtm_items."""
        return {
            "id":         row["id"],
            "title":      row["title"],
            "summary":    row["summary"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "provider":   row["provider"],
            "model":      row["model"],
            "engine":     row["engine"],
            "messages":   json.loads(row["messages"]  or "[]"),
            "rtm_items":  json.loads(row["rtm_items"] or "[]"),
            "metadata":   json.loads(row["metadata"]  or "{}"),
        }

    def _deserialize_light(self, row: dict) -> dict:
        """Light deserialization for list views (no messages/rtm content)."""
        meta = json.loads(row.get("metadata") or "{}")
        return {
            "id":         row["id"],
            "title":      row["title"],
            "summary":    row["summary"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "provider":   row["provider"],
            "model":      row["model"],
            "engine":     row["engine"],
            "msg_count":  meta.get("msg_count", 0),
            "ct_count":   meta.get("ct_count", 0),
            "rn_count":   meta.get("rn_count", 0),
            "cost_usd":   meta.get("cost_usd", 0.0),
            "tokens":     meta.get("tokens", 0),
        }

    # ── Title / Summary generation ─────────────────────────────

    @staticmethod
    def _generate_title(messages: list[dict]) -> str:
        """Extrai título da primeira mensagem do usuário."""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
                # Remove prefixos comuns
                for prefix in ["Como usuário", "Como ", "[User]:", "[User] "]:
                    if content.lower().startswith(prefix.lower()):
                        content = content[len(prefix):].strip()
                        break
                return content[:65] + ("…" if len(content) > 65 else "")
        return f"Sessão {datetime.utcnow().strftime('%d/%m %H:%M')}"

    @staticmethod
    def _generate_summary(
        messages: list[dict],
        rtm_items: list[dict],
        provider: str,
        metadata: dict,
    ) -> str:
        """Gera resumo automático da sessão."""
        parts = []
        msg_count = len([m for m in messages if m.get("role") == "user"])
        if msg_count:
            parts.append(f"{msg_count} turnos")

        ct_count = len(rtm_items)
        if ct_count:
            parts.append(f"{ct_count} CTs")

        rn_count = len(set(r.get("rn","") for r in rtm_items if r.get("rn")))
        if rn_count:
            parts.append(f"{rn_count} RNs")

        altos = len([r for r in rtm_items if "alto" in (r.get("risco","") or "").lower()])
        if altos:
            parts.append(f"⚠️ {altos} risco alto")

        if provider:
            parts.append(provider)

        cost = metadata.get("cost_usd", 0)
        if cost:
            parts.append(f"${cost:.4f}")

        return " · ".join(parts) if parts else "Sessão vazia"


# Singleton
session_manager = SessionManager()
