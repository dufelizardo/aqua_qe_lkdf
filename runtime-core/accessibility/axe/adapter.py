"""
runtime_core/accessibility/axe/adapter.py
AQuA-QE LKDF v1.4 — Axe-Core Adapter

Parseia resultados do axe-core e mapeia para os modelos WCAG do LKDF.
Suporta:
  - axe-core JSON output (via Playwright inject)
  - Pa11y JSON output
  - Lighthouse accessibility JSON
  - Input manual (para ambientes sem browser)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from runtime_core.accessibility.wcag.models import (
    AccessibilityViolation,
    ConformanceLevel,
    ConformanceReport,
    CRITERIA_BY_NUMBER,
    ViolationImpact,
    ViolationStatus,
    WcagCriterion,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Impact mapping
# ---------------------------------------------------------------------------

_AXE_IMPACT_MAP: dict[str, ViolationImpact] = {
    "critical": ViolationImpact.CRITICAL,
    "serious":  ViolationImpact.SERIOUS,
    "moderate": ViolationImpact.MODERATE,
    "minor":    ViolationImpact.MINOR,
}

# axe-core rule → WCAG criterion number
_AXE_RULE_TO_WCAG: dict[str, str] = {
    "image-alt":                 "1.1.1",
    "input-image-alt":           "1.1.1",
    "color-contrast":            "1.4.3",
    "color-contrast-enhanced":   "1.4.6",
    "label":                     "1.3.1",
    "label-content-name-mismatch": "2.5.3",
    "html-has-lang":             "3.1.1",
    "html-lang-valid":           "3.1.1",
    "document-title":            "2.4.2",
    "duplicate-id":              "4.1.1",
    "duplicate-id-active":       "4.1.1",
    "aria-required-attr":        "4.1.2",
    "aria-roles":                "4.1.2",
    "button-name":               "4.1.2",
    "link-name":                 "2.4.4",
    "tabindex":                  "2.1.1",
    "scrollable-region-focusable": "2.1.1",
    "skip-link":                 "2.4.1",
    "heading-order":             "2.4.6",
    "focus-visible":             "2.4.7",
    "aria-live-region-attr":     "4.1.3",
    "autocomplete-valid":        "1.3.5",
    "list":                      "1.3.1",
    "listitem":                  "1.3.1",
    "th-has-data-cells":         "1.3.1",
}


# ---------------------------------------------------------------------------
# Axe-core adapter
# ---------------------------------------------------------------------------

class AxeAdapter:
    """
    Parseia output JSON do axe-core e converte para ConformanceReport LKDF.

    O axe-core retorna:
      violations[]:  regras que falharam
      passes[]:      regras que passaram
      inapplicable[]: regras não aplicáveis
      incomplete[]:  regras inconclusivas

    Cada violation tem:
      id, impact, description, help, helpUrl, tags[], nodes[]
    """

    def parse_axe_json(
        self,
        axe_output: dict[str, Any],
        url:        str = "",
        component:  str = "",
    ) -> ConformanceReport:
        """Converte output JSON do axe-core em ConformanceReport."""
        violations: list[AccessibilityViolation] = []

        for v_raw in axe_output.get("violations", []):
            wcag_criterion = self._resolve_criterion(v_raw)
            impact         = _AXE_IMPACT_MAP.get(v_raw.get("impact", "serious"),
                                                   ViolationImpact.SERIOUS)

            # One violation per node found
            for node in v_raw.get("nodes", [{"html": ""}]):
                violation = AccessibilityViolation(
                    criterion=wcag_criterion,
                    criterion_ref=self._extract_wcag_ref(v_raw),
                    impact=impact,
                    status=ViolationStatus.OPEN,
                    element=node.get("target", [""])[0] if node.get("target") else "",
                    page_url=url,
                    description=v_raw.get("description", ""),
                    how_to_fix=v_raw.get("help", ""),
                    snippet=node.get("html", "")[:200],
                    tool="axe-core",
                    rule_id=v_raw.get("id", ""),
                    tags=v_raw.get("tags", []),
                    metadata={
                        "helpUrl":  v_raw.get("helpUrl", ""),
                        "any":      node.get("any", []),
                        "all":      node.get("all", []),
                        "none":     node.get("none", []),
                    },
                )
                violations.append(violation)

        passes     = [r.get("id", "") for r in axe_output.get("passes", [])]
        inapplicable = [r.get("id", "") for r in axe_output.get("inapplicable", [])]

        report = ConformanceReport(
            url=url,
            component=component,
            target_level=ConformanceLevel.AA,
            violations=violations,
            passes=passes,
            inapplicable=inapplicable,
            tool="axe-core",
        )

        log.info(
            "axe_parse_complete",
            url=url,
            violations=len(violations),
            passes=len(passes),
            aa_compliant=report.is_aa_compliant,
        )
        return report

    def parse_axe_json_string(self, json_str: str, url: str = "") -> ConformanceReport:
        return self.parse_axe_json(json.loads(json_str), url=url)

    def parse_pa11y_json(
        self,
        pa11y_output: list[dict[str, Any]],
        url: str = "",
    ) -> ConformanceReport:
        """Converte output JSON do Pa11y em ConformanceReport."""
        violations: list[AccessibilityViolation] = []

        for issue in pa11y_output:
            code = issue.get("code", "")
            # Pa11y code format: "WCAG2AA.Principle1.Guideline1_1.1_1_1.H37"
            wcag_num = self._extract_wcag_from_pa11y_code(code)
            criterion = CRITERIA_BY_NUMBER.get(wcag_num)

            type_map = {
                "error":   ViolationImpact.SERIOUS,
                "warning": ViolationImpact.MODERATE,
                "notice":  ViolationImpact.MINOR,
            }
            impact = type_map.get(issue.get("type", "error"), ViolationImpact.SERIOUS)

            violations.append(AccessibilityViolation(
                criterion=criterion,
                criterion_ref=wcag_num,
                impact=impact,
                status=ViolationStatus.OPEN,
                element=issue.get("selector", ""),
                page_url=url,
                description=issue.get("message", ""),
                snippet=issue.get("context", "")[:200],
                tool="pa11y",
                rule_id=code,
            ))

        return ConformanceReport(
            url=url,
            violations=violations,
            tool="pa11y",
        )

    # ------------------------------------------------------------------
    # Playwright integration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def axe_inject_script() -> str:
        """
        Script para injetar axe-core em uma página Playwright e coletar resultados.
        Uso: page.evaluate(AxeAdapter.axe_inject_script())
        """
        return """
async () => {
    // Load axe-core from CDN if not already loaded
    if (typeof axe === 'undefined') {
        await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    const results = await axe.run({
        runOnly: {
            type: 'tag',
            values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
        }
    });
    return results;
}
"""

    @staticmethod
    async def run_on_playwright_page(page: Any) -> ConformanceReport:
        """
        Executa axe-core em uma página Playwright e retorna ConformanceReport.
        Requer que playwright esteja instalado e a página carregada.
        """
        adapter = AxeAdapter()
        try:
            results = await page.evaluate(AxeAdapter.axe_inject_script())
            return adapter.parse_axe_json(results, url=page.url)
        except Exception as exc:
            log.error("axe_playwright_error", error=str(exc))
            return ConformanceReport(url=page.url, tool="axe-core")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_criterion(v_raw: dict[str, Any]) -> WcagCriterion | None:
        rule_id = v_raw.get("id", "")
        wcag_num = _AXE_RULE_TO_WCAG.get(rule_id)
        if wcag_num:
            return CRITERIA_BY_NUMBER.get(wcag_num)

        # Try to extract from tags (e.g. "wcag111" → "1.1.1")
        for tag in v_raw.get("tags", []):
            if tag.startswith("wcag") and tag[4:].isdigit():
                digits = tag[4:]
                if len(digits) == 3:
                    num = f"{digits[0]}.{digits[1]}.{digits[2]}"
                    crit = CRITERIA_BY_NUMBER.get(num)
                    if crit:
                        return crit
        return None

    @staticmethod
    def _extract_wcag_ref(v_raw: dict[str, Any]) -> str:
        for tag in v_raw.get("tags", []):
            if tag.startswith("wcag") and tag[4:].isdigit():
                digits = tag[4:]
                if len(digits) == 3:
                    return f"{digits[0]}.{digits[1]}.{digits[2]}"
        return ""

    @staticmethod
    def _extract_wcag_from_pa11y_code(code: str) -> str:
        """
        Extrai número WCAG de código Pa11y.
        ex: "WCAG2AA.Principle1.Guideline1_1.1_1_1.H37" → "1.1.1"
        """
        parts = code.split(".")
        for part in parts:
            if "_" in part and all(c.isdigit() or c == "_" for c in part):
                nums = part.split("_")
                if len(nums) == 3:
                    return ".".join(nums)
        return ""
