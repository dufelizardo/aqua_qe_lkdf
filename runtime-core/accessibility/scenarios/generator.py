"""
runtime_core/accessibility/scenarios/generator.py
AQuA-QE LKDF v1.4 — Accessibility Scenario Generator

Gera cenários de teste de acessibilidade automaticamente a partir de:
  - Violações WCAG detectadas pelo axe-core / Pa11y
  - Falhas nas heurísticas de Nielsen
  - Critérios WCAG relevantes para o contexto da Story

Integra com o Scenario Engine e o DSL do LKDF para produzir
flows testáveis em Robot Framework / Playwright.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import structlog

from runtime_core.accessibility.wcag.models import (
    AccessibilityViolation,
    ConformanceLevel,
    ConformanceReport,
    WcagCriterion,
    aa_criteria,
)
from runtime_core.accessibility.nielsen.heuristics import (
    HEURISTICS,
    HeuristicId,
    NielsenViolation,
)
from shared.models import (
    AdapterType,
    Flow,
    Priority,
    Scenario,
    SemanticStep,
    StepKeyword,
    StepType,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Accessibility scenario types
# ---------------------------------------------------------------------------

@dataclass
class AccessibilityScenario:
    """Cenário de teste de acessibilidade gerado."""
    id:            str                  = field(default_factory=lambda: str(uuid4())[:8])
    name:          str                  = ""
    category:      str                  = ""    # wcag | nielsen | keyboard | screen-reader
    criterion_ref: str                  = ""    # "1.4.3", "H2-1", etc.
    steps:         list[str]            = field(default_factory=list)
    priority:      str                  = "HIGH"
    tags:          list[str]            = field(default_factory=list)
    tool_hint:     str                  = ""    # axe-core | manual | screen-reader
    metadata:      dict[str, Any]       = field(default_factory=dict)

    def to_dsl(self, flow_name: str = "AccessibilityFlow", req_ref: str = "") -> str:
        """Gera DSL LKDF para este scenario."""
        steps_dsl = "\n    ".join(self.steps)
        return (
            f"  @scenario {self.name}\n"
            f"    {steps_dsl}"
        )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class AccessibilityScenarioGenerator:
    """
    Gera scenarios de acessibilidade a partir de violações e critérios WCAG.
    Produz DSL LKDF pronto para execução.
    """

    # ------------------------------------------------------------------
    # From WCAG violations
    # ------------------------------------------------------------------

    def from_violations(
        self,
        violations: list[AccessibilityViolation],
        url:        str = "",
    ) -> list[AccessibilityScenario]:
        """Gera um scenario para cada violação detectada."""
        scenarios: list[AccessibilityScenario] = []
        seen: set[str] = set()   # deduplicate by rule_id

        for v in violations:
            key = v.rule_id or (v.criterion.number if v.criterion else v.criterion_ref)
            if key in seen:
                continue
            seen.add(key)

            scenario = self._violation_to_scenario(v, url)
            if scenario:
                scenarios.append(scenario)

        log.info("a11y_scenarios_from_violations",
                 violations=len(violations), scenarios=len(scenarios))
        return scenarios

    def _violation_to_scenario(
        self,
        v:   AccessibilityViolation,
        url: str,
    ) -> AccessibilityScenario | None:
        rule_id    = v.rule_id or "unknown"
        criterion  = v.criterion
        ref        = criterion.number if criterion else v.criterion_ref

        # Generate scenario steps based on rule
        steps = self._steps_for_rule(rule_id, v.element, url, criterion)
        if not steps:
            return None

        name = self._scenario_name(rule_id, criterion)
        return AccessibilityScenario(
            name=name,
            category="wcag",
            criterion_ref=ref,
            steps=steps,
            priority="HIGH" if v.is_blocking else "MEDIUM",
            tags=["accessibility", "wcag", f"wcag-{ref.replace('.','')}", rule_id],
            tool_hint="axe-core",
            metadata={"element": v.element, "description": v.description},
        )

    def _steps_for_rule(
        self,
        rule_id:   str,
        element:   str,
        url:       str,
        criterion: WcagCriterion | None,
    ) -> list[str]:
        """Retorna steps DSL específicos para cada tipo de violação."""
        loc = element or "body"
        page = url or "a página"

        templates: dict[str, list[str]] = {
            "image-alt": [
                f"Dado que o usuário está em {page}",
                "Quando o leitor de tela navega pelos elementos da página",
                f"Então é esperado que a imagem '{loc}' tenha texto alternativo descritivo",
                "E é esperado que o atributo alt não esteja vazio ou ausente",
            ],
            "color-contrast": [
                f"Dado que o usuário está em {page}",
                f"Quando o texto no elemento '{loc}' é visualizado",
                "Então é esperado que a proporção de contraste seja de ao menos 4.5:1 para texto normal",
                "E é esperado que a proporção seja de ao menos 3:1 para texto grande",
            ],
            "label": [
                f"Dado que o usuário está no formulário em {page}",
                f"Quando o campo de entrada '{loc}' recebe foco",
                "Então é esperado que um label visível e associado esteja presente",
                "E é esperado que o leitor de tela anuncie o propósito do campo",
            ],
            "document-title": [
                f"Dado que o usuário acessa {page}",
                "Quando a página carrega completamente",
                "Então é esperado que o título da página seja descritivo e único",
                "E é esperado que o título reflita o conteúdo ou propósito da página",
            ],
            "html-has-lang": [
                f"Dado que o usuário acessa {page}",
                "Quando o leitor de tela processa o documento",
                "Então é esperado que o elemento html tenha o atributo lang definido",
                "E é esperado que o valor de lang corresponda ao idioma do conteúdo",
            ],
            "button-name": [
                f"Dado que o usuário está em {page}",
                f"Quando o botão '{loc}' recebe foco via teclado",
                "Então é esperado que o botão tenha nome acessível descritivo",
                "E é esperado que o leitor de tela anuncie a ação do botão",
            ],
            "tabindex": [
                f"Dado que o usuário está em {page}",
                "Quando o usuário navega pelo conteúdo usando a tecla Tab",
                f"Então é esperado que o elemento '{loc}' seja acessível via teclado",
                "E é esperado que a ordem de foco seja lógica e previsível",
            ],
            "link-name": [
                f"Dado que o usuário está em {page}",
                f"Quando o link '{loc}' é focado pelo leitor de tela",
                "Então é esperado que o link tenha texto descritivo do seu destino",
                "E é esperado que o texto não seja genérico como 'clique aqui' ou 'saiba mais'",
            ],
            "skip-link": [
                f"Dado que o usuário chega em {page} via teclado",
                "Quando o usuário pressiona Tab pela primeira vez",
                "Então é esperado que um link 'Pular para o conteúdo principal' apareça",
                "E é esperado que ao ativar o link o foco vá para o conteúdo principal",
            ],
            "heading-order": [
                f"Dado que o usuário está em {page}",
                "Quando o leitor de tela navega pelos headings da página",
                "Então é esperado que a hierarquia de headings seja sequencial (h1, h2, h3...)",
                "E é esperado que não haja saltos na hierarquia de headings",
            ],
            "focus-visible": [
                f"Dado que o usuário está em {page}",
                "Quando o usuário navega pelos elementos interativos usando Tab",
                "Então é esperado que o elemento com foco tenha indicador visual claro",
                "E é esperado que o indicador de foco não seja removido via CSS",
            ],
            "aria-required-attr": [
                f"Dado que o usuário está em {page}",
                f"Quando o componente ARIA '{loc}' é processado",
                "Então é esperado que todos os atributos ARIA obrigatórios estejam presentes",
                "E é esperado que os valores ARIA sejam válidos para o role usado",
            ],
            "duplicate-id": [
                f"Dado que o usuário acessa {page}",
                "Quando o HTML da página é validado",
                "Então é esperado que todos os atributos id sejam únicos no documento",
                "E é esperado que referências ARIA apontem para ids existentes",
            ],
        }

        return templates.get(rule_id, self._generic_steps(rule_id, loc, page, criterion))

    @staticmethod
    def _generic_steps(
        rule_id:   str,
        element:   str,
        url:       str,
        criterion: WcagCriterion | None,
    ) -> list[str]:
        ref = criterion.number if criterion else "WCAG"
        return [
            f"Dado que o usuário acessa {url or 'a página'}",
            f"Quando a ferramenta de acessibilidade analisa o elemento '{element}'",
            f"Então é esperado que o critério {ref} ({rule_id}) seja satisfeito",
            "E é esperado que nenhuma violação de acessibilidade seja reportada",
        ]

    @staticmethod
    def _scenario_name(rule_id: str, criterion: WcagCriterion | None) -> str:
        names: dict[str, str] = {
            "image-alt":        "ImgAlt_TextoAlternativo",
            "color-contrast":   "ColorContrast_PropoçãoMínima",
            "label":            "FormLabel_CampoRotulado",
            "document-title":   "PageTitle_TítuloDescritivo",
            "html-has-lang":    "HtmlLang_IdiomaDefinido",
            "button-name":      "ButtonName_BotãoAcessível",
            "tabindex":         "TabOrder_NavegaçãoTeclado",
            "link-name":        "LinkName_TextoDescritivo",
            "skip-link":        "SkipLink_PularConteúdo",
            "heading-order":    "HeadingOrder_HierarquiaSequencial",
            "focus-visible":    "FocusVisible_IndicadorFoco",
            "aria-required-attr": "AriaAttr_AtributosObrigatórios",
            "duplicate-id":     "DuplicateId_IDsÚnicos",
        }
        name = names.get(rule_id, f"A11y_{rule_id.replace('-', '_').title()}")
        if criterion:
            name = f"WCAG{criterion.number.replace('.', '')}_{name}"
        return name

    # ------------------------------------------------------------------
    # From Nielsen violations
    # ------------------------------------------------------------------

    def from_nielsen_violations(
        self,
        violations: list[NielsenViolation],
    ) -> list[AccessibilityScenario]:
        """Gera scenarios de UX a partir de violações das heurísticas de Nielsen."""
        scenarios: list[AccessibilityScenario] = []

        for v in violations:
            if not v.is_blocking:
                continue

            h = HEURISTICS.get(v.heuristic)
            steps = self._nielsen_steps(v, h)

            scenarios.append(AccessibilityScenario(
                name=f"Nielsen_H{v.heuristic.value}_{v.heuristic.name.replace(' ','_')[:30]}",
                category="nielsen",
                criterion_ref=f"H{v.heuristic.value}",
                steps=steps,
                priority="HIGH" if v.severity.value >= 3 else "MEDIUM",
                tags=["ux", "nielsen", f"heuristic-{v.heuristic.value}"],
                tool_hint="manual",
                metadata={"component": v.component, "severity": v.severity.value},
            ))

        return scenarios

    @staticmethod
    def _nielsen_steps(v: NielsenViolation, h: Any) -> list[str]:
        component = v.component or "o componente"
        return [
            f"Dado que o usuário acessa {component}",
            f"Quando o usuário interage com a interface",
            f"Então é esperado que a heurística '{h.name if h else v.heuristic.name}' seja satisfeita",
            f"E é esperado que '{v.checklist_item}' esteja correto",
            f"E é esperado que '{v.recommendation}' esteja implementado",
        ]

    # ------------------------------------------------------------------
    # Proactive — generate from WCAG criteria before violations
    # ------------------------------------------------------------------

    def from_criteria(
        self,
        criteria:  list[WcagCriterion],
        url:       str = "",
        component: str = "",
    ) -> list[AccessibilityScenario]:
        """
        Gera scenarios preventivos a partir de critérios WCAG,
        ANTES de qualquer scan ser executado.
        Útil para incluir acessibilidade no planejamento de testes.
        """
        scenarios: list[AccessibilityScenario] = []
        target    = url or component or "a interface"

        for criterion in criteria:
            if not criterion.test_rules:
                continue
            for rule in criterion.test_rules[:1]:  # 1 scenario per criterion
                steps = self._steps_for_rule(rule, "", target, criterion)
                scenarios.append(AccessibilityScenario(
                    name=f"WCAG{criterion.number.replace('.','')}_Preventivo_{rule.replace('-','_').title()}",
                    category="wcag-preventive",
                    criterion_ref=criterion.number,
                    steps=steps,
                    priority="HIGH" if criterion.level == ConformanceLevel.A else "MEDIUM",
                    tags=["accessibility", "preventive", f"wcag{criterion.number.replace('.','')}", *criterion.tags],
                    tool_hint="axe-core",
                ))

        return scenarios

    def aa_preventive_scenarios(self, url: str = "") -> list[AccessibilityScenario]:
        """Gera scenarios preventivos para todos os critérios A + AA."""
        return self.from_criteria(aa_criteria(), url=url)

    # ------------------------------------------------------------------
    # To Flow DSL
    # ------------------------------------------------------------------

    def to_flow(
        self,
        scenarios:    list[AccessibilityScenario],
        flow_name:    str            = "AccessibilityFlow",
        req_ref:      str            = "",
        adapter:      AdapterType    = AdapterType.PLAYWRIGHT,
    ) -> Flow:
        """Converte lista de AccessibilityScenario em Flow LKDF."""
        lkdf_scenarios: list[Scenario] = []

        for a_scenario in scenarios:
            steps: list[SemanticStep] = []
            kw_map = {
                "Dado":  (StepKeyword.DADO,   StepType.GIVEN),
                "Quando":(StepKeyword.QUANDO, StepType.WHEN),
                "Então": (StepKeyword.ENTAO,  StepType.THEN),
                "E":     (StepKeyword.E,      StepType.AND),
            }
            last_type = StepType.GIVEN
            for raw_step in a_scenario.steps:
                first = raw_step.split()[0] if raw_step.split() else "E"
                kw, stype = kw_map.get(first, (StepKeyword.E, StepType.AND))
                if stype == StepType.AND:
                    stype = last_type
                else:
                    last_type = stype
                steps.append(SemanticStep(
                    keyword=kw,
                    step_type=stype,
                    text=raw_step,
                ))

            lkdf_scenarios.append(Scenario(
                name=a_scenario.name,
                description=f"WCAG {a_scenario.criterion_ref} — {a_scenario.category}",
                steps=steps,
                tags=a_scenario.tags,
                requirement_ref=req_ref,
            ))

        return Flow(
            name=flow_name,
            requirement_ref=req_ref,
            adapter=adapter,
            priority=Priority.HIGH,
            scenarios=lkdf_scenarios,
            metadata={"generated_by": "AccessibilityScenarioGenerator"},
        )

    def to_dsl_string(
        self,
        scenarios: list[AccessibilityScenario],
        flow_name: str = "AccessibilityFlow",
        req_ref:   str = "",
    ) -> str:
        """Gera string DSL LKDF para todos os scenarios."""
        lines = [
            f"# Flow: {flow_name}",
            f"# Requirement: {req_ref or 'WCAG-2.1-AA'}",
            "# Adapter: playwright",
            "# Priority: HIGH",
            "# Generated-by: AccessibilityScenarioGenerator",
            "",
            f"@flow {flow_name.replace(' ', '')}",
        ]
        for s in scenarios:
            lines.append(f"\n  @scenario {s.name}")
            for step in s.steps:
                lines.append(f"    {step}")
        return "\n".join(lines)
