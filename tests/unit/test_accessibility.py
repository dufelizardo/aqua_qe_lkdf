"""
tests/unit/test_accessibility.py
AQuA-QE LKDF v1.4 — Unit Tests: Accessibility Layer
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


from runtime_core.accessibility.wcag.models import (
    AccessibilityViolation,
    ConformanceLevel,
    ConformanceReport,
    ViolationImpact,
    WCAG_CRITERIA,
    aa_criteria,
    criteria_by_level,
    get_criterion,
)
from runtime_core.accessibility.axe.adapter import AxeAdapter
from runtime_core.accessibility.nielsen.heuristics import (
    HEURISTICS,
    HeuristicId,
    NielsenEvaluator,
    NielsenSeverity,
    NielsenViolation,
)
from runtime_core.accessibility.scenarios.generator import (
    AccessibilityScenarioGenerator,
)


# ---------------------------------------------------------------------------
# Sample axe-core output
# ---------------------------------------------------------------------------

AXE_OUTPUT_WITH_VIOLATIONS = {
    "violations": [
        {
            "id":          "color-contrast",
            "impact":      "serious",
            "description": "Elements must have sufficient color contrast",
            "help":        "Ensure the contrast ratio of text is at least 4.5:1",
            "helpUrl":     "https://dequeuniversity.com/rules/axe/4.9/color-contrast",
            "tags":        ["cat.color", "wcag2aa", "wcag143"],
            "nodes": [
                {
                    "html":   "<button class='btn-gray'>Submit</button>",
                    "target": ["button.btn-gray"],
                    "any":    [{"id": "color-contrast", "message": "ratio 2.5:1 < 4.5:1"}],
                    "all":    [],
                    "none":   [],
                }
            ],
        },
        {
            "id":          "image-alt",
            "impact":      "critical",
            "description": "Images must have alternate text",
            "help":        "Ensure <img> elements have alternate text",
            "helpUrl":     "https://dequeuniversity.com/rules/axe/4.9/image-alt",
            "tags":        ["cat.text-alternatives", "wcag2a", "wcag111"],
            "nodes": [
                {
                    "html":   "<img src='logo.png'>",
                    "target": ["img.logo"],
                    "any":    [],
                    "all":    [],
                    "none":   [],
                }
            ],
        },
        {
            "id":     "label",
            "impact": "critical",
            "description": "Form elements must have labels",
            "help":   "Ensure every form element has a label",
            "tags":   ["cat.forms", "wcag2a", "wcag131"],
            "nodes":  [{"html": "<input type='email'>", "target": ["input[type='email']"]}],
        },
    ],
    "passes": [
        {"id": "html-has-lang"},
        {"id": "document-title"},
    ],
    "inapplicable": [{"id": "video-caption"}],
    "incomplete":   [],
}

AXE_OUTPUT_CLEAN = {
    "violations":   [],
    "passes":       [{"id": "html-has-lang"}, {"id": "color-contrast"}, {"id": "image-alt"}],
    "inapplicable": [],
    "incomplete":   [],
}


# ===========================================================================
# WCAG Models
# ===========================================================================

class TestWcagModels:

    def test_criteria_catalog_not_empty(self):
        assert len(WCAG_CRITERIA) > 20

    def test_criteria_by_number_lookup(self):
        c = get_criterion("1.1.1")
        assert c is not None
        assert c.name == "Non-text Content"
        assert c.level == ConformanceLevel.A

    def test_get_criterion_unknown_returns_none(self):
        assert get_criterion("9.9.9") is None

    def test_aa_criteria_includes_a_and_aa(self):
        aa = aa_criteria()
        levels = {c.level for c in aa}
        assert ConformanceLevel.A  in levels
        assert ConformanceLevel.AA in levels
        assert ConformanceLevel.AAA not in levels

    def test_criteria_by_level_a(self):
        a_only = criteria_by_level(ConformanceLevel.A)
        assert all(c.level == ConformanceLevel.A for c in a_only)

    def test_wcag_criterion_full_ref(self):
        c = get_criterion("1.4.3")
        assert "1.4.3" in c.full_ref
        assert "AA"    in c.full_ref

    def test_wcag22_criteria_present(self):
        from runtime_core.accessibility.wcag.models import WcagVersion
        wcag22 = [c for c in WCAG_CRITERIA if c.version == WcagVersion.V22]
        assert len(wcag22) > 0

    def test_violation_is_blocking_critical(self):
        v = AccessibilityViolation(impact=ViolationImpact.CRITICAL)
        assert v.is_blocking is True

    def test_violation_is_blocking_serious(self):
        v = AccessibilityViolation(impact=ViolationImpact.SERIOUS)
        assert v.is_blocking is True

    def test_violation_not_blocking_moderate(self):
        v = AccessibilityViolation(impact=ViolationImpact.MODERATE)
        assert v.is_blocking is False

    def test_violation_wcag_ref_from_criterion(self):
        c = get_criterion("1.4.3")
        v = AccessibilityViolation(criterion=c)
        assert "1.4.3" in v.wcag_ref

    def test_conformance_report_aa_violations(self):
        c_a  = get_criterion("1.1.1")   # A
        c_aa = get_criterion("1.4.3")   # AA
        v1 = AccessibilityViolation(criterion=c_a,  impact=ViolationImpact.CRITICAL)
        v2 = AccessibilityViolation(criterion=c_aa, impact=ViolationImpact.SERIOUS)
        report = ConformanceReport(violations=[v1, v2])
        assert len(report.a_violations)  == 1
        assert len(report.aa_violations) == 1

    def test_conformance_report_is_aa_compliant_when_no_violations(self):
        report = ConformanceReport(violations=[], passes=["html-has-lang"])
        assert report.is_aa_compliant is True

    def test_conformance_report_not_compliant_with_violations(self):
        c = get_criterion("1.4.3")
        v = AccessibilityViolation(criterion=c, impact=ViolationImpact.SERIOUS)
        report = ConformanceReport(violations=[v])
        assert report.is_aa_compliant is False

    def test_compliance_pct_perfect(self):
        report = ConformanceReport(violations=[], passes=["a", "b", "c"])
        assert report.compliance_pct == 1.0

    def test_compliance_pct_partial(self):
        c = get_criterion("1.4.3")
        v = AccessibilityViolation(criterion=c)
        report = ConformanceReport(violations=[v], passes=["x", "y", "z"])
        assert 0.0 < report.compliance_pct < 1.0

    def test_report_summary_structure(self):
        report = ConformanceReport(violations=[], passes=["a"])
        summary = report.summary()
        for key in ("url", "target_level", "is_aa_compliant", "compliance_pct",
                    "violations_total", "violations_a", "violations_aa", "tool"):
            assert key in summary


# ===========================================================================
# Axe Adapter
# ===========================================================================

class TestAxeAdapter:
    adapter = AxeAdapter()

    def test_parse_axe_json_returns_report(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS, url="/login")
        assert isinstance(report, ConformanceReport)

    def test_parse_axe_violations_count(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        assert len(report.violations) == 3

    def test_parse_axe_passes_count(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        assert len(report.passes) == 2

    def test_parse_axe_impact_mapped(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        impacts = {v.impact for v in report.violations}
        assert ViolationImpact.SERIOUS  in impacts
        assert ViolationImpact.CRITICAL in impacts

    def test_parse_axe_rule_id_preserved(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        rule_ids = {v.rule_id for v in report.violations}
        assert "color-contrast" in rule_ids
        assert "image-alt"      in rule_ids

    def test_parse_axe_criterion_resolved(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        # image-alt → 1.1.1
        img_violations = [v for v in report.violations if v.rule_id == "image-alt"]
        assert img_violations[0].criterion is not None
        assert img_violations[0].criterion.number == "1.1.1"

    def test_parse_axe_element_extracted(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        contrast_v = [v for v in report.violations if v.rule_id == "color-contrast"]
        assert contrast_v[0].element == "button.btn-gray"

    def test_parse_axe_tool_set(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        assert report.tool == "axe-core"

    def test_parse_axe_clean_output(self):
        report = self.adapter.parse_axe_json(AXE_OUTPUT_CLEAN)
        assert len(report.violations) == 0
        assert report.is_aa_compliant is True

    def test_axe_inject_script_not_empty(self):
        script = AxeAdapter.axe_inject_script()
        assert len(script) > 100
        assert "axe.run" in script

    def test_parse_pa11y_json(self):
        pa11y_output = [
            {
                "code":     "WCAG2AA.Principle1.Guideline1_1.1_1_1.H37",
                "type":     "error",
                "message":  "Img element missing an alt attribute",
                "selector": "img.logo",
                "context":  "<img src='logo.png'>",
            }
        ]
        report = self.adapter.parse_pa11y_json(pa11y_output, url="/home")
        assert len(report.violations) == 1
        assert report.violations[0].tool == "pa11y"
        assert report.tool == "pa11y"


# ===========================================================================
# Nielsen Heuristics
# ===========================================================================

class TestNielsenHeuristics:
    evaluator = NielsenEvaluator()

    def test_catalog_has_10_heuristics(self):
        assert len(HEURISTICS) == 10

    def test_all_heuristics_have_checklist(self):
        for h in HEURISTICS.values():
            assert len(h.checklist) >= 3, f"{h.name} has fewer than 3 checklist items"

    def test_all_heuristics_have_examples(self):
        for h in HEURISTICS.values():
            assert len(h.examples) >= 3

    def test_evaluate_checklist_all_pass(self):
        h     = HEURISTICS[HeuristicId.VISIBILITY_OF_SYSTEM_STATUS]
        answers = {item: True for item in h.checklist}
        results = self.evaluator.evaluate_checklist(
            HeuristicId.VISIBILITY_OF_SYSTEM_STATUS, answers
        )
        assert all(r.passed for r in results)

    def test_evaluate_checklist_some_fail(self):
        h     = HEURISTICS[HeuristicId.ERROR_PREVENTION]
        items = h.checklist
        answers = {item: (i % 2 == 0) for i, item in enumerate(items)}
        results = self.evaluator.evaluate_checklist(HeuristicId.ERROR_PREVENTION, answers)
        failed = [r for r in results if not r.passed]
        passed = [r for r in results if r.passed]
        assert len(failed) > 0
        assert len(passed) > 0

    def test_score_perfect(self):
        h = HEURISTICS[HeuristicId.CONSISTENCY_AND_STANDARDS]
        answers = {item: True for item in h.checklist}
        score = self.evaluator.score(HeuristicId.CONSISTENCY_AND_STANDARDS, answers)
        assert score == 1.0

    def test_score_zero(self):
        h = HEURISTICS[HeuristicId.USER_CONTROL_AND_FREEDOM]
        answers = {item: False for item in h.checklist}
        score = self.evaluator.score(HeuristicId.USER_CONTROL_AND_FREEDOM, answers)
        assert score == 0.0

    def test_score_all_returns_all_heuristics(self):
        answers = {h_id: {} for h_id in HeuristicId}
        scores = self.evaluator.score_all(answers)
        assert len(scores) == 10

    def test_overall_score_perfect(self):
        answers = {
            h_id: {item: True for item in h.checklist}
            for h_id, h in HEURISTICS.items()
        }
        score = self.evaluator.overall_score(answers)
        assert score == 1.0

    def test_violations_from_checklist(self):
        answers = {
            HeuristicId.VISIBILITY_OF_SYSTEM_STATUS: {
                "Operações longas têm indicador de progresso?": False,
                "Feedback confirmado após ações do usuário (salvar, enviar)?": True,
            }
        }
        violations = self.evaluator.violations_from_checklist(
            answers, component="Dashboard"
        )
        assert len(violations) == 1
        assert violations[0].heuristic == HeuristicId.VISIBILITY_OF_SYSTEM_STATUS
        assert violations[0].component == "Dashboard"

    def test_nielsen_violation_is_blocking(self):
        v = NielsenViolation(severity=NielsenSeverity.MAJOR)
        assert v.is_blocking is True

    def test_nielsen_violation_not_blocking_minor(self):
        v = NielsenViolation(severity=NielsenSeverity.MINOR)
        assert v.is_blocking is False

    def test_nielsen_violation_heuristic_name(self):
        v = NielsenViolation(heuristic=HeuristicId.ERROR_PREVENTION)
        assert "Error" in v.heuristic_name


# ===========================================================================
# Accessibility Scenario Generator
# ===========================================================================

class TestAccessibilityScenarioGenerator:
    generator = AccessibilityScenarioGenerator()

    def test_from_violations_returns_scenarios(self):
        adapter = AxeAdapter()
        report  = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        assert len(scenarios) > 0

    def test_from_violations_deduplicates_by_rule(self):
        # Two violations with same rule_id
        c = get_criterion("1.4.3")
        v1 = AccessibilityViolation(criterion=c, rule_id="color-contrast",
                                    element="button.a", impact=ViolationImpact.SERIOUS)
        v2 = AccessibilityViolation(criterion=c, rule_id="color-contrast",
                                    element="p.b", impact=ViolationImpact.SERIOUS)
        scenarios = self.generator.from_violations([v1, v2])
        # Should produce only 1 scenario (deduplicated by rule_id)
        assert len(scenarios) == 1

    def test_from_violations_high_priority_for_blocking(self):
        c = get_criterion("1.1.1")
        v = AccessibilityViolation(criterion=c, rule_id="image-alt",
                                   impact=ViolationImpact.CRITICAL)
        scenarios = self.generator.from_violations([v])
        assert scenarios[0].priority == "HIGH"

    def test_from_violations_steps_not_empty(self):
        adapter   = AxeAdapter()
        report    = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        for s in scenarios:
            assert len(s.steps) >= 3

    def test_scenario_steps_follow_bdd(self):
        adapter   = AxeAdapter()
        report    = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        for s in scenarios:
            keywords = [step.split()[0] for step in s.steps]
            assert "Dado" in keywords
            assert "Então" in keywords

    def test_scenarios_have_wcag_tags(self):
        adapter   = AxeAdapter()
        report    = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        for s in scenarios:
            assert "accessibility" in s.tags
            assert "wcag" in s.tags

    def test_from_nielsen_violations(self):
        violations = [
            NielsenViolation(
                heuristic=HeuristicId.ERROR_PREVENTION,
                severity=NielsenSeverity.MAJOR,
                component="LoginForm",
                checklist_item="Validação inline nos campos de formulário?",
                recommendation="Adicione validação em tempo real",
            )
        ]
        scenarios = self.generator.from_nielsen_violations(violations)
        assert len(scenarios) == 1
        assert scenarios[0].category == "nielsen"
        assert "nielsen" in scenarios[0].tags

    def test_from_nielsen_skips_non_blocking(self):
        violations = [
            NielsenViolation(
                heuristic=HeuristicId.AESTHETIC_AND_MINIMALIST_DESIGN,
                severity=NielsenSeverity.COSMETIC,   # not blocking
            )
        ]
        scenarios = self.generator.from_nielsen_violations(violations)
        assert len(scenarios) == 0

    def test_aa_preventive_scenarios(self):
        scenarios = self.generator.aa_preventive_scenarios(url="/login")
        assert len(scenarios) > 0
        assert all(s.category == "wcag-preventive" for s in scenarios)

    def test_from_criteria_generates_scenarios(self):
        criteria  = [get_criterion("1.1.1"), get_criterion("1.4.3")]
        scenarios = self.generator.from_criteria(criteria, url="/home")
        assert len(scenarios) > 0

    def test_to_flow_produces_valid_flow(self):
        adapter   = AxeAdapter()
        report    = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        flow      = self.generator.to_flow(scenarios, flow_name="A11yFlow")
        assert flow.name == "A11yFlow"
        assert len(flow.scenarios) > 0
        for s in flow.scenarios:
            assert len(s.steps) > 0

    def test_to_dsl_string_valid_format(self):
        adapter   = AxeAdapter()
        report    = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        dsl       = self.generator.to_dsl_string(scenarios, flow_name="A11yFlow")
        assert "@flow A11yFlow" in dsl
        assert "@scenario"      in dsl
        assert "Dado"           in dsl
        assert "Então"          in dsl

    def test_to_flow_steps_have_correct_types(self):
        from shared.models import StepType
        adapter   = AxeAdapter()
        report    = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)
        scenarios = self.generator.from_violations(report.violations)
        flow      = self.generator.to_flow(scenarios)
        for scenario in flow.scenarios:
            types = {s.step_type for s in scenario.steps}
            assert StepType.GIVEN in types
            assert StepType.THEN  in types

    def test_quality_policy_wcag_gate_integration(self):
        """
        Verifica que o ConformanceReport alimenta corretamente o WCAG_AA_COMPLIANCE gate.
        """
        from runtime_core.quality_policy.evaluators import EvaluationContext
        from runtime_core.quality_policy.models import (
            GateDefinition, GateType, PolicyAction, GateResult
        )
        from runtime_core.quality_policy.evaluators import WcagAAComplianceEvaluator

        adapter = AxeAdapter()
        report  = adapter.parse_axe_json(AXE_OUTPUT_WITH_VIOLATIONS)

        ctx = EvaluationContext()
        ctx.wcag_aa_violations    = len(report.aa_violations)
        ctx.wcag_aa_compliance_pct = report.compliance_pct

        gate = GateDefinition(
            gate_type=GateType.WCAG_AA_COMPLIANCE,
            name="WCAG AA",
            threshold=1.0,
            action=PolicyAction.BLOCK,
        )
        evaluator = WcagAAComplianceEvaluator()
        evaluation = evaluator.evaluate(gate, ctx)

        # Has violations → should fail
        assert evaluation.result == GateResult.FAILED
        assert evaluation.blocking_failure is True
