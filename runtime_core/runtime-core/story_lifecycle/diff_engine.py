"""
runtime_core/story_lifecycle/diff_engine.py
AQuA-QE LKDF v1.4 — Story Diff Engine

Responsável por:
  - Calcular diff semântico entre versões de uma Story
  - Identificar mudanças que impactam scenarios existentes
  - Detectar ambiguidades introduzidas pela mudança
  - Avaliar o risco delta (aumentou / diminuiu / neutro)
  - Triggering de regeneração de cenários pós-diff
"""
from __future__ import annotations

import difflib

import structlog

from runtime_core.story_lifecycle.models import (
    DiffCategory,
    DiffEntry,
    StoryVersion,
    VersionDiff,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Diff Engine
# ---------------------------------------------------------------------------

class DiffEngine:
    """
    Calcula diffs semânticos entre versões de Story.

    Opera em duas camadas:
      1. Estrutural — campos escalares e listas (determinístico)
      2. Semântico  — intenção das mudanças (via AI Gateway, opcional)
    """

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def compute(
        self,
        version_a: StoryVersion,
        version_b: StoryVersion,
    ) -> VersionDiff:
        """
        Computa diff entre version_a (from) e version_b (to).
        version_a = mais antiga, version_b = mais nova.
        """
        changes: list[DiffEntry] = []

        # 1. Title
        if version_a.title != version_b.title:
            changes.append(DiffEntry(
                category=DiffCategory.TEXT_CHANGE,
                field_path="title",
                old_value=version_a.title,
                new_value=version_b.title,
                description=f"Título alterado de '{version_a.title}' para '{version_b.title}'",
            ))

        # 2. Description
        if version_a.description != version_b.description:
            desc_diff = self._text_diff(version_a.description, version_b.description)
            changes.append(DiffEntry(
                category=DiffCategory.TEXT_CHANGE,
                field_path="description",
                old_value=version_a.description[:100],
                new_value=version_b.description[:100],
                description=f"Descrição alterada — {desc_diff}",
            ))

        # 3. Acceptance criteria (deep diff)
        changes.extend(self._diff_criteria(
            version_a.acceptance_criteria,
            version_b.acceptance_criteria,
        ))

        # 4. Priority
        if version_a.priority != version_b.priority:
            changes.append(DiffEntry(
                category=DiffCategory.PRIORITY_CHANGE,
                field_path="priority",
                old_value=version_a.priority,
                new_value=version_b.priority,
                description=f"Prioridade alterada de {version_a.priority} para {version_b.priority}",
            ))

        # 5. Risk delta
        risk_delta = self._assess_risk_delta(version_a, version_b, changes)

        # 6. Scenarios impacted
        scenarios_impacted = self._identify_impacted_scenarios(changes)

        # 7. Ambiguities introduced
        ambiguities = self._detect_new_ambiguities(version_a, version_b)

        diff = VersionDiff(
            from_version=version_a.version_number,
            to_version=version_b.version_number,
            changes=changes,
            ambiguities_introduced=ambiguities,
            scenarios_impacted=scenarios_impacted,
            risk_delta=risk_delta,
        )

        log.info(
            "diff_computed",
            from_v=version_a.version_number,
            to_v=version_b.version_number,
            changes=len(changes),
            breaking=diff.is_breaking,
            risk_delta=risk_delta,
        )
        return diff

    def compute_multi(
        self,
        versions: list[StoryVersion],
    ) -> list[VersionDiff]:
        """Computa diffs entre versões consecutivas de uma lista ordenada."""
        if len(versions) < 2:
            return []
        sorted_versions = sorted(versions, key=lambda v: v.version_number)
        return [
            self.compute(sorted_versions[i], sorted_versions[i + 1])
            for i in range(len(sorted_versions) - 1)
        ]

    # ------------------------------------------------------------------
    # Criteria diff
    # ------------------------------------------------------------------

    def _diff_criteria(
        self,
        old: list[str],
        new: list[str],
    ) -> list[DiffEntry]:
        entries: list[DiffEntry] = []

        old_set = set(old)
        new_set = set(new)

        added   = new_set - old_set
        removed = old_set - new_set

        # Modified: similar strings (not exact match, not fully new)
        modified_pairs: list[tuple[str, str]] = []
        remaining_old = list(old_set - removed)
        remaining_new = list(new_set - added)
        used_new: set[str] = set()

        for old_crit in remaining_old:
            best_match = None
            best_ratio = 0.0
            for new_crit in remaining_new:
                if new_crit in used_new:
                    continue
                ratio = difflib.SequenceMatcher(None, old_crit, new_crit).ratio()
                if ratio > 0.6 and ratio < 1.0 and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = new_crit
            if best_match:
                modified_pairs.append((old_crit, best_match))
                used_new.add(best_match)
                added.discard(best_match)

        for crit in added:
            entries.append(DiffEntry(
                category=DiffCategory.CRITERIA_ADD,
                field_path="acceptance_criteria[+]",
                new_value=crit,
                description=f"Critério adicionado: '{crit[:80]}'",
            ))

        for crit in removed:
            entries.append(DiffEntry(
                category=DiffCategory.CRITERIA_DEL,
                field_path="acceptance_criteria[-]",
                old_value=crit,
                description=f"Critério removido: '{crit[:80]}'",
            ))

        for old_c, new_c in modified_pairs:
            entries.append(DiffEntry(
                category=DiffCategory.CRITERIA_MOD,
                field_path="acceptance_criteria[~]",
                old_value=old_c,
                new_value=new_c,
                description=f"Critério modificado: '{old_c[:60]}' → '{new_c[:60]}'",
            ))

        return entries

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------

    def _assess_risk_delta(
        self,
        version_a: StoryVersion,
        version_b: StoryVersion,
        changes:   list[DiffEntry],
    ) -> str:
        if not changes:
            return "none"

        risky_categories = {
            DiffCategory.CRITERIA_DEL,
            DiffCategory.CRITERIA_MOD,
            DiffCategory.SCOPE_REMOVE,
        }
        safe_categories = {
            DiffCategory.CRITERIA_ADD,
            DiffCategory.SCOPE_ADD,
        }

        has_risky = any(c.category in risky_categories for c in changes)
        has_safe  = any(c.category in safe_categories  for c in changes)
        priority_dropped = (
            version_a.priority.value < version_b.priority.value
        )   # P0 < P1 < P2 alphabetically

        if has_risky:
            return "increased"
        if has_safe and not priority_dropped:
            return "decreased"
        return "neutral"

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------

    def _identify_impacted_scenarios(self, changes: list[DiffEntry]) -> list[str]:
        """
        Identifica scenarios possivelmente impactados pelas mudanças.
        Retorna lista de hints — IDs reais resolvidos via GraphRepository downstream.
        """
        hints: list[str] = []
        for change in changes:
            if change.category in (DiffCategory.CRITERIA_DEL, DiffCategory.CRITERIA_MOD):
                hints.append(f"scenarios-covering:{change.old_value!s:.40}")
            if change.category == DiffCategory.PRIORITY_CHANGE:
                hints.append("scenarios-all:priority-reorder-needed")
        return hints

    # ------------------------------------------------------------------
    # Ambiguity detection on diff
    # ------------------------------------------------------------------

    def _detect_new_ambiguities(
        self,
        version_a: StoryVersion,
        version_b: StoryVersion,
    ) -> list[str]:
        """
        Detecta ambiguidades introduzidas especificamente pela mudança,
        comparando os textos novos com os antigos.
        """
        from ai_engine.ambiguity_engine.detector import RuleBasedDetector
        detector = RuleBasedDetector()

        new_text = " ".join([
            version_b.title,
            version_b.description,
            *version_b.acceptance_criteria,
        ])
        old_text = " ".join([
            version_a.title,
            version_a.description,
            *version_a.acceptance_criteria,
        ])

        new_ambs = {a.excerpt.lower() for a in detector.detect(new_text)}
        old_ambs = {a.excerpt.lower() for a in detector.detect(old_text)}
        introduced = new_ambs - old_ambs

        return [f"Nova ambiguidade introduzida: '{exc}'" for exc in introduced]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _text_diff(old: str, new: str) -> str:
        """Resumo legível do diff textual."""
        if not old and new:
            return f"{len(new)} caracteres adicionados"
        if old and not new:
            return f"{len(old)} caracteres removidos"
        ratio = difflib.SequenceMatcher(None, old, new).ratio()
        pct   = int((1 - ratio) * 100)
        return f"{pct}% do conteúdo alterado"
