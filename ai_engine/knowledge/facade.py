"""
ai_engine/knowledge/facade.py
AQuA-QE LKDF v1.4 — Knowledge Layer Facade

Ponto de entrada unificado para todas as operações do Knowledge Layer.
Orquestra Memory Store, Learning Engine, Suggestion Engine e Ontology.

Uso típico no CognitivePipeline:
    knowledge = KnowledgeFacade(repository)
    await knowledge.initialize_seeds()

    # Ao registrar um defeito:
    await knowledge.learn_from_defect(DefectRecord(...))

    # Ao analisar um novo requisito:
    suggestions = await knowledge.suggest_for("Login deve ser autenticado", req_id="REQ-001")

    # Ao receber feedback:
    await knowledge.accept_suggestion(suggestion)
"""
from __future__ import annotations

from typing import Any

import structlog

from ai_engine.knowledge.learning.engine import DefectRecord, LearningEngine
from ai_engine.knowledge.memory.store import OrganizationalMemoryStore
from ai_engine.knowledge.models import (
    DefectPattern,
    MemoryEntry,
    MemoryType,
    PreventiveSuggestion,
    SuggestionType,
)
from ai_engine.knowledge.ontology.registry import OntologyNode, OntologyRegistry, get_ontology
from ai_engine.knowledge.suggestions.engine import SuggestionEngine
from runtime_core.persistence.graph.repository import GraphRepository

log = structlog.get_logger(__name__)


class KnowledgeFacade:
    """
    Facade do Knowledge Layer.
    API pública usada pelo CognitivePipeline e pela API REST.
    """

    def __init__(self, repository: GraphRepository) -> None:
        self._memory     = OrganizationalMemoryStore(repository)
        self._learning   = LearningEngine(self._memory)
        self._suggestion = SuggestionEngine(self._memory)
        self._ontology   = get_ontology()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize_seeds(self, domain_seeds: list[MemoryEntry] | None = None) -> None:
        """
        Inicializa a base de conhecimento com seeds de domínio.
        Chamado uma vez na inicialização do sistema.
        """
        seeds = domain_seeds or self._default_seeds()
        for seed in seeds:
            await self._memory.store(seed)
        log.info("knowledge_seeds_initialized", count=len(seeds))

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    async def learn_from_defect(self, defect: DefectRecord) -> list[DefectPattern]:
        """Aprende de um único defeito. Retorna padrões extraídos."""
        return await self._learning.learn_from_single_defect(defect)

    async def learn_from_defects(self, defects: list[DefectRecord]) -> list[DefectPattern]:
        """Aprende de múltiplos defeitos em batch."""
        return await self._learning.learn_from_defects(defects)

    async def store_memory(self, entry: MemoryEntry) -> MemoryEntry:
        """Persiste uma MemoryEntry diretamente."""
        return await self._memory.store(entry)

    # ------------------------------------------------------------------
    # Suggestions
    # ------------------------------------------------------------------

    async def suggest_for(
        self,
        requirement_text: str,
        requirement_id:   str   = "",
        domain:           str   = "",
        max_suggestions:  int   = 6,
    ) -> list[PreventiveSuggestion]:
        """
        Gera sugestões preventivas para um novo requisito.
        Ponto de entrada principal para integração com o pipeline.
        """
        # Infer domain from ontology if not provided
        if not domain:
            domain = self._ontology.infer_domain(requirement_text)

        suggestions = await self._suggestion.suggest_for_requirement(
            requirement_text=requirement_text,
            requirement_id=requirement_id,
            domain=domain,
            max_suggestions=max_suggestions,
        )
        return suggestions

    async def top_patterns(self, limit: int = 5) -> list[PreventiveSuggestion]:
        """Retorna os padrões mais relevantes da base de conhecimento."""
        return await self._suggestion.top_patterns(limit)

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    async def accept_suggestion(
        self,
        suggestion: PreventiveSuggestion,
    ) -> PreventiveSuggestion:
        """Aceita uma sugestão — reforça o padrão de origem."""
        accepted = self._suggestion.accept(suggestion)
        if suggestion.source_pattern:
            await self._learning.feedback_accepted(
                str(suggestion.id), suggestion.source_pattern
            )
        return accepted

    async def reject_suggestion(
        self,
        suggestion: PreventiveSuggestion,
    ) -> PreventiveSuggestion:
        """Rejeita uma sugestão — decai a confiança do padrão."""
        rejected = self._suggestion.reject(suggestion)
        if suggestion.source_pattern:
            await self._learning.feedback_rejected(
                str(suggestion.id), suggestion.source_pattern
            )
        return rejected

    # ------------------------------------------------------------------
    # Ontology
    # ------------------------------------------------------------------

    def enrich_with_ontology(self, text: str) -> dict[str, Any]:
        """Enriquece um texto com conceitos do domínio."""
        matched = self._ontology.match_in_text(text)
        domain  = self._ontology.infer_domain(text)
        related = []
        for node in matched[:3]:
            related.extend(self._ontology.related_to(node.concept))

        return {
            "domain":          domain,
            "concepts_found":  [n.concept for n in matched],
            "related_concepts": list({n.concept for n in related}),
            "concept_count":   len(matched),
        }

    def register_concept(self, node: OntologyNode) -> None:
        self._ontology.register(node)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def search_memories(
        self,
        query:       str,
        memory_type: MemoryType | None = None,
        domain:      str | None        = None,
        limit:       int               = 10,
    ) -> list[MemoryEntry]:
        return await self._memory.search(query, memory_type, domain, limit=limit)

    async def knowledge_stats(self) -> dict[str, Any]:
        mem_stats = await self._memory.stats()
        ontology_concepts = len(self._ontology.all_concepts())
        return {
            **mem_stats,
            "ontology_concepts": ontology_concepts,
            "domains_in_ontology": list({
                n.domain for n in self._ontology.all_concepts() if n.domain
            }),
        }

    # ------------------------------------------------------------------
    # Default seeds
    # ------------------------------------------------------------------

    @staticmethod
    def _default_seeds() -> list[MemoryEntry]:
        """
        Seeds iniciais de conhecimento para novos ambientes.
        Cobre os padrões de defeito mais comuns por domínio.
        """
        return [
            MemoryEntry(
                memory_type=MemoryType.DEFECT_PATTERN,
                title="Authentication_TokenExpiration",
                description="Token JWT expira durante sessão ativa sem tratamento adequado.",
                tags=["authentication", "jwt", "token", "session"],
                frequency=8,
                confidence=0.90,
                domain="authentication",
                metadata={
                    "trigger_keywords": ["login", "token", "jwt", "sessão"],
                    "prevention_steps": [
                        "Adicionar cenário de token expirado durante navegação",
                        "Implementar refresh token automático",
                        "Testar redirecionamento após expiração",
                    ],
                    "suggested_scenarios": [
                        "Dado que o token JWT expirou\nQuando o usuário faz requisição autenticada\nEntão é esperado que receba 401 e seja redirecionado ao login",
                    ],
                    "avg_severity": "P1",
                    "risk_score": 0.72,
                },
            ),
            MemoryEntry(
                memory_type=MemoryType.DEFECT_PATTERN,
                title="Payments_GatewayTimeout",
                description="Timeout no gateway de pagamento sem tratamento de estado parcial.",
                tags=["payments", "gateway", "timeout", "idempotency"],
                frequency=5,
                confidence=0.85,
                domain="payments",
                metadata={
                    "trigger_keywords": ["pagamento", "gateway", "checkout", "cobrança"],
                    "prevention_steps": [
                        "Implementar idempotency key em todas as cobranças",
                        "Adicionar timeout explícito com fallback",
                        "Testar comportamento em gateway indisponível",
                    ],
                    "suggested_scenarios": [
                        "Dado que o gateway está indisponível\nQuando o usuário tenta pagar\nEntão é esperado que receba erro amigável e o pedido não seja criado",
                    ],
                    "avg_severity": "P0",
                    "risk_score": 0.85,
                },
            ),
            MemoryEntry(
                memory_type=MemoryType.DEFECT_PATTERN,
                title="Authorization_DirectURLAccess",
                description="Acesso direto a URLs protegidas sem autenticação não é bloqueado.",
                tags=["authorization", "security", "url", "redirect"],
                frequency=12,
                confidence=0.95,
                domain="authorization",
                metadata={
                    "trigger_keywords": ["acesso", "permissão", "dashboard", "protegido", "role"],
                    "prevention_steps": [
                        "Testar acesso direto a todas as rotas protegidas sem token",
                        "Verificar que usuário é redirecionado ao login",
                        "Testar acesso cross-user (usuário A acessando recurso de usuário B)",
                    ],
                    "suggested_scenarios": [
                        "Dado que o usuário não está autenticado\nQuando acessa /dashboard diretamente\nEntão é esperado que seja redirecionado para /login",
                    ],
                    "avg_severity": "P0",
                    "risk_score": 0.95,
                },
            ),
            MemoryEntry(
                memory_type=MemoryType.BEST_PRACTICE,
                title="Forms_InlineValidation",
                description="Validação inline em tempo real melhora UX e previne erros de submissão.",
                tags=["forms", "validation", "ux", "best-practice"],
                frequency=15,
                confidence=0.88,
                domain="forms",
                metadata={
                    "steps": [
                        "Validar campos em tempo real (onChange)",
                        "Mostrar mensagem de erro próxima ao campo",
                        "Desabilitar submit até formulário válido",
                        "Indicar campos obrigatórios com asterisco",
                    ],
                },
            ),
            MemoryEntry(
                memory_type=MemoryType.FAILURE_MODE,
                title="API_ConcurrentRequests",
                description="Requisições concorrentes ao mesmo endpoint sem controle de concorrência.",
                tags=["api", "concurrent", "race-condition", "idempotency"],
                frequency=6,
                confidence=0.75,
                domain="api",
                metadata={
                    "mitigation": [
                        "Implementar locks otimistas no banco",
                        "Usar idempotency keys em operações críticas",
                        "Adicionar testes de carga com requisições simultâneas",
                    ],
                    "test_scenarios": [
                        "Dado que dois usuários acessam o mesmo recurso simultaneamente\nQuando ambos tentam modificá-lo\nEntão é esperado que apenas uma operação seja bem-sucedida",
                    ],
                },
            ),
        ]
