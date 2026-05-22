"""
ai_engine/knowledge/memory/store.py
AQuA-QE LKDF v1.4 — Organizational Memory Store

Responsável por:
  - Persistir MemoryEntries no GraphRepository
  - Busca semântica por intenção (LIKE no SQLite, vector no Neo4j)
  - Reforço e decaimento de memórias (reinforcement learning simples)
  - Deduplicação por similaridade de título/tags
  - Snapshot periódico para auditoria
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from ai_engine.knowledge.models import (
    ConfidenceLevel,
    MemoryEntry,
    MemoryType,
)
from runtime_core.persistence.graph.models import Node, RelationType
from runtime_core.persistence.graph.repository import GraphRepository

log = structlog.get_logger(__name__)


class OrganizationalMemoryStore:
    """
    Store de memória organizacional sobre GraphRepository.
    Opera sobre Nodes com label "KnowledgeMemory".
    """

    _LABEL = "KnowledgeMemory"

    def __init__(self, repository: GraphRepository) -> None:
        self._repo    = repository
        self._cache:  dict[str, MemoryEntry] = {}   # id → entry

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def store(self, entry: MemoryEntry) -> MemoryEntry:
        """Persiste ou atualiza uma MemoryEntry."""
        existing = await self._find_similar(entry)
        if existing:
            existing.reinforce(
                source_id=entry.source_ids[0] if entry.source_ids else ""
            )
            return await self._update(existing)

        return await self._create(entry)

    async def store_many(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        for entry in entries:
            results.append(await self.store(entry))
        return results

    async def reinforce(self, entry_id: str, source_id: str = "") -> MemoryEntry | None:
        """Reforça uma memória existente ao observar o padrão novamente."""
        entry = await self.get(entry_id)
        if not entry:
            return None
        entry.reinforce(source_id)
        return await self._update(entry)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get(self, entry_id: str) -> MemoryEntry | None:
        if entry_id in self._cache:
            return self._cache[entry_id]
        node = await self._repo.get_node_by_external_id(entry_id, self._LABEL)
        if not node:
            return None
        entry = self._node_to_entry(node)
        self._cache[str(entry.id)] = entry
        return entry

    async def search(
        self,
        query:       str,
        memory_type: MemoryType | None = None,
        domain:      str | None        = None,
        min_confidence: float          = 0.0,
        limit:       int               = 10,
    ) -> list[MemoryEntry]:
        """
        Busca memórias por query semântica.
        SQLite: LIKE search. Neo4j: vector similarity.
        """
        nodes = await self._repo.find_by_intent(query, limit=limit * 3)

        entries: list[MemoryEntry] = []
        for node in nodes:
            if node.label != self._LABEL:
                continue
            entry = self._node_to_entry(node)
            if memory_type and entry.memory_type != memory_type:
                continue
            if domain and entry.domain and domain.lower() not in entry.domain.lower():
                continue
            if entry.confidence < min_confidence:
                continue
            entries.append(entry)

        entries.sort(key=lambda e: (e.confidence, e.frequency), reverse=True)
        return entries[:limit]

    async def find_by_type(
        self,
        memory_type: MemoryType,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        nodes = await self._repo.find_nodes(
            label=self._LABEL,
            properties={"memory_type": memory_type.value},
            limit=limit,
        )
        return [self._node_to_entry(n) for n in nodes]

    async def find_by_domain(self, domain: str, limit: int = 20) -> list[MemoryEntry]:
        nodes = await self._repo.find_by_intent(domain, limit=limit * 2)
        entries = [
            self._node_to_entry(n) for n in nodes
            if n.label == self._LABEL
            and domain.lower() in n.properties.get("domain", "").lower()
        ]
        return entries[:limit]

    async def most_frequent(self, limit: int = 10) -> list[MemoryEntry]:
        nodes = await self._repo.find_nodes(label=self._LABEL, limit=200)
        entries = sorted(
            [self._node_to_entry(n) for n in nodes],
            key=lambda e: (e.frequency, e.confidence),
            reverse=True,
        )
        return entries[:limit]

    async def high_confidence(
        self, threshold: float = 0.75, limit: int = 20
    ) -> list[MemoryEntry]:
        nodes  = await self._repo.find_nodes(label=self._LABEL, limit=500)
        entries = [
            self._node_to_entry(n) for n in nodes
            if n.properties.get("confidence", 0.0) >= threshold
        ]
        entries.sort(key=lambda e: e.confidence, reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        nodes   = await self._repo.find_nodes(label=self._LABEL, limit=10000)
        entries = [self._node_to_entry(n) for n in nodes]

        by_type: dict[str, int] = {}
        for e in entries:
            by_type[e.memory_type.value] = by_type.get(e.memory_type.value, 0) + 1

        confidences = [e.confidence for e in entries]
        avg_conf    = sum(confidences) / len(confidences) if confidences else 0.0
        total_freq  = sum(e.frequency for e in entries)

        return {
            "total_entries":  len(entries),
            "by_type":        by_type,
            "avg_confidence": round(avg_conf, 3),
            "total_frequency": total_freq,
            "high_confidence": sum(1 for e in entries if e.confidence >= 0.75),
            "domains":         list({e.domain for e in entries if e.domain}),
        }

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _create(self, entry: MemoryEntry) -> MemoryEntry:
        node = self._entry_to_node(entry)
        saved = await self._repo.add_node(node)
        entry.id = saved.id
        self._cache[str(entry.id)] = entry
        log.debug("memory_stored", type=entry.memory_type.value,
                  title=entry.title[:40], confidence=entry.confidence)
        return entry

    async def _update(self, entry: MemoryEntry) -> MemoryEntry:
        node = await self._repo.get_node_by_external_id(
            str(entry.id), self._LABEL
        )
        if node:
            node.properties.update(self._entry_props(entry))
            node.updated_at = datetime.utcnow()
            await self._repo.update_node(node)
        self._cache[str(entry.id)] = entry
        log.debug("memory_reinforced", id=str(entry.id)[:8],
                  frequency=entry.frequency, confidence=round(entry.confidence, 2))
        return entry

    async def _find_similar(self, entry: MemoryEntry) -> MemoryEntry | None:
        """Busca memória similar por título + tipo para evitar duplicatas."""
        candidates = await self._repo.find_nodes(
            label=self._LABEL,
            properties={"memory_type": entry.memory_type.value},
            limit=50,
        )
        for node in candidates:
            existing_title = node.properties.get("title", "").lower()
            new_title      = entry.title.lower()
            if (
                existing_title == new_title
                or self._similarity(existing_title, new_title) > 0.85
            ):
                return self._node_to_entry(node)
        return None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _entry_to_node(self, entry: MemoryEntry) -> Node:
        return Node(
            id=entry.id,
            label=self._LABEL,
            external_id=str(entry.id),
            properties=self._entry_props(entry),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    @staticmethod
    def _entry_props(entry: MemoryEntry) -> dict[str, Any]:
        return {
            "memory_type":  entry.memory_type.value,
            "title":        entry.title,
            "description":  entry.description,
            "source_ids":   json.dumps(entry.source_ids),
            "tags":         json.dumps(entry.tags),
            "frequency":    entry.frequency,
            "confidence":   entry.confidence,
            "domain":       entry.domain,
            "last_seen_at": entry.last_seen_at.isoformat(),
        }

    @staticmethod
    def _node_to_entry(node: Node) -> MemoryEntry:
        p = node.properties
        return MemoryEntry(
            id=node.id,
            memory_type=MemoryType(p.get("memory_type", MemoryType.DEFECT_PATTERN.value)),
            title=p.get("title", ""),
            description=p.get("description", ""),
            source_ids=json.loads(p.get("source_ids", "[]")),
            tags=json.loads(p.get("tags", "[]")),
            frequency=int(p.get("frequency", 1)),
            confidence=float(p.get("confidence", 0.5)),
            domain=p.get("domain", ""),
            created_at=node.created_at,
            updated_at=node.updated_at,
            last_seen_at=datetime.fromisoformat(
                p.get("last_seen_at", node.updated_at.isoformat())
            ),
        )

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Similaridade simples por bigramas."""
        def bigrams(s: str) -> set[str]:
            return {s[i:i+2] for i in range(len(s) - 1)}
        ba, bb = bigrams(a), bigrams(b)
        if not ba or not bb:
            return 0.0
        return len(ba & bb) / len(ba | bb)
