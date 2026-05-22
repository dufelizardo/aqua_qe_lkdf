"""
runtime_core/semantic_engine/intent_resolver.py
AQuA-QE LKDF — Semantic Engine

Responsável por:
  - Resolver a intenção semântica de cada step
  - Mapear intenção → action no adapter
  - Enriquecer o contexto com entidades extraídas
  - Detectar ambiguidades semânticas
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from shared.models import SemanticStep


# ---------------------------------------------------------------------------
# Intent Catalog — contratos semânticos universais
# ---------------------------------------------------------------------------
#
# Cada entrada mapeia um padrão de texto → intent canônica + action.
# A action é adapter-agnóstica; o adapter a traduz para sua sintaxe nativa.
#
# Formato: (regex_pattern, intent, action, entity_groups)
#

@dataclass
class IntentMapping:
    pattern: re.Pattern[str]
    intent: str
    action: str
    entity_keys: list[str]      # nomes dos grupos de captura


_RAW_MAPPINGS: list[tuple[str, str, str, list[str]]] = [
    # --- Navigation ---
    (r"está na página de (.+)",            "navigate",        "open_page",        ["page"]),
    (r"acessa (?:a página|o url|o link) (.+)", "navigate",    "open_url",         ["target"]),
    (r"navega para (.+)",                  "navigate",        "open_page",        ["page"]),

    # --- Input ---
    (r'insere? "([^"]+)" no campo (.+)',   "fill_field",      "fill",             ["value", "field"]),
    (r'digita "([^"]+)" em (.+)',          "fill_field",      "fill",             ["value", "field"]),
    (r'preenche? (.+) com "([^"]+)"',      "fill_field",      "fill",             ["field", "value"]),

    # --- Click / Action ---
    (r'clica? (?:no botão|no link|em) "([^"]+)"', "click",   "click_element",    ["element"]),
    (r'clica? em (.+)',                    "click",           "click_element",    ["element"]),
    (r'submete? (?:o formulário|o form)',  "submit_form",     "submit",           []),

    # --- Assertion ---
    (r'(?:seja|é) exibid[ao] a mensagem "([^"]+)"', "assert_message", "assert_text", ["text"]),
    (r'(?:mensagem|texto) "([^"]+)" seja exibid[ao]',  "assert_message", "assert_text", ["text"]),
    (r'receba a mensagem "([^"]+)"',       "assert_message",  "assert_text",      ["text"]),
    (r'a mensagem "([^"]+)" seja exibida', "assert_message",  "assert_text",      ["text"]),
    (r'o título seja "([^"]+)"',           "assert_title",    "assert_title",     ["title"]),
    (r'o elemento (.+) esteja visível',    "assert_visible",  "assert_visible",   ["element"]),
    (r'o elemento (.+) não esteja visível',"assert_hidden",   "assert_hidden",    ["element"]),
    (r'receba a mensagem "([^"]+)"',       "assert_message",  "assert_text",      ["text"]),
    (r'o resultado seja (.+)',             "assert_result",   "assert_text",      ["expected"]),

    # --- State / Precondition ---
    (r'(?:está|possui|tem) credenciais válidas',  "setup_credentials",  "set_valid_credentials", []),
    (r'está autenticad[oa]',              "assert_authenticated", "verify_login",   []),
    (r'conta (.+) está bloqueada',        "setup_blocked_account","block_account",  ["account"]),
    (r'(?:está|tem) (?:itens?|produtos?) no carrinho', "setup_cart", "populate_cart", []),

    # --- Wait ---
    (r'aguarda? (?:até )?(\d+) segundos?',"wait",             "wait_seconds",     ["seconds"]),
    (r'aguarda? o elemento (.+)',         "wait_element",     "wait_for_element", ["element"]),

    # --- Generic fallback ---
    (r'(.+)',                              "generic_action",  "execute_keyword",  ["text"]),
]

INTENT_CATALOG: list[IntentMapping] = [
    IntentMapping(
        pattern=re.compile(raw, re.IGNORECASE),
        intent=intent,
        action=action,
        entity_keys=keys,
    )
    for raw, intent, action, keys in _RAW_MAPPINGS
]


# ---------------------------------------------------------------------------
# Intent Resolver
# ---------------------------------------------------------------------------

@dataclass
class ResolvedIntent:
    intent: str
    action: str
    entities: dict[str, str]
    confidence: float           # 0.0 – 1.0
    ambiguous: bool = False
    ambiguity_reason: str = ""


class IntentResolver:
    """
    Resolve a intenção semântica de cada step do DSL.
    Aplica os contratos semânticos do INTENT_CATALOG.
    """

    def resolve(self, step: SemanticStep) -> ResolvedIntent:
        # Remove keyword prefix (Dado que, Quando o, etc.)
        text = self._clean_text(step.text)

        best: ResolvedIntent | None = None
        candidates: list[ResolvedIntent] = []

        for mapping in INTENT_CATALOG:
            m = mapping.pattern.search(text)
            if not m:
                continue

            entities: dict[str, str] = {}
            for i, key in enumerate(mapping.entity_keys):
                try:
                    entities[key] = m.group(i + 1).strip()
                except IndexError:
                    pass

            # Score based on specificity (longer pattern = higher confidence)
            pattern_len = len(mapping.pattern.pattern)
            confidence  = min(1.0, pattern_len / 60.0)

            if mapping.intent != "generic_action":
                confidence = min(1.0, confidence + 0.3)

            resolved = ResolvedIntent(
                intent=mapping.intent,
                action=mapping.action,
                entities=entities,
                confidence=confidence,
            )
            candidates.append(resolved)

        if not candidates:
            return ResolvedIntent(
                intent="unknown",
                action="execute_keyword",
                entities={"text": text},
                confidence=0.0,
                ambiguous=True,
                ambiguity_reason="Nenhuma intenção mapeada para este step.",
            )

        # Pick highest confidence
        candidates.sort(key=lambda r: r.confidence, reverse=True)
        best = candidates[0]

        # Detect ambiguity: two candidates with similar confidence
        if len(candidates) > 1 and (candidates[0].confidence - candidates[1].confidence) < 0.1:
            best.ambiguous = True
            best.ambiguity_reason = (
                f"Ambiguidade entre '{candidates[0].intent}' e '{candidates[1].intent}'. "
                "Considere usar linguagem mais específica."
            )

        return best

    def resolve_all(self, steps: list[SemanticStep]) -> list[tuple[SemanticStep, ResolvedIntent]]:
        return [(step, self.resolve(step)) for step in steps]

    def enrich_step(self, step: SemanticStep) -> SemanticStep:
        """Enriquece o step com intent e action resolvidos (mutação em cópia)."""
        resolved = self.resolve(step)
        return step.model_copy(update={
            "intent": resolved.intent,
            "action": resolved.action,
            "parameters": {**step.parameters, **resolved.entities},
        })

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_text(raw: str) -> str:
        """Remove keyword prefix e conectivos para facilitar matching."""
        prefixes = [
            r"^Dado que\s+",
            r"^Dado\s+",
            r"^Quando o\s+",
            r"^Quando a\s+",
            r"^Quando\s+",
            r"^Então é esperado que\s+",
            r"^Então\s+",
            r"^E que\s+",
            r"^E o\s+",
            r"^E a\s+",
            r"^E\s+",
            r"^Mas\s+",
        ]
        text = raw
        for prefix in prefixes:
            text = re.sub(prefix, "", text, flags=re.IGNORECASE)
        return text.strip()


# ---------------------------------------------------------------------------
# Semantic Enrichment — Context Analyzer
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """
    Analisa o conjunto de steps de um scenario para extrair
    contexto semântico rico (entidades, risco, cobertura).
    """

    def analyze_scenario(self, steps: list[SemanticStep]) -> dict[str, Any]:
        resolver = IntentResolver()
        resolved = resolver.resolve_all(steps)

        intents        = [r.intent for _, r in resolved]
        entities: dict[str, list[str]] = {}
        ambiguities: list[str] = []

        for step, r in resolved:
            for k, v in r.entities.items():
                entities.setdefault(k, []).append(v)
            if r.ambiguous:
                ambiguities.append(f"Step '{step.text[:60]}': {r.ambiguity_reason}")

        has_navigation  = "navigate" in intents
        has_assertions  = any("assert" in i for i in intents)
        has_setup       = any("setup" in i for i in intents)
        coverage_score  = (
            (1 if has_navigation else 0) +
            (2 if has_assertions else 0) +
            (1 if has_setup else 0)
        ) / 4.0

        return {
            "intents":          intents,
            "entities":         entities,
            "ambiguities":      ambiguities,
            "has_navigation":   has_navigation,
            "has_assertions":   has_assertions,
            "has_setup":        has_setup,
            "coverage_score":   coverage_score,
            "risk_level":       "HIGH" if ambiguities else "LOW",
        }
