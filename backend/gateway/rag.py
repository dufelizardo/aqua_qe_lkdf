"""
AQuA-QE LKDF — RAG Architecture §32
Recuperação Semântica Contextual — 100% offline, sem dependências externas.

Estratégia:
  - TF-IDF + bigramas para representação vetorial dos documentos
  - Cosine similarity para ranking de relevância
  - Índice persistido em SQLite (via knowledge.db já existente)
  - Augmentation: injeta contexto relevante no prompt antes do LLM
  - Auto-indexa todo item adicionado ao Knowledge Layer

Evolução futura:
  - Substituir TF-IDF por sentence-transformers quando disponível
  - Migrar para Qdrant/Weaviate para escala (§33)
  - Adicionar BM25 híbrido para recall melhor
"""
from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter, defaultdict
from typing import Optional


# ── Tokenizer ────────────────────────────────────────────────

_STOPWORDS_PT = {
    "a","as","ao","aos","à","às","de","do","da","dos","das","em","no","na",
    "nos","nas","um","uma","uns","umas","o","os","e","é","que","se","com",
    "por","para","como","mais","mas","ou","não","seu","sua","seus","suas",
    "ele","ela","eles","elas","isso","este","esta","um","uma","ter","ser",
    "foi","são","está","este","essa","esse","quando","então","dado","quando",
    "deve","deve","todo","toda","todos","todas","pode","pode","entre",
}

def tokenize(text: str) -> list[str]:
    """Tokeniza texto em português, removendo stopwords."""
    text  = text.lower()
    text  = re.sub(r'[^\w\sáàâãéèêíïóôõúü]', ' ', text)
    words = [w for w in text.split() if len(w) > 2 and w not in _STOPWORDS_PT]
    # Add bigrams for better phrase matching
    bigrams = [f"{words[i]}_{words[i+1]}" for i in range(len(words)-1)]
    return words + bigrams


# ── TF-IDF Vector Store ───────────────────────────────────────

class TFIDFVectorStore:
    """
    Vector store local usando TF-IDF.
    Suporta adição incremental de documentos e busca por similaridade.
    """

    def __init__(self):
        self._lock       = threading.Lock()
        self._docs:     list[dict]          = []   # {id, text, metadata}
        self._tf:       list[dict[str,float]] = []  # TF por documento
        self._df:       dict[str, int]      = defaultdict(int)  # DF global
        self._vocab:    dict[str, int]      = {}   # token → index
        self._n_docs    = 0

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        """Adiciona documento ao índice."""
        with self._lock:
            # Check duplicate
            if any(d["id"] == doc_id for d in self._docs):
                return
            tokens = tokenize(text)
            if not tokens:
                return
            # TF
            tf: dict[str, float] = {}
            counts = Counter(tokens)
            total  = sum(counts.values())
            for tok, cnt in counts.items():
                tf[tok] = cnt / total
                # Update vocab
                if tok not in self._vocab:
                    self._vocab[tok] = len(self._vocab)
            # DF
            for tok in set(tokens):
                self._df[tok] += 1

            self._docs.append({"id": doc_id, "text": text[:500], "metadata": metadata or {}})
            self._tf.append(tf)
            self._n_docs += 1

    def search(self, query: str, top_k: int = 5, min_score: float = 0.01) -> list[dict]:
        """
        Busca documentos mais relevantes para a query.
        Retorna lista de { id, text, metadata, score }.
        """
        with self._lock:
            if not self._docs:
                return []
            q_tokens = tokenize(query)
            if not q_tokens:
                return []

            # TF-IDF para a query
            q_counts = Counter(q_tokens)
            q_total  = sum(q_counts.values())
            q_tf     = {tok: cnt/q_total for tok, cnt in q_counts.items()}

            # IDF global
            N = max(self._n_docs, 1)
            idf = {tok: math.log((N+1) / (self._df.get(tok, 0)+1)) + 1
                   for tok in q_tf}

            # Score por documento (dot product dos TF-IDF vectors)
            scores = []
            for i, doc_tf in enumerate(self._tf):
                score = 0.0
                q_norm = sum((q_tf[t]*idf.get(t,1))**2 for t in q_tf) ** 0.5
                d_norm = sum((v * idf.get(t,1))**2 for t,v in doc_tf.items()) ** 0.5
                if q_norm == 0 or d_norm == 0:
                    scores.append(0.0)
                    continue
                for tok in q_tf:
                    if tok in doc_tf:
                        score += (q_tf[tok] * idf.get(tok,1)) * (doc_tf[tok] * idf.get(tok,1))
                scores.append(score / (q_norm * d_norm))

            # Rank
            ranked = sorted(
                [(i, s) for i, s in enumerate(scores) if s >= min_score],
                key=lambda x: -x[1]
            )
            return [
                {**self._docs[i], "score": round(scores[i], 4)}
                for i, _ in ranked[:top_k]
            ]

    def size(self) -> int:
        with self._lock:
            return self._n_docs

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()
            self._tf.clear()
            self._df.clear()
            self._vocab.clear()
            self._n_docs = 0


# ── RAG Engine ────────────────────────────────────────────────

class RAGEngine:
    """
    Retrieval-Augmented Generation para o AQuA-QE LKDF.

    Fluxo:
      1. retrieve(query) → top-k documentos relevantes do Knowledge Layer
      2. augment(query, context) → prompt enriquecido com contexto
      3. O prompt aumentado é enviado ao LLM via gateway normal

    Índices separados por tipo de documento:
      - "knowledge" → RNs, CAs, padrões, insights do Knowledge Layer
      - "sessions"  → histórico de conversas
      - "stories"   → histórias salvas no Story Engineering
    """

    def __init__(self):
        self._indices: dict[str, TFIDFVectorStore] = {
            "knowledge": TFIDFVectorStore(),
            "sessions":  TFIDFVectorStore(),
            "stories":   TFIDFVectorStore(),
        }
        self._lock   = threading.Lock()
        self._stats  = {"queries": 0, "indexed": 0, "hits": 0}

    # ── Indexing ──────────────────────────────────────────────

    def index_knowledge_item(self, item: dict) -> None:
        """Indexa item do Knowledge Layer."""
        text = f"{item.get('title','')} {item.get('content','')} {' '.join(item.get('tags',[]))}"
        self._indices["knowledge"].add(
            doc_id=item.get("id", ""),
            text=text,
            metadata={
                "type":       item.get("type", ""),
                "title":      item.get("title", ""),
                "story_name": item.get("story_name", ""),
                "tags":       item.get("tags", []),
                "frequency":  item.get("frequency", 1),
            }
        )
        with self._lock:
            self._stats["indexed"] += 1

    def index_session(self, session: dict) -> None:
        """Indexa sessão de chat."""
        msgs     = session.get("messages", [])
        user_msgs = " ".join(m.get("content","") for m in msgs if m.get("role")=="user")
        text = f"{session.get('title','')} {user_msgs}"
        self._indices["sessions"].add(
            doc_id=session.get("id",""),
            text=text[:1000],
            metadata={
                "title":    session.get("title",""),
                "provider": session.get("provider",""),
                "ct_count": session.get("metadata",{}).get("ct_count",0),
            }
        )
        with self._lock:
            self._stats["indexed"] += 1

    def index_story(self, story_id: str, story_name: str, content: str,
                    rns: list[dict], cas: list[dict]) -> None:
        """Indexa história do Story Engineering."""
        rn_text = " ".join(f"{r.get('id','')} {r.get('text','')}" for r in rns)
        ca_text = " ".join(f"{c.get('id','')} {c.get('text','')}" for c in cas)
        text = f"{story_name} {content[:400]} {rn_text} {ca_text}"
        self._indices["stories"].add(
            doc_id=story_id,
            text=text,
            metadata={"story_name": story_name, "rn_count": len(rns), "ca_count": len(cas)}
        )
        with self._lock:
            self._stats["indexed"] += 1

    def bulk_index_knowledge(self, items: list[dict]) -> int:
        """Indexa lista de itens do Knowledge Layer em lote."""
        for item in items:
            self.index_knowledge_item(item)
        return len(items)

    # ── Retrieval ─────────────────────────────────────────────

    def retrieve(
        self,
        query:      str,
        index:      str = "knowledge",
        top_k:      int = 5,
        min_score:  float = 0.05,
        type_filter: str = "",
    ) -> list[dict]:
        """
        Busca documentos relevantes.
        Retorna lista ranqueada com score de relevância.
        """
        with self._lock:
            self._stats["queries"] += 1

        store = self._indices.get(index, self._indices["knowledge"])
        results = store.search(query, top_k=top_k*2, min_score=min_score)

        # Filter by type if specified
        if type_filter:
            results = [r for r in results if r.get("metadata",{}).get("type") == type_filter]

        results = results[:top_k]

        if results:
            with self._lock:
                self._stats["hits"] += 1

        return results

    def retrieve_multi(self, query: str, top_k: int = 3) -> dict[str, list]:
        """Busca em todos os índices simultaneamente."""
        return {
            idx: self.retrieve(query, index=idx, top_k=top_k)
            for idx in self._indices
        }

    # ── Augmentation ──────────────────────────────────────────

    def build_context(self, results: list[dict], max_chars: int = 2000) -> str:
        """Constrói bloco de contexto para injetar no prompt."""
        if not results:
            return ""
        lines = ["=== CONTEXTO RELEVANTE DO KNOWLEDGE LAYER ==="]
        total = 0
        for i, r in enumerate(results, 1):
            meta  = r.get("metadata", {})
            title = meta.get("title", r.get("text","")[:60])
            itype = meta.get("type","")
            score = r.get("score", 0)
            entry = f"\n[{i}] {itype.upper() if itype else 'DOC'} (relevância: {score:.2f})\n{title}\n{r.get('text','')[:300]}"
            if total + len(entry) > max_chars:
                break
            lines.append(entry)
            total += len(entry)
        lines.append("\n=== FIM DO CONTEXTO ===")
        return "\n".join(lines)

    def augment_prompt(
        self,
        user_query:   str,
        system_prompt: str = "",
        index:        str = "knowledge",
        top_k:        int = 4,
        min_score:    float = 0.05,
    ) -> tuple[str, list[dict]]:
        """
        Recupera contexto e injeta no system prompt.
        Retorna: (system_prompt_aumentado, fontes_usadas)
        """
        results = self.retrieve(user_query, index=index, top_k=top_k, min_score=min_score)
        if not results:
            return system_prompt, []

        context = self.build_context(results)
        augmented = f"{system_prompt}\n\n{context}" if system_prompt else context
        return augmented, results

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            s = dict(self._stats)
        return {
            **s,
            "indices": {
                name: store.size()
                for name, store in self._indices.items()
            },
            "hit_rate": round(s["hits"] / max(s["queries"], 1) * 100, 1),
        }

    def clear_index(self, index: str = "") -> None:
        """Limpa índice(s). Se index='', limpa todos."""
        if index and index in self._indices:
            self._indices[index].clear()
        else:
            for store in self._indices.values():
                store.clear()
        with self._lock:
            self._stats["indexed"] = 0


# ── Singleton ────────────────────────────────────────────────
rag_engine = RAGEngine()


# ── Bootstrap: pre-index Knowledge Layer items ───────────────

def bootstrap_from_knowledge(knowledge_mgr) -> int:
    """
    Indexa todos os itens existentes no Knowledge Layer ao iniciar.
    Chamado no startup do gateway.
    """
    try:
        items = knowledge_mgr.list(limit=500)
        return rag_engine.bulk_index_knowledge(items)
    except Exception as e:
        print(f"[RAG] Bootstrap warning: {e}")
        return 0
