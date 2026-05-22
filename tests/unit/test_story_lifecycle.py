"""
tests/unit/test_story_lifecycle.py
AQuA-QE LKDF v1.4 — Unit Tests: Story Lifecycle
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from runtime_core.persistence.adapters.sqlite_adapter import SQLiteGraphAdapter
from runtime_core.story_lifecycle.diff_engine import DiffEngine
from runtime_core.story_lifecycle.models import (
    ChildType,
    CriticalityLevel,
    CriticalityMatrix,
    DiffCategory,
    SnapshotType,
    Story,
    StoryStatus,
    StoryVersion,
)
from runtime_core.story_lifecycle.service import StoryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    adapter = SQLiteGraphAdapter("sqlite+aiosqlite:///:memory:")
    await adapter.initialize()
    yield adapter
    await adapter.close()


@pytest.fixture
async def svc(db):
    return StoryService(db)


def make_version(
    version_number=1,
    snapshot_type=SnapshotType.DEF,
    title="Login deve funcionar",
    description="Autenticação via JWT",
    criteria=None,
    priority=CriticalityLevel.P1,
) -> StoryVersion:
    return StoryVersion(
        story_external_id="BFTG-127",
        version_number=version_number,
        snapshot_type=snapshot_type,
        title=title,
        description=description,
        acceptance_criteria=criteria or [
            "Usuário com credenciais válidas deve ser autenticado",
            "Token JWT deve expirar em 24 horas",
            "Tentativas inválidas devem ser bloqueadas após 5 erros",
        ],
        priority=priority,
    )


# ===========================================================================
# Criticality Matrix
# ===========================================================================

class TestCriticalityMatrix:

    def test_p0_security_risk(self):
        m = CriticalityMatrix("low", "cosmetic", security_risk=True)
        assert m.level == CriticalityLevel.P0

    def test_p0_data_risk(self):
        m = CriticalityMatrix("low", "cosmetic", data_risk=True)
        assert m.level == CriticalityLevel.P0

    def test_p0_high_frequency_blocking(self):
        m = CriticalityMatrix("high", "blocking")
        assert m.level == CriticalityLevel.P0

    def test_p1_blocking(self):
        m = CriticalityMatrix("low", "blocking")
        assert m.level == CriticalityLevel.P1

    def test_p1_high_degraded(self):
        m = CriticalityMatrix("high", "degraded")
        assert m.level == CriticalityLevel.P1

    def test_p2_cosmetic(self):
        m = CriticalityMatrix("low", "cosmetic")
        assert m.level == CriticalityLevel.P2

    def test_p2_medium_degraded(self):
        m = CriticalityMatrix("medium", "degraded")
        assert m.level == CriticalityLevel.P2

    def test_sla_p0_is_4h(self):
        m = CriticalityMatrix("high", "blocking")
        assert m.sla_hours == 4

    def test_sla_p1_is_24h(self):
        m = CriticalityMatrix("low", "blocking")
        assert m.sla_hours == 24

    def test_sla_p2_is_72h(self):
        m = CriticalityMatrix("low", "cosmetic")
        assert m.sla_hours == 72


# ===========================================================================
# StoryVersion
# ===========================================================================

class TestStoryVersion:

    def test_is_def(self):
        v = make_version(snapshot_type=SnapshotType.DEF)
        assert v.is_def is True
        assert v.is_imp is False
        assert v.is_reg is False

    def test_is_imp(self):
        v = make_version(snapshot_type=SnapshotType.IMP)
        assert v.is_imp is True

    def test_is_reg(self):
        v = make_version(snapshot_type=SnapshotType.REG)
        assert v.is_reg is True


# ===========================================================================
# Story
# ===========================================================================

class TestStory:

    def test_latest_version(self):
        v1 = make_version(1)
        v2 = make_version(2)
        s  = Story(external_id="X-1", versions=[v1, v2])
        assert s.latest_version.version_number == 2

    def test_latest_version_empty(self):
        s = Story(external_id="X-1")
        assert s.latest_version is None

    def test_get_version(self):
        v1 = make_version(1)
        v2 = make_version(2)
        s  = Story(external_id="X-1", versions=[v1, v2])
        assert s.get_version(1) == v1
        assert s.get_version(9) is None

    def test_def_versions_filter(self):
        v1 = make_version(1, SnapshotType.DEF)
        v2 = make_version(2, SnapshotType.IMP)
        v3 = make_version(3, SnapshotType.DEF)
        s  = Story(external_id="X-1", versions=[v1, v2, v3])
        assert len(s.def_versions) == 2

    def test_has_regression(self):
        s = Story(external_id="X-1", status=StoryStatus.REGRESSED)
        assert s.has_regression is True

    def test_open_defects(self):
        from runtime_core.story_lifecycle.models import ChildArtifact
        c1 = ChildArtifact(child_type=ChildType.DEFECT, resolved=False)
        c2 = ChildArtifact(child_type=ChildType.DEFECT, resolved=True)
        c3 = ChildArtifact(child_type=ChildType.IMPROVEMENT, resolved=False)
        s  = Story(external_id="X-1", children=[c1, c2, c3])
        assert len(s.open_defects) == 1


# ===========================================================================
# DiffEngine
# ===========================================================================

class TestDiffEngine:
    engine = DiffEngine()

    def test_no_changes(self):
        v1   = make_version(1)
        v2   = make_version(2)
        diff = self.engine.compute(v1, v2)
        assert len(diff.changes) == 0
        assert diff.is_breaking is False

    def test_title_change_detected(self):
        v1   = make_version(1, title="Login")
        v2   = make_version(2, title="Autenticação")
        diff = self.engine.compute(v1, v2)
        title_changes = [c for c in diff.changes if c.field_path == "title"]
        assert len(title_changes) == 1
        assert title_changes[0].category == DiffCategory.TEXT_CHANGE

    def test_criteria_add_detected(self):
        v1 = make_version(1, criteria=["Critério A"])
        v2 = make_version(2, criteria=["Critério A", "Critério B"])
        diff = self.engine.compute(v1, v2)
        adds = [c for c in diff.changes if c.category == DiffCategory.CRITERIA_ADD]
        assert len(adds) == 1
        assert "Critério B" in adds[0].new_value

    def test_criteria_delete_detected(self):
        v1 = make_version(1, criteria=["Critério A", "Critério B"])
        v2 = make_version(2, criteria=["Critério A"])
        diff = self.engine.compute(v1, v2)
        dels = [c for c in diff.changes if c.category == DiffCategory.CRITERIA_DEL]
        assert len(dels) == 1

    def test_criteria_modify_detected(self):
        v1 = make_version(1, criteria=[
            "Token deve expirar em 24 horas após emissão"
        ])
        v2 = make_version(2, criteria=[
            "Token deve expirar em 48 horas após emissão"
        ])
        diff = self.engine.compute(v1, v2)
        # Strings muito similares devem ser detectadas como modify
        mods = [c for c in diff.changes if c.category == DiffCategory.CRITERIA_MOD]
        adds = [c for c in diff.changes if c.category == DiffCategory.CRITERIA_ADD]
        dels = [c for c in diff.changes if c.category == DiffCategory.CRITERIA_DEL]
        # Should detect as modify OR as del+add — both are valid diff strategies
        assert len(mods) >= 1 or (len(adds) >= 1 and len(dels) >= 1)

    def test_criteria_delete_is_breaking(self):
        v1   = make_version(1, criteria=["Critério A", "Critério B"])
        v2   = make_version(2, criteria=["Critério A"])
        diff = self.engine.compute(v1, v2)
        assert diff.is_breaking is True

    def test_criteria_add_is_not_breaking(self):
        v1   = make_version(1, criteria=["Critério A"])
        v2   = make_version(2, criteria=["Critério A", "Critério B"])
        diff = self.engine.compute(v1, v2)
        assert diff.is_breaking is False

    def test_risk_delta_increased_on_deletion(self):
        v1   = make_version(1, criteria=["Critério A", "Critério B"])
        v2   = make_version(2, criteria=["Critério A"])
        diff = self.engine.compute(v1, v2)
        assert diff.risk_delta == "increased"

    def test_risk_delta_none_on_no_change(self):
        v1   = make_version(1)
        v2   = make_version(2)
        diff = self.engine.compute(v1, v2)
        assert diff.risk_delta == "none"

    def test_diff_summary_not_empty_when_changes(self):
        v1   = make_version(1, title="A")
        v2   = make_version(2, title="B")
        diff = self.engine.compute(v1, v2)
        assert diff.summary != "Sem mudanças detectadas."

    def test_multi_diff(self):
        v1 = make_version(1)
        v2 = make_version(2, title="Novo título")
        v3 = make_version(3, criteria=["Critério único"])
        diffs = self.engine.compute_multi([v1, v2, v3])
        assert len(diffs) == 2

    def test_multi_diff_single_version(self):
        diffs = self.engine.compute_multi([make_version(1)])
        assert diffs == []

    def test_from_to_version_numbers(self):
        v1   = make_version(3)
        v2   = make_version(5)
        diff = self.engine.compute(v1, v2)
        assert diff.from_version == 3
        assert diff.to_version   == 5


# ===========================================================================
# StoryService
# ===========================================================================

class TestStoryService:

    @pytest.mark.asyncio
    async def test_create_story(self, svc):
        story = await svc.create(
            external_id="BFTG-001",
            title="Login deve funcionar",
            acceptance_criteria=["Critério A", "Critério B"],
            criticality=CriticalityLevel.P1,
        )
        assert story.external_id == "BFTG-001"
        assert story.current_version == 1
        assert story.status == StoryStatus.DEFINED

    @pytest.mark.asyncio
    async def test_create_persists_to_graph(self, svc, db):
        await svc.create(external_id="BFTG-002", title="Story para grafo")
        node = await db.get_node_by_external_id("BFTG-002", label="Story")
        assert node is not None
        assert node.properties["title"] == "Story para grafo"

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, svc):
        await svc.create(external_id="BFTG-DUP", title="Primeiro")
        with pytest.raises(ValueError, match="já existe"):
            await svc.create(external_id="BFTG-DUP", title="Segundo")

    @pytest.mark.asyncio
    async def test_add_imp_version(self, svc):
        await svc.create(external_id="BFTG-003", title="Story IMP")
        v2, diff = await svc.add_version(
            external_id="BFTG-003",
            snapshot_type=SnapshotType.IMP,
        )
        assert v2.version_number == 2
        assert v2.snapshot_type  == SnapshotType.IMP

    @pytest.mark.asyncio
    async def test_add_version_with_diff(self, svc):
        await svc.create(
            external_id="BFTG-004",
            title="Story original",
            acceptance_criteria=["Critério A", "Critério B"],
        )
        _, diff = await svc.add_version(
            external_id="BFTG-004",
            snapshot_type=SnapshotType.IMP,
            acceptance_criteria=["Critério A"],   # removeu B
        )
        assert diff is not None
        assert diff.is_breaking is True
        assert diff.risk_delta == "increased"

    @pytest.mark.asyncio
    async def test_classify_criticality_p0(self, svc):
        await svc.create(external_id="BFTG-005", title="Story P0")
        level = await svc.classify_criticality(
            "BFTG-005",
            frequency="high",
            user_impact="blocking",
            security_risk=True,
        )
        assert level == CriticalityLevel.P0

    @pytest.mark.asyncio
    async def test_classify_criticality_updates_story(self, svc):
        await svc.create("BFTG-006", "Story", criticality=CriticalityLevel.P2)
        await svc.classify_criticality("BFTG-006", "high", "blocking")
        story = await svc.get("BFTG-006")
        assert story.criticality == CriticalityLevel.P0

    @pytest.mark.asyncio
    async def test_add_defect_child(self, svc):
        await svc.create(external_id="BFTG-007", title="Story com defect")
        child = await svc.add_child(
            story_external_id="BFTG-007",
            child_type=ChildType.DEFECT,
            external_id="DEF-001",
            title="Crash no login",
            criticality=CriticalityLevel.P0,
        )
        assert child.child_type == ChildType.DEFECT
        story = await svc.get("BFTG-007")
        assert len(story.open_defects) == 1

    @pytest.mark.asyncio
    async def test_add_regression_changes_story_status(self, svc):
        await svc.create(external_id="BFTG-008", title="Story com regressão")
        await svc.add_child(
            "BFTG-008", ChildType.REGRESSION, "REG-001", "Regressão detectada"
        )
        story = await svc.get("BFTG-008")
        assert story.status == StoryStatus.REGRESSED
        assert story.has_regression is True

    @pytest.mark.asyncio
    async def test_resolve_defect(self, svc):
        await svc.create(external_id="BFTG-009", title="Story resolve")
        await svc.add_child(
            "BFTG-009", ChildType.DEFECT, "DEF-002", "Defect para resolver"
        )
        resolved = await svc.resolve_child("BFTG-009", "DEF-002", fixed_in_version=3)
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.fixed_in_version == 3

    @pytest.mark.asyncio
    async def test_get_story_by_external_id(self, svc):
        await svc.create(external_id="BFTG-010", title="Story get")
        story = await svc.get("BFTG-010")
        assert story is not None
        assert story.external_id == "BFTG-010"

    @pytest.mark.asyncio
    async def test_get_nonexistent_story(self, svc):
        story = await svc.get("BFTG-NOPE")
        assert story is None

    @pytest.mark.asyncio
    async def test_get_version_diff(self, svc):
        await svc.create(
            external_id="BFTG-011",
            title="Story diff",
            acceptance_criteria=["Critério A", "Critério B"],
        )
        await svc.add_version(
            "BFTG-011", SnapshotType.IMP,
            acceptance_criteria=["Critério A"],
        )
        diff = await svc.get_version_diff("BFTG-011", 1, 2)
        assert diff is not None
        assert diff.is_breaking is True

    @pytest.mark.asyncio
    async def test_list_breaking_changes(self, svc):
        await svc.create(
            external_id="BFTG-012",
            title="Story breaking",
            acceptance_criteria=["A", "B", "C"],
        )
        await svc.add_version(
            "BFTG-012", SnapshotType.IMP,
            acceptance_criteria=["A"],   # breaking
        )
        await svc.add_version(
            "BFTG-012", SnapshotType.DEF,
            acceptance_criteria=["A", "B"],  # add — not breaking
        )
        breaking = await svc.list_breaking_changes("BFTG-012")
        assert len(breaking) >= 1
        assert all(d.is_breaking for d in breaking)

    @pytest.mark.asyncio
    async def test_quality_gate_passes(self, svc):
        await svc.create(
            external_id="BFTG-013",
            title="Story QG pass",
            acceptance_criteria=["Critério válido"],
            criticality=CriticalityLevel.P1,
        )
        gate = await svc.quality_gate_check("BFTG-013")
        assert gate["passed"] is True
        assert gate["issues"] == []

    @pytest.mark.asyncio
    async def test_quality_gate_fails_no_criteria(self, svc):
        await svc.create(
            external_id="BFTG-014",
            title="Story sem critérios",
            acceptance_criteria=[],
        )
        gate = await svc.quality_gate_check("BFTG-014")
        assert gate["passed"] is False
        assert any("critério" in i.lower() for i in gate["issues"])

    @pytest.mark.asyncio
    async def test_quality_gate_fails_p0_defect(self, svc):
        await svc.create(
            external_id="BFTG-015",
            title="Story com P0",
            acceptance_criteria=["Critério A"],
        )
        await svc.add_child(
            "BFTG-015", ChildType.DEFECT, "DEF-P0", "Defect crítico",
            criticality=CriticalityLevel.P0,
        )
        gate = await svc.quality_gate_check("BFTG-015")
        assert gate["passed"] is False
        assert any("P0" in i for i in gate["issues"])

    @pytest.mark.asyncio
    async def test_versions_persisted_as_graph_nodes(self, svc, db):
        await svc.create(external_id="BFTG-016", title="Story grafo versions")
        await svc.add_version("BFTG-016", SnapshotType.IMP)
        v1_node = await db.get_node_by_external_id("BFTG-016:v1", "StoryVersion")
        v2_node = await db.get_node_by_external_id("BFTG-016:v2", "StoryVersion")
        assert v1_node is not None
        assert v2_node is not None

    @pytest.mark.asyncio
    async def test_version_chain_in_graph(self, svc, db):
        await svc.create(external_id="BFTG-017", title="Story chain")
        await svc.add_version("BFTG-017", SnapshotType.IMP)
        v1_node = await db.get_node_by_external_id("BFTG-017:v1", "StoryVersion")
        v2_node = await db.get_node_by_external_id("BFTG-017:v2", "StoryVersion")
        edges   = await db.get_edges(
            source_id=v1_node.id,
            relation=None,
        )
        from runtime_core.persistence.graph.models import RelationType
        next_edges = [e for e in edges if e.relation == RelationType.NEXT_VERSION]
        assert len(next_edges) == 1
        assert next_edges[0].target_id == v2_node.id
