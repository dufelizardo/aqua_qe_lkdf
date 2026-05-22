"""
ai_engine/knowledge/learning/engine.py
AQuA-QE LKDF v1.4 — Learning Engine

Responsável por:
  - Extrair DefectPatterns de histórico de defeitos reais
  - Identificar padrões recorrentes por domínio e keyword
  - Reforçar memórias existentes ao observar novos defeitos
  - Calcular risk_score por padrão para priorizar sugestões
  - Aprender de feedback (sugestões aceitas/rejeitadas)
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from ai_engine.knowledge.models import (
    DefectPattern,
    MemoryEntry,
    MemoryType,
)
from ai_engine.knowledge.memory.store import OrganizationalMemoryStore

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Defect input contract
# ---------------------------------------------------------------------------

@dataclass
class DefectRecord:
    """Registro de defeito histórico para aprendizado."""
    id:          str
    title:       str
    description: str
    severity:    str             = "P1"       # P0 / P1 / P2
    domain:      str             = ""         # authentication / payments / ui...
    story_id:    str             = ""
    keywords:    list[str]       = field(default_factory=list)
    resolved_at: datetime | None = None
    root_cause:  str             = ""
    metadata:    dict[str, Any]  = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Learning Engine
# ---------------------------------------------------------------------------

class LearningEngine:
    """
    Motor de aprendizado organizacional.
    Transforma histórico de defeitos em padrões reutilizáveis.
    """

    # Keyword clusters por domínio — ampliam o matching
    _DOMAIN_KEYWORDS: dict[str, list[str]] = {
        "authentication": [
            "login", "logout", "senha", "token", "jwt", "oauth",
            "autenticação", "sessão", "session", "credenciais", "2fa",
        ],
        "payments": [
            "pagamento", "payment", "cobrança", "checkout", "cartão",
            "card", "pix", "boleto", "refund", "estorno", "gateway",
        ],
        "authorization": [
            "permissão", "permission", "role", "acesso", "autorização",
            "forbidden", "403", "unauthorized", "401", "rbac",
        ],
        "forms": [
            "formulário", "form", "campo", "input", "validação",
            "validation", "submit", "obrigatório", "required",
        ],
        "ui": [
            "interface", "tela", "botão", "button", "menu", "navegação",
            "layout", "responsivo", "responsive", "display",
        ],
        "api": [
            "api", "endpoint", "rest", "graphql", "request", "response",
            "timeout", "rate limit", "json", "payload",
        ],
        "data": [
            "banco", "database", "query", "sql", "migração", "migration",
            "dados", "data", "integrity", "constraint",
        ],
    }

    def __init__(self, memory: OrganizationalMemoryStore) -> None:
        self._memory  = memory
        self._patterns: list[DefectPattern] = []

    # ------------------------------------------------------------------
    # Main learning loop
    # ------------------------------------------------------------------

    async def learn_from_defects(
        self, defects: list[DefectRecord]
    ) -> list[DefectPattern]:
        """
        Processa lista de defeitos históricos e extrai padrões.
        Persiste cada padrão como MemoryEntry no grafo.
        """
        log.info("learning_start", defects=len(defects))

        # 1. Extrair padrões por domínio e keywords
        raw_patterns = self._extract_patterns(defects)

        # 2. Consolidar padrões similares
        consolidated = self._consolidate(raw_patterns)

        # 3. Persistir como MemoryEntry
        for pattern in consolidated:
            entry = self._pattern_to_memory(pattern)
            await self._memory.store(entry)

        self._patterns.extend(consolidated)

        log.info("learning_done",
                 defects=len(defects),
                 patterns_extracted=len(consolidated))
        return consolidated

    async def learn_from_single_defect(
        self, defect: DefectRecord
    ) -> list[DefectPattern]:
        """Aprende de um único defeito — reforça padrões existentes ou cria novos."""
        return await self.learn_from_defects([defect])

    async def feedback_accepted(self, suggestion_id: str, pattern_id: str) -> None:
        """Reforça padrão quando sugestão é aceita pelo usuário."""
        await self._memory.reinforce(pattern_id, source_id=f"feedback:{suggestion_id}")
        log.info("feedback_accepted_reinforced", pattern_id=pattern_id)

    async def feedback_rejected(self, suggestion_id: str, pattern_id: str) -> None:
        """Decai confiança quando sugestão é rejeitada."""
        entry = await self._memory.get(pattern_id)
        if entry:
            entry.decay(factor=0.10)
            # Use _update directly to avoid reinforce in store()
            await self._memory._update(entry)
        log.info("feedback_rejected_decay", pattern_id=pattern_id)

    # ------------------------------------------------------------------
    # Pattern extraction
    # ------------------------------------------------------------------

    def _extract_patterns(
        self, defects: list[DefectRecord]
    ) -> list[DefectPattern]:
        patterns: list[DefectPattern] = []

        # Group by domain
        by_domain: dict[str, list[DefectRecord]] = {}
        for d in defects:
            domain = d.domain or self._infer_domain(d.title + " " + d.description)
            by_domain.setdefault(domain, []).append(d)

        for domain, domain_defects in by_domain.items():
            # Extract keyword frequency
            all_text   = " ".join(
                f"{d.title} {d.description} {d.root_cause}".lower()
                for d in domain_defects
            )
            keywords   = self._extract_keywords(all_text, domain)
            severities = [d.severity for d in domain_defects]
            avg_sev    = self._avg_severity(severities)
            confidence = min(1.0, len(domain_defects) / 5.0 * 0.5 + 0.3)

            if not keywords:
                continue

            prevention = self._prevention_steps(domain, keywords)
            scenarios  = self._suggested_scenarios(domain, keywords)

            pattern = DefectPattern(
                pattern_name=f"{domain.title()}_{keywords[0].replace(' ', '_').title()}",
                description=self._pattern_description(domain, keywords, domain_defects),
                trigger_keywords=keywords[:5],
                trigger_domains=[domain],
                defect_ids=[d.id for d in domain_defects],
                occurrences=len(domain_defects),
                avg_severity=avg_sev,
                prevention_steps=prevention,
                suggested_scenarios=scenarios,
                confidence=confidence,
                domain=domain,
            )
            patterns.append(pattern)

        return patterns

    def _consolidate(
        self, patterns: list[DefectPattern]
    ) -> list[DefectPattern]:
        """Consolida padrões similares (mesmo domínio + keywords sobrepostos)."""
        consolidated: list[DefectPattern] = []
        used: set[int] = set()

        for i, p in enumerate(patterns):
            if i in used:
                continue
            merged = p
            for j, q in enumerate(patterns[i + 1:], start=i + 1):
                if j in used:
                    continue
                if (
                    p.domain == q.domain
                    and len(set(p.trigger_keywords) & set(q.trigger_keywords)) >= 1
                ):
                    merged = self._merge_patterns(merged, q)
                    used.add(j)
            consolidated.append(merged)
            used.add(i)

        return consolidated

    @staticmethod
    def _merge_patterns(a: DefectPattern, b: DefectPattern) -> DefectPattern:
        merged_keywords = list(dict.fromkeys(a.trigger_keywords + b.trigger_keywords))
        return DefectPattern(
            pattern_name=a.pattern_name,
            description=a.description,
            trigger_keywords=merged_keywords[:8],
            trigger_domains=list(set(a.trigger_domains + b.trigger_domains)),
            defect_ids=list(set(a.defect_ids + b.defect_ids)),
            occurrences=a.occurrences + b.occurrences,
            avg_severity=a.avg_severity if a.avg_severity < b.avg_severity else b.avg_severity,
            prevention_steps=list(dict.fromkeys(a.prevention_steps + b.prevention_steps)),
            suggested_scenarios=list(dict.fromkeys(
                a.suggested_scenarios + b.suggested_scenarios
            )),
            confidence=min(1.0, (a.confidence + b.confidence) / 2 + 0.05),
            domain=a.domain,
        )

    # ------------------------------------------------------------------
    # Domain inference
    # ------------------------------------------------------------------

    def _infer_domain(self, text: str) -> str:
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[domain] = score
        if not scores:
            return "general"
        return max(scores, key=lambda d: scores[d])

    def _extract_keywords(self, text: str, domain: str) -> list[str]:
        """Extrai keywords relevantes do texto, priorizando termos do domínio."""
        domain_kws = set(self._DOMAIN_KEYWORDS.get(domain, []))
        words      = re.findall(r'\b[a-záéíóúàãõç]{4,}\b', text.lower())
        freq       = Counter(words)

        # Prioritize domain keywords, then by frequency
        domain_matches = [w for w in domain_kws if freq.get(w, 0) > 0]
        other_common   = [
            w for w, c in freq.most_common(20)
            if c >= 2 and w not in domain_kws
            and w not in {"para", "pelo", "pela", "como", "esse", "essa",
                          "este", "esta", "mais", "deve", "quando"}
        ]
        return (domain_matches + other_common)[:6]

    # ------------------------------------------------------------------
    # Prevention & scenarios
    # ------------------------------------------------------------------

    def _prevention_steps(self, domain: str, keywords: list[str]) -> list[str]:
        base: dict[str, list[str]] = {
            "authentication": [
                "Adicionar cenário de login com token expirado",
                "Testar comportamento com credenciais inválidas",
                "Verificar expiração de sessão após inatividade",
                "Cobrir cenário de 2FA quando habilitado",
            ],
            "payments": [
                "Adicionar cenário de falha de gateway de pagamento",
                "Testar idempotência em cobranças duplicadas",
                "Verificar comportamento em timeout de gateway",
                "Cobrir estorno e reembolso automático",
            ],
            "authorization": [
                "Testar acesso direto a URL sem autenticação",
                "Verificar segregação de papéis (RBAC)",
                "Cobrir tentativa de acesso a recurso de outro usuário",
                "Testar escalação de privilégios",
            ],
            "forms": [
                "Testar submissão com campos obrigatórios vazios",
                "Verificar validação de formato de e-mail",
                "Cobrir caracteres especiais e SQL injection em inputs",
                "Testar comprimento máximo de campos",
            ],
            "api": [
                "Testar comportamento em timeout de requisição",
                "Verificar resposta a payload inválido",
                "Cobrir rate limiting e throttling",
                "Testar autenticação inválida (401) e proibida (403)",
            ],
        }
        domain_steps = base.get(domain, [
            "Adicionar cenários para casos de borda do domínio",
            "Verificar comportamento com dados inválidos",
        ])
        return domain_steps

    def _suggested_scenarios(self, domain: str, keywords: list[str]) -> list[str]:
        scenarios: dict[str, list[str]] = {
            "authentication": [
                "Dado que o token JWT está expirado\n"
                "Quando o usuário tenta acessar recurso protegido\n"
                "Então é esperado que receba 401 e seja redirecionado ao login",
                "Dado que o usuário errou a senha 5 vezes\n"
                "Quando tenta o sexto login\n"
                "Então é esperado que a conta seja temporariamente bloqueada",
            ],
            "payments": [
                "Dado que o gateway de pagamento está indisponível\n"
                "Quando o usuário tenta finalizar a compra\n"
                "Então é esperado que receba mensagem de erro e o pedido não seja criado",
                "Dado que o mesmo pagamento é enviado duas vezes\n"
                "Quando o sistema processa a segunda requisição\n"
                "Então é esperado que seja idempotente e não cobre duas vezes",
            ],
            "authorization": [
                "Dado que o usuário não está autenticado\n"
                "Quando tenta acessar /dashboard diretamente\n"
                "Então é esperado que seja redirecionado para login",
                "Dado que o usuário tem papel 'viewer'\n"
                "Quando tenta executar operação de escrita\n"
                "Então é esperado que receba 403 Forbidden",
            ],
        }
        return scenarios.get(domain, [
            f"Dado que o sistema está em estado normal\n"
            f"Quando a operação relacionada a '{keywords[0] if keywords else domain}' é executada\n"
            f"Então é esperado que o comportamento seja correto e sem erros"
        ])

    @staticmethod
    def _pattern_description(
        domain: str, keywords: list[str], defects: list[DefectRecord]
    ) -> str:
        kw_str = ", ".join(keywords[:3])
        return (
            f"Padrão recorrente no domínio '{domain}' relacionado a {kw_str}. "
            f"Observado em {len(defects)} defeito(s) histórico(s)."
        )

    @staticmethod
    def _avg_severity(severities: list[str]) -> str:
        order = {"P0": 0, "P1": 1, "P2": 2}
        if not severities:
            return "P1"
        return min(severities, key=lambda s: order.get(s, 99))

    @staticmethod
    def _pattern_to_memory(pattern: DefectPattern) -> MemoryEntry:
        import json as _json
        return MemoryEntry(
            memory_type=MemoryType.DEFECT_PATTERN,
            title=pattern.pattern_name,
            description=pattern.description,
            source_ids=pattern.defect_ids,
            tags=[pattern.domain, "defect-pattern", f"severity:{pattern.avg_severity}"],
            frequency=pattern.occurrences,
            confidence=pattern.confidence,
            domain=pattern.domain,
            metadata={
                "trigger_keywords":    pattern.trigger_keywords,
                "prevention_steps":    pattern.prevention_steps,
                "suggested_scenarios": pattern.suggested_scenarios,
                "avg_severity":        pattern.avg_severity,
                "risk_score":          pattern.risk_score,
            },
        )
