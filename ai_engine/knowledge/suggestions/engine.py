"""
ai_engine/knowledge/suggestions/engine.py
AQuA-QE LKDF v1.4 — Suggestion Engine

Gera sugestões preventivas para novos requisitos baseadas em:
  - Padrões aprendidos do histórico de defeitos (DefectPattern)
  - Memórias organizacionais de alta confiança
  - Análise semântica do texto do requisito
  - Domínio inferido do contexto

Integra com o CognitivePipeline como etapa pós-análise de requisito.
"""
from __future__ import annotations


import structlog

from ai_engine.knowledge.models import (
    MemoryEntry,
    MemoryType,
    PreventiveSuggestion,
    SuggestionType,
)
from ai_engine.knowledge.memory.store import OrganizationalMemoryStore

log = structlog.get_logger(__name__)


class SuggestionEngine:
    """
    Motor de sugestões preventivas baseado em memória organizacional.
    Consultado automaticamente pelo CognitivePipeline ao analisar um requisito.
    """

    def __init__(self, memory: OrganizationalMemoryStore) -> None:
        self._memory = memory

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    async def suggest_for_requirement(
        self,
        requirement_text: str,
        requirement_id:   str = "",
        domain:           str = "",
        min_confidence:   float = 0.40,
        max_suggestions:  int   = 8,
    ) -> list[PreventiveSuggestion]:
        """
        Gera sugestões preventivas para um novo requisito.
        Busca padrões relevantes na memória e cria sugestões ranqueadas.
        """
        log.info("suggestion_generate_start",
                 req_id=requirement_id, domain=domain or "inferred")

        suggestions: list[PreventiveSuggestion] = []

        # 1. Busca memórias relevantes por texto e domínio
        memories = await self._memory.search(
            query=requirement_text,
            min_confidence=min_confidence,
            limit=30,
        )

        if domain:
            domain_memories = await self._memory.find_by_domain(domain, limit=20)
            seen_ids = {str(m.id) for m in memories}
            memories += [m for m in domain_memories if str(m.id) not in seen_ids]

        # 2. Gera sugestão para cada memória relevante
        for memory in memories:
            if not self._is_relevant(memory, requirement_text):
                continue

            suggestion = self._memory_to_suggestion(
                memory, requirement_text, requirement_id
            )
            if suggestion:
                suggestions.append(suggestion)

        # 3. Ordena por confiança e prioridade
        suggestions = self._rank(suggestions)[:max_suggestions]

        log.info("suggestion_generate_done",
                 req_id=requirement_id,
                 suggestions=len(suggestions))
        return suggestions

    async def suggest_for_domain(
        self,
        domain:          str,
        requirement_id:  str   = "",
        max_suggestions: int   = 5,
    ) -> list[PreventiveSuggestion]:
        """Sugestões baseadas apenas no domínio, sem texto de requisito."""
        memories = await self._memory.find_by_domain(domain, limit=20)
        high_conf = [m for m in memories if m.confidence >= 0.60]

        suggestions = [
            s for s in [
                self._memory_to_suggestion(m, domain, requirement_id)
                for m in high_conf
            ]
            if s is not None
        ]
        return self._rank(suggestions)[:max_suggestions]

    async def top_patterns(self, limit: int = 5) -> list[PreventiveSuggestion]:
        """Retorna sugestões dos padrões mais frequentes e confiáveis."""
        memories = await self._memory.high_confidence(threshold=0.70, limit=limit * 2)
        suggestions = [
            s for s in [self._memory_to_suggestion(m, "", "") for m in memories]
            if s is not None
        ]
        return self._rank(suggestions)[:limit]

    # ------------------------------------------------------------------
    # Feedback integration
    # ------------------------------------------------------------------

    def accept(self, suggestion: PreventiveSuggestion) -> PreventiveSuggestion:
        suggestion.accept()
        log.info("suggestion_accepted", id=str(suggestion.id)[:8])
        return suggestion

    def reject(self, suggestion: PreventiveSuggestion) -> PreventiveSuggestion:
        suggestion.reject()
        log.info("suggestion_rejected", id=str(suggestion.id)[:8])
        return suggestion

    # ------------------------------------------------------------------
    # Builder helpers
    # ------------------------------------------------------------------

    def _memory_to_suggestion(
        self,
        memory:           MemoryEntry,
        requirement_text: str,
        requirement_id:   str,
    ) -> PreventiveSuggestion | None:
        """Converte MemoryEntry em PreventiveSuggestion."""
        if memory.memory_type == MemoryType.DEFECT_PATTERN:
            return self._from_defect_pattern(memory, requirement_text, requirement_id)
        if memory.memory_type == MemoryType.BEST_PRACTICE:
            return self._from_best_practice(memory, requirement_text, requirement_id)
        if memory.memory_type == MemoryType.ANTI_PATTERN:
            return self._from_anti_pattern(memory, requirement_text, requirement_id)
        if memory.memory_type == MemoryType.FAILURE_MODE:
            return self._from_failure_mode(memory, requirement_text, requirement_id)
        return None

    def _from_defect_pattern(
        self, memory: MemoryEntry, req_text: str, req_id: str
    ) -> PreventiveSuggestion:
        metadata     = memory.metadata or {}
        prevention   = metadata.get("prevention_steps", [])
        scenarios    = metadata.get("suggested_scenarios", [])
        risk_score   = metadata.get("risk_score", memory.confidence)
        avg_severity = metadata.get("avg_severity", "P1")
        priority     = "HIGH" if avg_severity == "P0" else ("MEDIUM" if avg_severity == "P1" else "LOW")

        return PreventiveSuggestion(
            suggestion_type=SuggestionType.RISK_WARNING,
            title=f"⚠ Padrão de risco: {memory.title}",
            description=memory.description,
            rationale=(
                f"Este padrão foi observado em {memory.frequency} defeito(s) histórico(s) "
                f"no domínio '{memory.domain}'. "
                f"Confiança: {memory.confidence:.0%}. "
                f"Severidade média: {avg_severity}."
            ),
            source_pattern=str(memory.id),
            target_story_id=req_id,
            confidence=memory.confidence,
            priority=priority,
            action_items=prevention[:4],
            scenarios=scenarios[:2],
            metadata={
                "memory_frequency": memory.frequency,
                "risk_score":       risk_score,
                "domain":           memory.domain,
                "avg_severity":     avg_severity,
            },
        )

    def _from_best_practice(
        self, memory: MemoryEntry, req_text: str, req_id: str
    ) -> PreventiveSuggestion:
        return PreventiveSuggestion(
            suggestion_type=SuggestionType.PATTERN_REUSE,
            title=f"✓ Boa prática aplicável: {memory.title}",
            description=memory.description,
            rationale=f"Prática validada com confiança {memory.confidence:.0%}.",
            source_pattern=str(memory.id),
            target_story_id=req_id,
            confidence=memory.confidence,
            priority="LOW",
            action_items=memory.metadata.get("steps", []),
            scenarios=[],
        )

    def _from_anti_pattern(
        self, memory: MemoryEntry, req_text: str, req_id: str
    ) -> PreventiveSuggestion:
        return PreventiveSuggestion(
            suggestion_type=SuggestionType.RISK_WARNING,
            title=f"✗ Anti-padrão detectado: {memory.title}",
            description=memory.description,
            rationale=f"Anti-padrão observado {memory.frequency}x. Evite esta abordagem.",
            source_pattern=str(memory.id),
            target_story_id=req_id,
            confidence=memory.confidence,
            priority="HIGH",
            action_items=memory.metadata.get("alternatives", []),
            scenarios=[],
        )

    def _from_failure_mode(
        self, memory: MemoryEntry, req_text: str, req_id: str
    ) -> PreventiveSuggestion:
        return PreventiveSuggestion(
            suggestion_type=SuggestionType.SCENARIO_ADDITION,
            title=f"Modo de falha: {memory.title}",
            description=memory.description,
            rationale=(
                "Modo de falha recorrente neste domínio. "
                "Adicione cenário de teste para cobrir este caminho."
            ),
            source_pattern=str(memory.id),
            target_story_id=req_id,
            confidence=memory.confidence,
            priority="MEDIUM",
            action_items=memory.metadata.get("mitigation", []),
            scenarios=memory.metadata.get("test_scenarios", []),
        )

    # ------------------------------------------------------------------
    # Relevance check
    # ------------------------------------------------------------------

    @staticmethod
    def _is_relevant(memory: MemoryEntry, text: str) -> bool:
        """Verifica relevância semântica simples por tags e domínio."""
        text_lower = text.lower()
        if memory.domain and memory.domain.lower() in text_lower:
            return True
        for tag in memory.tags:
            if tag.lower() in text_lower:
                return True
        # Title similarity
        title_words = memory.title.lower().split("_")
        return any(w in text_lower for w in title_words if len(w) > 4)

    @staticmethod
    def _rank(suggestions: list[PreventiveSuggestion]) -> list[PreventiveSuggestion]:
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        return sorted(
            suggestions,
            key=lambda s: (priority_order.get(s.priority, 1), -s.confidence),
        )
