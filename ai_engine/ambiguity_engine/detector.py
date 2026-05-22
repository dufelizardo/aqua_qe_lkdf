"""
ai_engine/ambiguity_engine/detector.py
AQuA-QE LKDF — Ambiguity Engine: Rule-Based Detector

Detecta ambiguidades determinísticas via padrões linguísticos.
Funciona sem API — base para o modo offline e como pré-filtro para a IA.

Cobre:
  - Termos vagos quantitativos ("rapidamente", "adequado", "muitos")
  - Referências indefinidas ("o usuário", "o sistema", "o dashboard")
  - Ausência de tratamento de erro ("deve X" sem "caso contrário")
  - Condicionais implícitas ("quando necessário", "se aplicável")
  - Temporalidade vaga ("em breve", "após", "antes de")
  - Sujeitos ambíguos (voz passiva sem agente)
"""
from __future__ import annotations

import re
from uuid import uuid4

from ai_engine.ambiguity_engine.models import (
    Ambiguity,
    AmbiguitySeverity,
    AmbiguityType,
    BusinessRule,
    CoverageGap,
)


# ---------------------------------------------------------------------------
# Pattern catalogs
# ---------------------------------------------------------------------------

_VAGUE_QUANTITATIVE = [
    (r"\b(rapidamente|rápido|de forma ágil|em tempo hábil)\b",
     "Tempo de resposta vago", "Qual é o SLA esperado em milissegundos ou segundos?"),
    (r"\b(muitos|vários|alguns|poucos|diversos)\b",
     "Quantidade não especificada", "Qual é o valor numérico exato?"),
    (r"\b(grande|pequeno|médio|adequado|suficiente|razoável)\b",
     "Dimensão relativa sem referência", "Em relação a quê? Qual é o critério mensurável?"),
    (r"\b(frequentemente|ocasionalmente|raramente|sempre que possível)\b",
     "Frequência vaga", "Com que periodicidade exata? Em que condições?"),
    (r"\b(alto|baixo|elevado|reduzido) (volume|carga|tráfego|número)\b",
     "Limites de carga não definidos", "Qual é o volume numérico que define 'alto' vs 'baixo'?"),
]

_VAGUE_REFERENCES = [
    (r"\b(o usuário|a conta|o sistema|o dashboard|o relatório|o painel)\b",
     "Referência definida assume instância única",
     "Existe apenas um? Usuários com papéis diferentes têm instâncias distintas?"),
    (r"\bdevid[ao]mente\b",
     "\"Devidamente\" é subjetivo",
     "O que significa 'devidamente' neste contexto? Qual é o critério de aceite?"),
    (r"\b(corretamente|adequadamente|apropriadamente)\b",
     "Advérbio de modo sem definição",
     "O que define 'corretamente' aqui? Qual é o comportamento esperado preciso?"),
    (r"\b(informações? (relevantes?|necessárias?|pertinentes?))\b",
     "\"Informações relevantes\" não definidas",
     "Quais campos específicos devem ser exibidos/processados?"),
]

_MISSING_ERROR_PATH = [
    (r"\b(deve|deverá|precisa|é necessário) [^,.]+\.",
     "Caminho de erro ausente",
     "O que acontece quando esta ação falha? Há rollback, retry, notificação?"),
    (r"\b(enviar?|processar?|salvar?|gravar?|atualizar?) [^,.]+\.",
     "Falha na operação não tratada",
     "O que ocorre em caso de timeout, indisponibilidade ou erro parcial?"),
    (r"\b(integrar?|sincronizar?|comunicar?) com\b",
     "Falha de integração não especificada",
     "O que fazer quando o sistema externo está indisponível?"),
]

_IMPLICIT_CONDITIONS = [
    (r"\b(quando necessário|se necessário|quando aplicável|se aplicável)\b",
     "Condição implícita não definida",
     "Quando exatamente é 'necessário'? Qual é o critério de ativação?"),
    (r"\b(pode|poderá|é permitido|tem a opção)\b",
     "Comportamento opcional sem critério",
     "É opcional para o usuário ou para o sistema? Em quais condições é permitido?"),
    (r"\b(automaticamente|de forma automática)\b",
     "Automação sem gatilho definido",
     "O que dispara a automação? Com que frequência? Há janela de tempo?"),
    (r"\b(em caso de (necessidade|demanda|solicitação))\b",
     "Gatilho vago",
     "O que especificamente constitui 'necessidade'?"),
]

_TEMPORAL_VAGUENESS = [
    (r"\b(em breve|logo|rapidamente|imediatamente|no menor tempo possível)\b",
     "Temporalidade sem SLA",
     "Qual é o prazo máximo aceitável? Em segundos, minutos ou horas?"),
    (r"\b(após|depois de|antes de) [^,.]+\b(?! \d)",
     "Sequência temporal indefinida",
     "Após quanto tempo? Existe um timeout? O que acontece se a condição não ocorrer?"),
    (r"\b(periodicamente|regularmente|de tempos em tempos)\b",
     "Periodicidade não especificada",
     "Com qual frequência exata? A cada hora, dia, semana?"),
    (r"\b(em tempo real|realtime|ao vivo)\b",
     "\"Tempo real\" sem latência definida",
     "Qual é a latência máxima aceitável para ser considerado 'tempo real'?"),
]

_PASSIVE_VOICE_NO_AGENT = [
    (r"\b(deve ser|deverá ser|será|é|são) (enviado|processado|aprovado|validado|gerado|criado|atualizado|notificado)\b",
     "Voz passiva sem agente",
     "Quem ou qual sistema é responsável por executar esta ação?"),
    (r"\b(será (verificado|conferido|checado|auditado))\b",
     "Verificação sem responsável",
     "Quem verifica? É automático ou manual? Com que critério?"),
]

_ALL_PATTERNS: list[tuple[str, list[tuple[str, str, str]], AmbiguityType, AmbiguitySeverity]] = [
    ("quantitative", _VAGUE_QUANTITATIVE, AmbiguityType.QUANTITATIVE, AmbiguitySeverity.HIGH),
    ("referential",  _VAGUE_REFERENCES,   AmbiguityType.REFERENTIAL,  AmbiguitySeverity.MEDIUM),
    ("implicit",     _MISSING_ERROR_PATH,  AmbiguityType.IMPLICIT,     AmbiguitySeverity.CRITICAL),
    ("scope",        _IMPLICIT_CONDITIONS, AmbiguityType.SCOPE,        AmbiguitySeverity.HIGH),
    ("temporal",     _TEMPORAL_VAGUENESS,  AmbiguityType.TEMPORAL,     AmbiguitySeverity.MEDIUM),
    ("passive",      _PASSIVE_VOICE_NO_AGENT, AmbiguityType.REFERENTIAL, AmbiguitySeverity.MEDIUM),
]


# ---------------------------------------------------------------------------
# Rule-based detector
# ---------------------------------------------------------------------------

class RuleBasedDetector:
    """
    Detecta ambiguidades via padrões linguísticos determinísticos.
    Rápido, offline, sem custo de API.
    Usado como pré-filtro e fallback quando Claude não está disponível.
    """

    def detect(self, text: str) -> list[Ambiguity]:
        ambiguities: list[Ambiguity] = []
        seen_excerpts: set[str] = set()

        for group_name, patterns, amb_type, default_severity in _ALL_PATTERNS:
            for pattern, description, question in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    excerpt = match.group(0).strip()
                    if excerpt.lower() in seen_excerpts:
                        continue
                    seen_excerpts.add(excerpt.lower())

                    amb = Ambiguity(
                        id=f"AMB-{str(uuid4())[:6].upper()}",
                        type=amb_type,
                        severity=default_severity,
                        text=description,
                        question=question,
                        excerpt=excerpt,
                        options=self._suggest_options(amb_type, excerpt),
                        impact=self._infer_impact(amb_type, default_severity),
                        scenario_hint=self._suggest_scenario(amb_type, excerpt),
                    )
                    ambiguities.append(amb)

        # Deduplicate by (type, excerpt) keeping highest severity
        return self._deduplicate(ambiguities)

    def extract_rules(self, text: str) -> list[BusinessRule]:
        """Extrai regras de negócio implícitas via padrões."""
        rules: list[BusinessRule] = []

        # Pattern: "deve X" → regra explícita
        for m in re.finditer(r"(?:deve|deverá|precisa)\s+([^,.]{10,80})", text, re.IGNORECASE):
            rules.append(BusinessRule(
                id=f"BR-{str(uuid4())[:6].upper()}",
                description=m.group(0).strip(),
                source="explicit",
                confidence=0.9,
            ))

        # Pattern: "não pode / não deve X" → regra de restrição
        for m in re.finditer(r"(?:não pode|não deve|é proibido|é vedado)\s+([^,.]{5,80})", text, re.IGNORECASE):
            rules.append(BusinessRule(
                id=f"BR-{str(uuid4())[:6].upper()}",
                description=m.group(0).strip(),
                source="explicit",
                confidence=0.95,
            ))

        # Pattern: "somente / apenas / exclusivamente"
        for m in re.finditer(r"(?:somente|apenas|exclusivamente)\s+([^,.]{5,60})", text, re.IGNORECASE):
            rules.append(BusinessRule(
                id=f"BR-{str(uuid4())[:6].upper()}",
                description=f"Restrição: {m.group(0).strip()}",
                source="inferred",
                confidence=0.85,
            ))

        return rules[:8]   # limit

    def identify_gaps(self, text: str) -> list[CoverageGap]:
        """Identifica gaps de cobertura via ausência de padrões."""
        gaps: list[CoverageGap] = []
        text_lower = text.lower()

        gap_checks = [
            (
                not any(kw in text_lower for kw in ["erro", "falha", "inválid", "incorret", "exception"]),
                "Nenhum caminho de erro descrito",
                "missing_error_path",
                "CRITICAL",
                "Teste com dados inválidos e verifique o comportamento de erro",
            ),
            (
                not any(kw in text_lower for kw in ["permissão", "autoriza", "papel", "role", "perfil", "acesso"]),
                "Controle de acesso não especificado",
                "missing_authorization",
                "HIGH",
                "Teste com usuário sem permissão para verificar comportamento",
            ),
            (
                not any(kw in text_lower for kw in ["timeout", "tempo limite", "expirar", "prazo"]),
                "Comportamento em timeout não especificado",
                "missing_timeout",
                "MEDIUM",
                "Teste o comportamento quando operação ultrapassa tempo máximo",
            ),
            (
                not any(kw in text_lower for kw in ["concorrente", "simultâneo", "paralelo", "race"]),
                "Comportamento concorrente não endereçado",
                "missing_concurrency",
                "HIGH",
                "Teste com múltiplas requisições simultâneas ao mesmo recurso",
            ),
            (
                not any(kw in text_lower for kw in ["log", "audit", "rastr", "histórico", "registro"]),
                "Auditoria e rastreabilidade não mencionadas",
                "missing_audit",
                "MEDIUM",
                "Verifique se operações críticas geram logs de auditoria",
            ),
        ]

        for condition, description, gap_type, priority, scenario in gap_checks:
            if condition:
                gaps.append(CoverageGap(
                    id=f"GAP-{str(uuid4())[:6].upper()}",
                    description=description,
                    gap_type=gap_type,
                    priority=priority,
                    suggested_scenario=scenario,
                ))

        return gaps

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _suggest_options(amb_type: AmbiguityType, excerpt: str) -> list[str]:
        if amb_type == AmbiguityType.IMPLICIT:
            return [
                "Operação falha silenciosamente (log apenas)",
                "Rollback automático e notificação ao usuário",
                "Retry automático com backoff exponencial",
                "Fila de recuperação para processamento posterior",
            ]
        if amb_type == AmbiguityType.TEMPORAL:
            return ["< 1 segundo", "< 5 segundos", "< 30 segundos", "< 5 minutos"]
        if amb_type == AmbiguityType.QUANTITATIVE:
            return ["Definir valor numérico exato", "Definir faixa aceitável", "Definir por SLA"]
        return []

    @staticmethod
    def _infer_impact(amb_type: AmbiguityType, severity: AmbiguitySeverity) -> str:
        impacts = {
            AmbiguityType.IMPLICIT:     "Comportamento indefinido em produção pode causar perda de dados ou estado inconsistente.",
            AmbiguityType.SCOPE:        "Implementações divergentes entre dev e negócio geram retrabalho pós-entrega.",
            AmbiguityType.QUANTITATIVE: "Sem SLA definido, testes de performance não têm critério de aceite.",
            AmbiguityType.REFERENTIAL:  "Funcionalidade pode ser implementada para contexto errado.",
            AmbiguityType.TEMPORAL:     "Timeout indefinido pode causar deadlock ou degradação silenciosa.",
            AmbiguityType.LEXICAL:      "Termos interpretados diferentemente por dev, QA e negócio.",
        }
        return impacts.get(amb_type, "Risco de implementação incorreta.")

    @staticmethod
    def _suggest_scenario(amb_type: AmbiguityType, excerpt: str) -> str:
        if amb_type == AmbiguityType.IMPLICIT:
            return f"Cenário: simular falha durante '{excerpt}' e verificar estado do sistema"
        if amb_type == AmbiguityType.TEMPORAL:
            return f"Cenário: medir tempo de '{excerpt}' sob carga normal e pico"
        if amb_type == AmbiguityType.REFERENTIAL:
            return f"Cenário: testar com múltiplas instâncias de '{excerpt}'"
        return f"Cenário: testar interpretações alternativas de '{excerpt}'"

    @staticmethod
    def _deduplicate(ambiguities: list[Ambiguity]) -> list[Ambiguity]:
        seen: dict[str, Ambiguity] = {}
        severity_order = {
            AmbiguitySeverity.CRITICAL: 4,
            AmbiguitySeverity.HIGH:     3,
            AmbiguitySeverity.MEDIUM:   2,
            AmbiguitySeverity.LOW:      1,
        }
        for amb in ambiguities:
            key = f"{amb.type}:{amb.excerpt[:30].lower()}"
            if key not in seen or severity_order[amb.severity] > severity_order[seen[key].severity]:
                seen[key] = amb
        return list(seen.values())
