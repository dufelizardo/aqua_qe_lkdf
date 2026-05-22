"""
tests/unit/test_quality_policy.py
AQuA-QE LKDF v1.4 — Unit Tests: Quality Policy Engine
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from runtime_core.quality_policy.evaluators import EvaluationContext
from runtime_core.quality_policy.engine import PolicyEngine, PolicyGateStage
from runtime_core.quality_policy.models import (
    GateDefinition,
    GateResult,
    GateScope,
    GateType,
    PolicyAction,
    QualityPolicy,
    default_release_policy,
    default_story_policy,
)
from runtime_core.pipeline.fanout import FanOutPipeline, PipelineContext, PipelineStage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return PolicyEngine(repository=None)


def perfect_story_ctx() -> EvaluationContext:
    return PolicyEngine.build_story_context(
        has_acceptance_criteria=True,
        acceptance_criteria_count=3,
        criticality_classified=True,
        open_p0_defects=0,
        critical_ambiguities=0,
        ambiguity_score=0.1,
        has_bidirectional_traceability=True,
        traceability_coverage=1.0,
        unreviewed_breaking_changes=0,
    )


def perfect_release_ctx() -> EvaluationContext:
    return PolicyEngine.build_release_context(
        requirements_total=10,
        requirements_with_scenarios=9,
        requirements_in_rtm=9,
        execution_total=50,
        execution_passed=48,
        open_p0_defects=0,
        wcag_aa_violations=0,
        wcag_aa_compliance_pct=1.0,
        traceability_coverage=1.0,
        has_bidirectional_traceability=True,
    )


# ===========================================================================
# Policy Models
# ===========================================================================

class TestPolicyModels:

    def test_default_story_policy_has_mandatory_gates(self):
        p = default_story_policy()
        assert len(p.mandatory_gates) > 0

    def test_default_release_policy_has_wcag_gate(self):
        p = default_release_policy()
        assert p.has_gate(GateType.WCAG_AA_COMPLIANCE)

    def test_release_wcag_gate_is_mandatory(self):
        p = default_release_policy()
        wcag = p.get_gate(GateType.WCAG_AA_COMPLIANCE)
        assert wcag is not None
        assert wcag.mandatory is True
        assert wcag.action == PolicyAction.BLOCK

    def test_gate_display_threshold_percentage(self):
        g = GateDefinition(
            gate_type=GateType.SCENARIO_COVERAGE,
            name="Coverage",
            threshold=0.85,
        )
        assert g.display_threshold == "85%"

    def test_gate_is_blocking(self):
        g = GateDefinition(gate_type=GateType.CUSTOM, action=PolicyAction.BLOCK)
        assert g.is_blocking is True

    def test_gate_is_not_blocking_warn(self):
        g = GateDefinition(gate_type=GateType.CUSTOM, action=PolicyAction.WARN)
        assert g.is_blocking is False

    def test_policy_report_gate_summary(self):
        from runtime_core.quality_policy.models import GateEvaluation, PolicyReport
        from uuid import uuid4
        evals = [
            GateEvaluation(uuid4(), GateType.ACCEPTANCE_CRITERIA, "A",
                           GateResult.PASSED, action=PolicyAction.BLOCK),
            GateEvaluation(uuid4(), GateType.NO_OPEN_P0_DEFECTS, "B",
                           GateResult.FAILED, action=PolicyAction.BLOCK),
            GateEvaluation(uuid4(), GateType.CUSTOM, "C",
                           GateResult.WARNING, action=PolicyAction.WARN),
        ]
        report = PolicyReport(evaluations=evals, blocking_failures=1)
        summary = report.gate_summary
        assert summary["total"]   == 3
        assert summary["passed"]  == 1
        assert summary["failed"]  == 1
        assert summary["warning"] == 1


# ===========================================================================
# Individual Evaluators
# ===========================================================================

class TestEvaluators:

    def _gate(self, gate_type: GateType, threshold: float = 1.0,
              action: PolicyAction = PolicyAction.BLOCK) -> GateDefinition:
        return GateDefinition(
            gate_type=gate_type,
            name=gate_type.value,
            threshold=threshold,
            action=action,
        )

    def _evaluate(self, gate_type, ctx, threshold=1.0, action=PolicyAction.BLOCK):
        from runtime_core.quality_policy.evaluators import get_evaluator
        gate = self._gate(gate_type, threshold, action)
        evaluator = get_evaluator(gate_type)
        assert evaluator is not None, f"No evaluator for {gate_type}"
        return evaluator.evaluate(gate, ctx)

    # --- AcceptanceCriteria ---
    def test_acceptance_criteria_passes(self):
        ctx = EvaluationContext()
        ctx.has_acceptance_criteria = True
        ctx.acceptance_criteria_count = 2
        r = self._evaluate(GateType.ACCEPTANCE_CRITERIA, ctx)
        assert r.result == GateResult.PASSED

    def test_acceptance_criteria_fails_empty(self):
        ctx = EvaluationContext()
        ctx.has_acceptance_criteria = False
        ctx.acceptance_criteria_count = 0
        r = self._evaluate(GateType.ACCEPTANCE_CRITERIA, ctx)
        assert r.result == GateResult.FAILED
        assert r.blocking_failure is True

    # --- Criticality ---
    def test_criticality_passes_when_classified(self):
        ctx = EvaluationContext()
        ctx.criticality_classified = True
        r = self._evaluate(GateType.CRITICALITY_CLASSIFIED, ctx)
        assert r.result == GateResult.PASSED

    def test_criticality_fails_when_unclassified(self):
        ctx = EvaluationContext()
        ctx.criticality_classified = False
        r = self._evaluate(GateType.CRITICALITY_CLASSIFIED, ctx)
        assert r.result == GateResult.FAILED

    # --- No Critical Ambiguity ---
    def test_no_critical_ambiguity_passes(self):
        ctx = EvaluationContext()
        ctx.critical_ambiguities = 0
        r = self._evaluate(GateType.NO_CRITICAL_AMBIGUITY, ctx)
        assert r.result == GateResult.PASSED

    def test_no_critical_ambiguity_fails(self):
        ctx = EvaluationContext()
        ctx.critical_ambiguities = 2
        r = self._evaluate(GateType.NO_CRITICAL_AMBIGUITY, ctx)
        assert r.result == GateResult.FAILED

    # --- No Open P0 ---
    def test_no_p0_defects_passes(self):
        ctx = EvaluationContext()
        ctx.open_p0_defects = 0
        r = self._evaluate(GateType.NO_OPEN_P0_DEFECTS, ctx)
        assert r.result == GateResult.PASSED

    def test_no_p0_defects_fails(self):
        ctx = EvaluationContext()
        ctx.open_p0_defects = 1
        r = self._evaluate(GateType.NO_OPEN_P0_DEFECTS, ctx)
        assert r.result == GateResult.FAILED

    # --- Scenario Coverage ---
    def test_scenario_coverage_passes(self):
        ctx = EvaluationContext()
        ctx.requirements_total = 10
        ctx.requirements_with_scenarios = 9
        r = self._evaluate(GateType.SCENARIO_COVERAGE, ctx, threshold=0.80)
        assert r.result == GateResult.PASSED
        assert r.actual_value == pytest.approx(0.9, abs=0.01)

    def test_scenario_coverage_fails(self):
        ctx = EvaluationContext()
        ctx.requirements_total = 10
        ctx.requirements_with_scenarios = 7
        r = self._evaluate(GateType.SCENARIO_COVERAGE, ctx, threshold=0.80)
        assert r.result == GateResult.FAILED

    def test_scenario_coverage_skipped_no_requirements(self):
        ctx = EvaluationContext()
        ctx.requirements_total = 0
        r = self._evaluate(GateType.SCENARIO_COVERAGE, ctx)
        assert r.result == GateResult.SKIPPED

    # --- Execution Pass Rate ---
    def test_execution_pass_rate_passes(self):
        ctx = EvaluationContext()
        ctx.execution_total = 100
        ctx.execution_passed = 95
        r = self._evaluate(GateType.EXECUTION_PASS_RATE, ctx, threshold=0.90)
        assert r.result == GateResult.PASSED

    def test_execution_pass_rate_fails(self):
        ctx = EvaluationContext()
        ctx.execution_total = 100
        ctx.execution_passed = 85
        r = self._evaluate(GateType.EXECUTION_PASS_RATE, ctx, threshold=0.90)
        assert r.result == GateResult.FAILED

    def test_execution_pass_rate_skipped(self):
        ctx = EvaluationContext()
        ctx.execution_total = 0
        r = self._evaluate(GateType.EXECUTION_PASS_RATE, ctx)
        assert r.result == GateResult.SKIPPED

    # --- RTM Coverage ---
    def test_rtm_coverage_passes(self):
        ctx = EvaluationContext()
        ctx.requirements_total = 10
        ctx.requirements_in_rtm = 9
        r = self._evaluate(GateType.RTM_COVERAGE, ctx, threshold=0.85)
        assert r.result == GateResult.PASSED

    def test_rtm_coverage_fails(self):
        ctx = EvaluationContext()
        ctx.requirements_total = 10
        ctx.requirements_in_rtm = 5
        r = self._evaluate(GateType.RTM_COVERAGE, ctx, threshold=0.85)
        assert r.result == GateResult.FAILED

    # --- WCAG AA ---
    def test_wcag_aa_passes_no_violations(self):
        ctx = EvaluationContext()
        ctx.wcag_aa_violations = 0
        ctx.wcag_aa_compliance_pct = 1.0
        r = self._evaluate(GateType.WCAG_AA_COMPLIANCE, ctx)
        assert r.result == GateResult.PASSED

    def test_wcag_aa_fails_with_violations(self):
        ctx = EvaluationContext()
        ctx.wcag_aa_violations = 3
        ctx.wcag_aa_compliance_pct = 0.85
        r = self._evaluate(GateType.WCAG_AA_COMPLIANCE, ctx)
        assert r.result == GateResult.FAILED
        assert r.blocking_failure is True

    # --- Bidirectional Traceability ---
    def test_traceability_passes(self):
        ctx = EvaluationContext()
        ctx.has_bidirectional_traceability = True
        ctx.traceability_coverage = 1.0
        r = self._evaluate(GateType.BIDIRECTIONAL_TRACEABILITY, ctx)
        assert r.result == GateResult.PASSED

    def test_traceability_warns_when_action_warn(self):
        ctx = EvaluationContext()
        ctx.has_bidirectional_traceability = False
        ctx.traceability_coverage = 0.5
        r = self._evaluate(
            GateType.BIDIRECTIONAL_TRACEABILITY, ctx,
            threshold=1.0, action=PolicyAction.WARN
        )
        # WARN action on failure → WARNING result (not blocking)
        assert r.result in (GateResult.FAILED, GateResult.WARNING)
        assert r.blocking_failure is False

    # --- Breaking Changes ---
    def test_no_breaking_changes_passes(self):
        ctx = EvaluationContext()
        ctx.unreviewed_breaking_changes = 0
        r = self._evaluate(GateType.NO_BREAKING_CHANGES_UNREVIEWED, ctx)
        assert r.result == GateResult.PASSED

    def test_breaking_changes_fails(self):
        ctx = EvaluationContext()
        ctx.unreviewed_breaking_changes = 2
        r = self._evaluate(GateType.NO_BREAKING_CHANGES_UNREVIEWED, ctx)
        assert r.result == GateResult.FAILED

    # --- Ambiguity Score ---
    def test_ambiguity_score_passes(self):
        ctx = EvaluationContext()
        ctx.ambiguity_score = 0.2
        r = self._evaluate(GateType.AMBIGUITY_SCORE, ctx, threshold=0.5)
        assert r.result == GateResult.PASSED

    def test_ambiguity_score_warns(self):
        ctx = EvaluationContext()
        ctx.ambiguity_score = 0.8
        r = self._evaluate(GateType.AMBIGUITY_SCORE, ctx,
                           threshold=0.5, action=PolicyAction.WARN)
        assert r.result == GateResult.WARNING


# ===========================================================================
# Policy Engine
# ===========================================================================

class TestPolicyEngine:

    @pytest.mark.asyncio
    async def test_evaluate_story_perfect_context_passes(self, engine):
        ctx    = perfect_story_ctx()
        report = await engine.evaluate_story("BFTG-001", ctx)
        assert report.passed is True
        assert report.blocking_failures == 0

    @pytest.mark.asyncio
    async def test_evaluate_story_no_criteria_fails(self, engine):
        ctx = PolicyEngine.build_story_context(
            has_acceptance_criteria=False,
            acceptance_criteria_count=0,
            criticality_classified=True,
        )
        report = await engine.evaluate_story("BFTG-002", ctx)
        assert report.passed is False
        assert report.blocking_failures >= 1

    @pytest.mark.asyncio
    async def test_evaluate_story_p0_defect_fails(self, engine):
        ctx = perfect_story_ctx()
        ctx.open_p0_defects = 1
        report = await engine.evaluate_story("BFTG-003", ctx)
        assert report.passed is False

    @pytest.mark.asyncio
    async def test_evaluate_release_perfect_passes(self, engine):
        ctx    = perfect_release_ctx()
        report = await engine.evaluate_release("REL-001", ctx)
        assert report.passed is True

    @pytest.mark.asyncio
    async def test_evaluate_release_wcag_violation_fails(self, engine):
        ctx = perfect_release_ctx()
        ctx.wcag_aa_violations = 1
        ctx.wcag_aa_compliance_pct = 0.95
        report = await engine.evaluate_release("REL-002", ctx)
        assert report.passed is False
        failed_names = [e.gate_name for e in report.failed_gates()]
        assert any("WCAG" in n for n in failed_names)

    @pytest.mark.asyncio
    async def test_evaluate_release_low_coverage_fails(self, engine):
        ctx = PolicyEngine.build_release_context(
            requirements_total=10,
            requirements_with_scenarios=6,   # 60% < 80%
            execution_total=50,
            execution_passed=48,
            wcag_aa_compliance_pct=1.0,
        )
        report = await engine.evaluate_release("REL-003", ctx)
        assert report.passed is False

    @pytest.mark.asyncio
    async def test_evaluate_by_name_returns_report(self, engine):
        ctx    = perfect_story_ctx()
        report = await engine.evaluate_by_name("Default Story Policy", "BFTG-004", ctx)
        assert report is not None
        assert report.policy_name == "Default Story Policy"

    @pytest.mark.asyncio
    async def test_evaluate_by_name_unknown_returns_none(self, engine):
        ctx    = EvaluationContext()
        report = await engine.evaluate_by_name("NonExistent Policy", "X", ctx)
        assert report is None

    @pytest.mark.asyncio
    async def test_custom_policy_evaluation(self, engine):
        custom_policy = QualityPolicy(
            name="Custom Test Policy",
            scope=GateScope.MODULE,
            gates=[
                GateDefinition(
                    gate_type=GateType.EXECUTION_PASS_RATE,
                    name="Pass rate 95%",
                    threshold=0.95,
                    action=PolicyAction.BLOCK,
                ),
                GateDefinition(
                    gate_type=GateType.SCENARIO_COVERAGE,
                    name="Coverage 90%",
                    threshold=0.90,
                    action=PolicyAction.WARN,
                ),
            ],
        )
        engine.register(custom_policy)

        ctx = EvaluationContext()
        ctx.execution_total = 100
        ctx.execution_passed = 97
        ctx.requirements_total = 10
        ctx.requirements_with_scenarios = 8   # 80% < 90% → WARNING

        report = await engine.evaluate_by_name("Custom Test Policy", "MOD-001", ctx)
        assert report.passed is True          # WARN doesn't block
        assert report.warnings >= 1

    @pytest.mark.asyncio
    async def test_fail_fast_stops_at_first_blocking_failure(self, engine):
        policy = default_story_policy()
        policy.fail_fast = True

        ctx = EvaluationContext()
        ctx.has_acceptance_criteria = False   # will fail first gate
        ctx.criticality_classified = False    # would fail too, but fail_fast stops

        report = await engine.evaluate(policy, ctx, "BFTG-FF")
        assert not report.passed
        # With fail_fast, fewer gates evaluated
        assert len(report.evaluations) < len(policy.gates)

    @pytest.mark.asyncio
    async def test_composite_evaluation(self, engine):
        ctx      = perfect_story_ctx()
        policies = [default_story_policy()]
        reports  = await engine.evaluate_composite(policies, ctx, "BFTG-COMP")
        assert len(reports) == 1
        assert reports[0].passed is True

    def test_list_policies(self, engine):
        policies = engine.list_policies()
        assert "Default Story Policy"   in policies
        assert "Default Release Policy" in policies

    def test_compliance_summary_structure(self, engine):
        summary = engine.compliance_summary()
        for key in ("total_evaluations", "passed", "failed",
                    "compliance_rate", "blocking_failures", "warnings"):
            assert key in summary

    @pytest.mark.asyncio
    async def test_failed_subjects_tracked(self, engine):
        ctx = PolicyEngine.build_story_context(
            has_acceptance_criteria=False,
        )
        await engine.evaluate_story("BAD-STORY", ctx)
        assert "BAD-STORY" in engine.failed_subjects()

    @pytest.mark.asyncio
    async def test_report_persisted_to_graph(self):
        from runtime_core.persistence.adapters.sqlite_adapter import SQLiteGraphAdapter
        db     = SQLiteGraphAdapter("sqlite+aiosqlite:///:memory:")
        await db.initialize()
        eng    = PolicyEngine(repository=db)
        ctx    = perfect_story_ctx()
        await eng.evaluate_story("BFTG-PERSIST", ctx)
        nodes  = await db.find_nodes(label="PolicyReport")
        assert len(nodes) >= 1
        assert nodes[0].properties["subject_id"] == "BFTG-PERSIST"
        await db.close()


# ===========================================================================
# Pipeline Integration
# ===========================================================================

class TestPolicyGateStage:

    @pytest.mark.asyncio
    async def test_gate_stage_passes_good_context(self):
        engine = PolicyEngine()

        class SetupStage(PipelineStage):
            async def execute(self, ctx):
                ctx.inputs["subject_id"]         = "STORY-001"
                ctx.inputs["evaluation_context"] = perfect_story_ctx()
                return "setup_done"

        stages = [
            SetupStage("setup", "Setup"),
            PolicyGateStage(
                "gate", "Quality Gate",
                policy_name="Default Story Policy",
                engine=engine,
                depends_on=["setup"],
            ),
        ]
        pipeline = FanOutPipeline("test", stages)
        ctx      = PipelineContext()
        result   = await pipeline.run(ctx)

        from runtime_core.pipeline.fanout import StageStatus
        assert result.status == StageStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_gate_stage_fails_bad_context(self):
        engine = PolicyEngine()

        class SetupStage(PipelineStage):
            async def execute(self, ctx):
                ctx.inputs["subject_id"]         = "BAD-STORY"
                ctx.inputs["evaluation_context"] = PolicyEngine.build_story_context(
                    has_acceptance_criteria=False,
                )
                return "setup_done"

        stages = [
            SetupStage("setup", "Setup"),
            PolicyGateStage(
                "gate", "Quality Gate",
                policy_name="Default Story Policy",
                engine=engine,
                depends_on=["setup"],
            ),
        ]
        pipeline = FanOutPipeline("test", stages, fail_fast=True)
        ctx      = PipelineContext()
        result   = await pipeline.run(ctx)

        from runtime_core.pipeline.fanout import StageStatus
        assert result.status == StageStatus.FAILED

    @pytest.mark.asyncio
    async def test_optional_gate_stage_does_not_fail_pipeline(self):
        engine = PolicyEngine()

        class SetupStage(PipelineStage):
            async def execute(self, ctx):
                ctx.inputs["subject_id"]         = "OPT-STORY"
                ctx.inputs["evaluation_context"] = PolicyEngine.build_story_context(
                    has_acceptance_criteria=False,
                )
                return "setup"

        stages = [
            SetupStage("setup", "Setup"),
            PolicyGateStage(
                "gate", "Optional Gate",
                policy_name="Default Story Policy",
                engine=engine,
                depends_on=["setup"],
                optional=True,         # won't block pipeline
            ),
        ]
        pipeline = FanOutPipeline("test", stages)
        ctx      = PipelineContext()
        result   = await pipeline.run(ctx)

        from runtime_core.pipeline.fanout import StageStatus
        # Optional gate failure = SKIPPED in result, pipeline still COMPLETED
        gate_result = next(
            (r for r in result.stage_results if r.stage_id == "gate"), None
        )
        assert gate_result is not None
        assert gate_result.status in (StageStatus.SKIPPED, StageStatus.FAILED)
        # But pipeline itself completes because setup passed
        completed = [r for r in result.stage_results if r.stage_id == "setup"]
        assert completed[0].status == StageStatus.COMPLETED
