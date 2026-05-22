"""
runtime_core/accessibility/wcag/models.py
AQuA-QE LKDF v1.4 — WCAG Domain Models

Catálogo de critérios WCAG 2.1 / 2.2, contratos de violação
e conformidade. Base para o gate WCAG_AA_COMPLIANCE.

Referência: https://www.w3.org/TR/WCAG21/ e WCAG 2.2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WcagVersion(str, Enum):
    V21 = "2.1"
    V22 = "2.2"


class ConformanceLevel(str, Enum):
    A   = "A"
    AA  = "AA"
    AAA = "AAA"


class WcagPrinciple(str, Enum):
    PERCEIVABLE  = "1"   # 1.x
    OPERABLE     = "2"   # 2.x
    UNDERSTANDABLE = "3" # 3.x
    ROBUST       = "4"   # 4.x


class ViolationImpact(str, Enum):
    CRITICAL = "critical"   # blocker — impede uso completo
    SERIOUS  = "serious"    # blocker — impede uso significativo
    MODERATE = "moderate"   # dificulta uso
    MINOR    = "minor"      # inconveniência


class ViolationStatus(str, Enum):
    OPEN     = "open"
    FIXED    = "fixed"
    DEFERRED = "deferred"
    WONTFIX  = "wontfix"
    FALSE_POSITIVE = "false_positive"


# ---------------------------------------------------------------------------
# WCAG Criterion
# ---------------------------------------------------------------------------

@dataclass
class WcagCriterion:
    """Um critério de sucesso WCAG individual."""
    number:      str               # ex: "1.1.1", "2.4.6"
    name:        str               # ex: "Non-text Content"
    level:       ConformanceLevel
    version:     WcagVersion       = WcagVersion.V21
    principle:   WcagPrinciple     = WcagPrinciple.PERCEIVABLE
    description: str               = ""
    how_to_meet: str               = ""
    test_rules:  list[str]         = field(default_factory=list)
    tags:        list[str]         = field(default_factory=list)

    @property
    def full_ref(self) -> str:
        return f"WCAG {self.version.value} {self.number} ({self.level.value})"

    @property
    def is_aa_or_above(self) -> bool:
        return self.level in (ConformanceLevel.AA, ConformanceLevel.AAA)


# ---------------------------------------------------------------------------
# Violation
# ---------------------------------------------------------------------------

@dataclass
class AccessibilityViolation:
    """Uma violação de acessibilidade detectada em um componente/página."""
    id:            UUID              = field(default_factory=uuid4)
    criterion:     WcagCriterion | None = None
    criterion_ref: str               = ""     # fallback: "1.1.1"
    impact:        ViolationImpact   = ViolationImpact.SERIOUS
    status:        ViolationStatus   = ViolationStatus.OPEN
    element:       str               = ""     # CSS selector ou XPath
    page_url:      str               = ""
    description:   str               = ""
    how_to_fix:    str               = ""
    snippet:       str               = ""     # HTML snippet
    tool:          str               = ""     # axe-core | pa11y | manual | lhci
    rule_id:       str               = ""     # ex: "image-alt", "color-contrast"
    tags:          list[str]         = field(default_factory=list)
    metadata:      dict[str, Any]    = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.impact in (ViolationImpact.CRITICAL, ViolationImpact.SERIOUS)

    @property
    def wcag_ref(self) -> str:
        if self.criterion:
            return self.criterion.full_ref
        return f"WCAG {self.criterion_ref}"


# ---------------------------------------------------------------------------
# Conformance Report
# ---------------------------------------------------------------------------

@dataclass
class ConformanceReport:
    """Relatório de conformidade WCAG de uma página ou componente."""
    id:            UUID                         = field(default_factory=uuid4)
    url:           str                          = ""
    component:     str                          = ""
    target_level:  ConformanceLevel             = ConformanceLevel.AA
    violations:    list[AccessibilityViolation] = field(default_factory=list)
    passes:        list[str]                    = field(default_factory=list)
    inapplicable:  list[str]                    = field(default_factory=list)
    tool:          str                          = "axe-core"
    scanned_at:    str                          = ""

    @property
    def violations_by_level(self) -> dict[str, list[AccessibilityViolation]]:
        result: dict[str, list[AccessibilityViolation]] = {"A": [], "AA": [], "AAA": []}
        for v in self.violations:
            if v.criterion:
                result[v.criterion.level.value].append(v)
        return result

    @property
    def a_violations(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations
                if v.criterion and v.criterion.level == ConformanceLevel.A]

    @property
    def aa_violations(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations
                if v.criterion and v.criterion.level == ConformanceLevel.AA]

    @property
    def blocking_violations(self) -> list[AccessibilityViolation]:
        return [v for v in self.violations if v.is_blocking]

    @property
    def is_aa_compliant(self) -> bool:
        return len(self.a_violations) == 0 and len(self.aa_violations) == 0

    @property
    def compliance_pct(self) -> float:
        """
        Percentual de critérios AA passando.
        (passes_aa / (passes_aa + violations_aa))
        """
        viol   = len(self.aa_violations) + len(self.a_violations)
        passed = len(self.passes)
        total  = viol + passed
        if total == 0:
            return 1.0
        return round(passed / total, 3)

    def summary(self) -> dict[str, Any]:
        return {
            "url":              self.url or self.component,
            "target_level":     self.target_level.value,
            "is_aa_compliant":  self.is_aa_compliant,
            "compliance_pct":   self.compliance_pct,
            "violations_total": len(self.violations),
            "violations_a":     len(self.a_violations),
            "violations_aa":    len(self.aa_violations),
            "blocking":         len(self.blocking_violations),
            "passes":           len(self.passes),
            "tool":             self.tool,
        }


# ---------------------------------------------------------------------------
# WCAG 2.1 / 2.2 Criteria Catalog (subset — critérios mais testados)
# ---------------------------------------------------------------------------

WCAG_CRITERIA: list[WcagCriterion] = [
    # ── Principle 1: Perceivable ──────────────────────────────────────────
    WcagCriterion("1.1.1", "Non-text Content",           ConformanceLevel.A,
                  principle=WcagPrinciple.PERCEIVABLE,
                  description="Imagens devem ter texto alternativo.",
                  how_to_meet="Adicione atributo alt descritivo em todas as imagens.",
                  test_rules=["image-alt", "input-image-alt"],
                  tags=["images", "screen-reader"]),

    WcagCriterion("1.3.1", "Info and Relationships",     ConformanceLevel.A,
                  principle=WcagPrinciple.PERCEIVABLE,
                  description="Estrutura e relacionamentos transmitidos via apresentação também disponíveis programaticamente.",
                  how_to_meet="Use HTML semântico: heading, list, table, form elements.",
                  test_rules=["label", "list", "listitem", "th-has-data-cells"],
                  tags=["structure", "semantics"]),

    WcagCriterion("1.3.4", "Orientation",                ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.PERCEIVABLE,
                  description="Conteúdo não deve restringir orientação de tela.",
                  test_rules=["css-orientation-lock"],
                  tags=["mobile", "orientation"]),

    WcagCriterion("1.3.5", "Identify Input Purpose",     ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.PERCEIVABLE,
                  description="Campos de entrada de informações do usuário identificam o propósito.",
                  how_to_meet="Use autocomplete attributes nos campos de formulário.",
                  test_rules=["autocomplete-valid"],
                  tags=["forms", "autocomplete"]),

    WcagCriterion("1.4.1", "Use of Color",               ConformanceLevel.A,
                  principle=WcagPrinciple.PERCEIVABLE,
                  description="Cor não é o único meio visual de transmitir informação.",
                  test_rules=["color-contrast"],
                  tags=["color", "visual"]),

    WcagCriterion("1.4.3", "Contrast (Minimum)",         ConformanceLevel.AA,
                  principle=WcagPrinciple.PERCEIVABLE,
                  description="Texto deve ter contraste mínimo de 4.5:1 (3:1 para texto grande).",
                  how_to_meet="Use ferramentas de verificação de contraste. Mínimo 4.5:1.",
                  test_rules=["color-contrast"],
                  tags=["color", "contrast", "visual"]),

    WcagCriterion("1.4.4", "Resize Text",                ConformanceLevel.AA,
                  principle=WcagPrinciple.PERCEIVABLE,
                  description="Texto redimensionável até 200% sem perda de conteúdo.",
                  tags=["zoom", "text-size"]),

    WcagCriterion("1.4.10", "Reflow",                    ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.PERCEIVABLE,
                  description="Conteúdo pode ser apresentado em 320px CSS sem scroll horizontal.",
                  test_rules=["css-orientation-lock"],
                  tags=["mobile", "responsive", "reflow"]),

    WcagCriterion("1.4.11", "Non-text Contrast",         ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.PERCEIVABLE,
                  description="Componentes de UI e gráficos têm contraste mínimo 3:1.",
                  test_rules=["color-contrast"],
                  tags=["color", "contrast", "ui-components"]),

    WcagCriterion("1.4.12", "Text Spacing",              ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.PERCEIVABLE,
                  description="Sem perda de conteúdo ao sobrescrever espaçamento de texto.",
                  tags=["text-spacing", "css"]),

    WcagCriterion("1.4.13", "Content on Hover or Focus", ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.PERCEIVABLE,
                  description="Tooltips e popovers acionados por hover/focus são dispensáveis e persistentes.",
                  tags=["hover", "focus", "tooltip"]),

    # ── Principle 2: Operable ─────────────────────────────────────────────
    WcagCriterion("2.1.1", "Keyboard",                   ConformanceLevel.A,
                  principle=WcagPrinciple.OPERABLE,
                  description="Toda funcionalidade disponível via teclado.",
                  how_to_meet="Garanta que todos os elementos interativos sejam focáveis.",
                  test_rules=["tabindex", "scrollable-region-focusable"],
                  tags=["keyboard", "focus"]),

    WcagCriterion("2.1.2", "No Keyboard Trap",           ConformanceLevel.A,
                  principle=WcagPrinciple.OPERABLE,
                  description="Foco de teclado não fica preso em um componente.",
                  test_rules=["tabindex"],
                  tags=["keyboard", "focus", "trap"]),

    WcagCriterion("2.4.1", "Bypass Blocks",              ConformanceLevel.A,
                  principle=WcagPrinciple.OPERABLE,
                  description="Mecanismo para pular blocos de conteúdo repetido.",
                  how_to_meet="Adicione link 'Pular para o conteúdo principal'.",
                  test_rules=["skip-link"],
                  tags=["skip-link", "navigation"]),

    WcagCriterion("2.4.2", "Page Titled",                ConformanceLevel.A,
                  principle=WcagPrinciple.OPERABLE,
                  description="Páginas têm título descritivo.",
                  test_rules=["document-title"],
                  tags=["title", "page"]),

    WcagCriterion("2.4.3", "Focus Order",                ConformanceLevel.A,
                  principle=WcagPrinciple.OPERABLE,
                  description="Ordem de foco preserva significado e operabilidade.",
                  test_rules=["tabindex"],
                  tags=["focus", "order"]),

    WcagCriterion("2.4.4", "Link Purpose (In Context)", ConformanceLevel.A,
                  principle=WcagPrinciple.OPERABLE,
                  description="Propósito de cada link determinável pelo texto ou contexto.",
                  test_rules=["link-name", "duplicate-link-checker"],
                  tags=["links", "navigation"]),

    WcagCriterion("2.4.6", "Headings and Labels",        ConformanceLevel.AA,
                  principle=WcagPrinciple.OPERABLE,
                  description="Headings e labels descritivos.",
                  test_rules=["heading-order"],
                  tags=["headings", "labels", "structure"]),

    WcagCriterion("2.4.7", "Focus Visible",              ConformanceLevel.AA,
                  principle=WcagPrinciple.OPERABLE,
                  description="Indicador de foco visível para navegação por teclado.",
                  how_to_meet="Nunca use outline: none sem substituição visível.",
                  test_rules=["focus-visible"],
                  tags=["focus", "keyboard", "visual"]),

    WcagCriterion("2.4.11", "Focus Appearance",          ConformanceLevel.AA,
                  version=WcagVersion.V22, principle=WcagPrinciple.OPERABLE,
                  description="Indicador de foco com área mínima e contraste suficiente (WCAG 2.2).",
                  tags=["focus", "wcag22"]),

    WcagCriterion("2.5.3", "Label in Name",              ConformanceLevel.A,
                  version=WcagVersion.V21, principle=WcagPrinciple.OPERABLE,
                  description="Label visível incluída no nome acessível do componente.",
                  test_rules=["label-content-name-mismatch"],
                  tags=["labels", "voice-control"]),

    # ── Principle 3: Understandable ───────────────────────────────────────
    WcagCriterion("3.1.1", "Language of Page",           ConformanceLevel.A,
                  principle=WcagPrinciple.UNDERSTANDABLE,
                  description="Idioma padrão da página determinável programaticamente.",
                  test_rules=["html-has-lang", "html-lang-valid"],
                  tags=["language", "html"]),

    WcagCriterion("3.2.1", "On Focus",                   ConformanceLevel.A,
                  principle=WcagPrinciple.UNDERSTANDABLE,
                  description="Receber foco não inicia mudança de contexto.",
                  tags=["focus", "behavior"]),

    WcagCriterion("3.3.1", "Error Identification",       ConformanceLevel.A,
                  principle=WcagPrinciple.UNDERSTANDABLE,
                  description="Erros de entrada identificados e descritos em texto.",
                  test_rules=["aria-required-attr", "label"],
                  tags=["forms", "errors"]),

    WcagCriterion("3.3.2", "Labels or Instructions",     ConformanceLevel.A,
                  principle=WcagPrinciple.UNDERSTANDABLE,
                  description="Labels ou instruções fornecidos para entradas de usuário.",
                  test_rules=["label"],
                  tags=["forms", "labels"]),

    WcagCriterion("3.3.7", "Redundant Entry",            ConformanceLevel.A,
                  version=WcagVersion.V22, principle=WcagPrinciple.UNDERSTANDABLE,
                  description="Informação previamente inserida não solicitada novamente (WCAG 2.2).",
                  tags=["forms", "wcag22"]),

    WcagCriterion("3.3.8", "Accessible Authentication",  ConformanceLevel.AA,
                  version=WcagVersion.V22, principle=WcagPrinciple.UNDERSTANDABLE,
                  description="Autenticação não exige testes cognitivos (WCAG 2.2).",
                  tags=["auth", "wcag22", "cognitive"]),

    # ── Principle 4: Robust ───────────────────────────────────────────────
    WcagCriterion("4.1.1", "Parsing",                    ConformanceLevel.A,
                  principle=WcagPrinciple.ROBUST,
                  description="HTML sem erros de parsing críticos.",
                  test_rules=["duplicate-id"],
                  tags=["html", "parsing"]),

    WcagCriterion("4.1.2", "Name, Role, Value",          ConformanceLevel.A,
                  principle=WcagPrinciple.ROBUST,
                  description="Componentes têm nome, role e valor acessíveis.",
                  how_to_meet="Use ARIA roles e atributos corretamente.",
                  test_rules=["aria-required-attr", "aria-roles", "button-name"],
                  tags=["aria", "semantics"]),

    WcagCriterion("4.1.3", "Status Messages",            ConformanceLevel.AA,
                  version=WcagVersion.V21, principle=WcagPrinciple.ROBUST,
                  description="Mensagens de status comunicadas sem receber foco.",
                  test_rules=["aria-live-region-attr"],
                  tags=["aria", "live-regions", "notifications"]),
]

# Fast lookup by number
CRITERIA_BY_NUMBER: dict[str, WcagCriterion] = {
    c.number: c for c in WCAG_CRITERIA
}


def get_criterion(number: str) -> WcagCriterion | None:
    return CRITERIA_BY_NUMBER.get(number)


def criteria_by_level(level: ConformanceLevel) -> list[WcagCriterion]:
    return [c for c in WCAG_CRITERIA if c.level == level]


def aa_criteria() -> list[WcagCriterion]:
    """Retorna todos os critérios A + AA (mínimo para conformidade AA)."""
    return [c for c in WCAG_CRITERIA
            if c.level in (ConformanceLevel.A, ConformanceLevel.AA)]
