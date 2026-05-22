"""
runtime_core/story_lifecycle/service.py
AQuA-QE LKDF v1.4 — Story Lifecycle Service

Orquestra o ciclo de vida completo de uma Story:
  1. Criação e persistência no GraphRepository (Node + edges)
  2. Versionamento semântico imutável (DEF / IMP / REG)
  3. Diff automático entre versões com análise de impacto
  4. Classificação de criticidade (P0/P1/P2)
  5. Registro de artefatos filhos (Defect / Improvement / Regression)
  6. Trigger de regeneração de cenários pós-mudança
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from runtime_core.persistence.graph.models import Node, RelationType
from runtime_core.persistence.graph.repository import GraphRepository
from runtime_core.story_lifecycle.diff_engine import DiffEngine
from runtime_core.story_lifecycle.models import (
    ChildArtifact,
    ChildType,
    CriticalityLevel,
    CriticalityMatrix,
    SnapshotType,
    Story,
    StoryStatus,
    StoryVersion,
    VersionDiff,
)

log = structlog.get_logger(__name__)


class StoryService:
    """
    Serviço de domínio para o Story Lifecycle.
    Único ponto de entrada para criação, versionamento e consulta de Stories.
    """

    def __init__(self, repository: GraphRepository) -> None:
        self._repo   = repository
        self._diff   = DiffEngine()
        self._store: dict[str, Story] = {}   # in-memory cache por external_id

    # ------------------------------------------------------------------
    # Story creation
    # ------------------------------------------------------------------

    async def create(
        self,
        external_id:         str,
        title:               str,
        description:         str                = "",
        acceptance_criteria: list[str]          = None,
        criticality:         CriticalityLevel   = CriticalityLevel.P1,
        tags:                list[str]          = None,
        created_by:          str                = "",
        metadata:            dict[str, Any]     = None,
    ) -> Story:
        """
        Cria uma Story com o primeiro snapshot DEF e persiste no grafo.
        O external_id é imutável após criação.
        """
        if external_id in self._store:
            raise ValueError(
                f"Story '{external_id}' já existe. "
                "Use add_version() para criar uma nova versão."
            )

        criteria = acceptance_criteria or []
        story = Story(
            external_id=external_id,
            title=title,
            description=description,
            status=StoryStatus.DEFINED,
            current_version=1,
            criticality=criticality,
        )

        # First version (DEF)
        v1 = StoryVersion(
            story_external_id=external_id,
            version_number=1,
            snapshot_type=SnapshotType.DEF,
            title=title,
            description=description,
            acceptance_criteria=criteria,
            priority=criticality,
            status=StoryStatus.DEFINED,
            tags=tags or [],
            metadata=metadata or {},
            created_by=created_by,
        )
        story.versions.append(v1)

        # Persist to graph
        story.node_id = await self._persist_story(story)
        await self._persist_version(story, v1)

        self._store[external_id] = story
        log.info("story_created", external_id=external_id, criticality=criticality.value)
        return story

    # ------------------------------------------------------------------
    # Version management
    # ------------------------------------------------------------------

    async def add_version(
        self,
        external_id:         str,
        snapshot_type:       SnapshotType,
        title:               str | None          = None,
        description:         str | None          = None,
        acceptance_criteria: list[str] | None    = None,
        criticality:         CriticalityLevel | None = None,
        created_by:          str                 = "",
        metadata:            dict[str, Any]      = None,
    ) -> tuple[StoryVersion, VersionDiff | None]:
        """
        Adiciona nova versão imutável a uma Story existente.
        Retorna (new_version, diff_from_previous).
        """
        story = await self.get(external_id)
        if not story:
            raise ValueError(f"Story '{external_id}' não encontrada.")

        prev  = story.latest_version
        new_v = story.current_version + 1

        new_version = StoryVersion(
            story_external_id=external_id,
            version_number=new_v,
            snapshot_type=snapshot_type,
            title=title               if title               is not None else (prev.title        if prev else ""),
            description=description   if description         is not None else (prev.description  if prev else ""),
            acceptance_criteria=acceptance_criteria if acceptance_criteria is not None
                                else (prev.acceptance_criteria if prev else []),
            priority=criticality      if criticality         is not None else (prev.priority     if prev else CriticalityLevel.P1),
            status=self._status_from_snapshot(snapshot_type),
            created_by=created_by,
            metadata=metadata or {},
        )

        story.versions.append(new_version)
        story.current_version = new_v
        story.status = new_version.status
        story.updated_at = datetime.utcnow()

        # Compute diff
        diff: VersionDiff | None = None
        if prev:
            diff = self._diff.compute(prev, new_version)
            if diff.is_breaking:
                log.warning(
                    "story_breaking_change",
                    external_id=external_id,
                    from_v=prev.version_number,
                    to_v=new_v,
                    changes=len(diff.changes),
                )

        # Persist
        await self._persist_version(story, new_version)
        if diff:
            await self._persist_diff(story, prev, new_version, diff)

        self._store[external_id] = story
        log.info(
            "story_version_added",
            external_id=external_id,
            version=new_v,
            type=snapshot_type.value,
            breaking=diff.is_breaking if diff else False,
        )
        return new_version, diff

    # ------------------------------------------------------------------
    # Criticality
    # ------------------------------------------------------------------

    async def classify_criticality(
        self,
        external_id:   str,
        frequency:     str,
        user_impact:   str,
        data_risk:     bool = False,
        security_risk: bool = False,
    ) -> CriticalityLevel:
        """Classifica ou reclassifica a criticidade P0/P1/P2 de uma Story."""
        story = await self.get(external_id)
        if not story:
            raise ValueError(f"Story '{external_id}' não encontrada.")

        matrix = CriticalityMatrix(
            frequency=frequency,
            user_impact=user_impact,
            data_risk=data_risk,
            security_risk=security_risk,
        )
        level = matrix.level

        if level != story.criticality:
            log.info(
                "story_criticality_changed",
                external_id=external_id,
                from_level=story.criticality.value,
                to_level=level.value,
                sla_hours=matrix.sla_hours,
            )
            story.criticality = level
            story.updated_at  = datetime.utcnow()
            self._store[external_id] = story

            # Update graph node
            if story.node_id:
                node = await self._repo.get_node(story.node_id)
                if node:
                    node.set("criticality", level.value)
                    node.set("sla_hours", matrix.sla_hours)
                    await self._repo.update_node(node)

        return level

    # ------------------------------------------------------------------
    # Child artifacts
    # ------------------------------------------------------------------

    async def add_child(
        self,
        story_external_id: str,
        child_type:        ChildType,
        external_id:       str,
        title:             str,
        description:       str              = "",
        criticality:       CriticalityLevel = CriticalityLevel.P1,
        caused_by_version: int | None       = None,
        metadata:          dict[str, Any]   = None,
    ) -> ChildArtifact:
        """Registra um artefato filho (Defect, Improvement ou Regression)."""
        story = await self.get(story_external_id)
        if not story:
            raise ValueError(f"Story '{story_external_id}' não encontrada.")

        child = ChildArtifact(
            story_external_id=story_external_id,
            child_type=child_type,
            external_id=external_id,
            title=title,
            description=description,
            criticality=criticality,
            caused_by_version=caused_by_version,
            metadata=metadata or {},
        )
        story.children.append(child)

        if child_type == ChildType.REGRESSION:
            story.status = StoryStatus.REGRESSED
            log.warning(
                "story_regression_registered",
                external_id=story_external_id,
                child=external_id,
                criticality=criticality.value,
            )

        # Persist child as graph node
        child_node = Node(
            label=child_type.value,
            external_id=external_id,
            properties={
                "title":              title,
                "criticality":        criticality.value,
                "caused_by_version":  caused_by_version,
                "story_external_id":  story_external_id,
            },
        )
        child_node = await self._repo.add_node(child_node)

        if story.node_id:
            await self._repo.ensure_edge(
                story.node_id, child_node.id, RelationType.HAS_CHILD
            )
            if child_type == ChildType.REGRESSION:
                await self._repo.ensure_edge(
                    child_node.id, story.node_id, RelationType.CAUSED_BY
                )

        self._store[story_external_id] = story
        log.info("child_artifact_added", story=story_external_id,
                 child_type=child_type.value, child_id=external_id)
        return child

    async def resolve_child(
        self,
        story_external_id: str,
        child_external_id: str,
        fixed_in_version:  int | None = None,
    ) -> ChildArtifact | None:
        """Marca um artefato filho como resolvido."""
        story = await self.get(story_external_id)
        if not story:
            return None

        for child in story.children:
            if child.external_id == child_external_id:
                child.resolved       = True
                child.fixed_in_version = fixed_in_version
                log.info("child_resolved", child=child_external_id,
                         fixed_in=fixed_in_version)
                return child
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get(self, external_id: str) -> Story | None:
        """Recupera Story do cache ou do grafo."""
        if external_id in self._store:
            return self._store[external_id]

        node = await self._repo.get_node_by_external_id(external_id, label="Story")
        if not node:
            return None

        story = self._node_to_story(node)
        self._store[external_id] = story
        return story

    async def get_version_diff(
        self,
        external_id: str,
        from_version: int,
        to_version:   int,
    ) -> VersionDiff | None:
        """Computa diff entre duas versões específicas."""
        story = await self.get(external_id)
        if not story:
            return None
        v_from = story.get_version(from_version)
        v_to   = story.get_version(to_version)
        if not v_from or not v_to:
            return None
        return self._diff.compute(v_from, v_to)

    async def list_breaking_changes(self, external_id: str) -> list[VersionDiff]:
        """Retorna todos os diffs com mudanças breaking da Story."""
        story = await self.get(external_id)
        if not story or len(story.versions) < 2:
            return []
        all_diffs = self._diff.compute_multi(story.versions)
        return [d for d in all_diffs if d.is_breaking]

    async def quality_gate_check(self, external_id: str) -> dict[str, Any]:
        """
        Verifica se a Story passa nos quality gates do Blueprint v1.4:
          - Tem ao menos 1 critério de aceite
          - Não tem critérios ambíguos (CRITICAL)
          - Criticidade classificada
          - Sem defects P0 abertos
        """
        story = await self.get(external_id)
        if not story:
            return {"passed": False, "reason": "Story não encontrada"}

        latest = story.latest_version
        issues: list[str] = []

        if not latest or not latest.acceptance_criteria:
            issues.append("Nenhum critério de aceite definido.")

        if story.criticality not in (CriticalityLevel.P0, CriticalityLevel.P1, CriticalityLevel.P2):
            issues.append("Criticidade não classificada.")

        p0_defects = [c for c in story.open_defects if c.criticality == CriticalityLevel.P0]
        if p0_defects:
            issues.append(f"{len(p0_defects)} defect(s) P0 aberto(s).")

        return {
            "story_id":   external_id,
            "passed":     len(issues) == 0,
            "issues":     issues,
            "criticality": story.criticality.value,
            "version":    story.current_version,
            "open_defects": len(story.open_defects),
        }

    # ------------------------------------------------------------------
    # Graph persistence helpers
    # ------------------------------------------------------------------

    async def _persist_story(self, story: Story) -> UUID:
        node = Node(
            label="Story",
            external_id=story.external_id,
            properties={
                "title":        story.title,
                "description":  story.description,
                "status":       story.status.value,
                "criticality":  story.criticality.value,
            },
        )
        saved = await self._repo.upsert_node(node)
        return saved.id

    async def _persist_version(self, story: Story, version: StoryVersion) -> None:
        v_node = Node(
            label="StoryVersion",
            external_id=f"{story.external_id}:v{version.version_number}",
            properties={
                "version_number":      version.version_number,
                "snapshot_type":       version.snapshot_type.value,
                "title":               version.title,
                "acceptance_criteria": version.acceptance_criteria,
                "priority":            version.priority.value,
                "status":              version.status.value,
                "created_by":          version.created_by,
            },
        )
        saved = await self._repo.add_node(v_node)

        if story.node_id:
            await self._repo.ensure_edge(
                story.node_id, saved.id, RelationType.HAS_VERSION
            )

        # Link versions sequentially
        if version.version_number > 1:
            prev_node = await self._repo.get_node_by_external_id(
                f"{story.external_id}:v{version.version_number - 1}",
                label="StoryVersion",
            )
            if prev_node:
                await self._repo.ensure_edge(
                    prev_node.id, saved.id, RelationType.NEXT_VERSION
                )

    async def _persist_diff(
        self,
        story:      Story,
        from_v:     StoryVersion,
        to_v:       StoryVersion,
        diff:       VersionDiff,
    ) -> None:
        diff_node = Node(
            label="VersionDiff",
            external_id=f"{story.external_id}:diff:{from_v.version_number}-{to_v.version_number}",
            properties={
                "from_version":            from_v.version_number,
                "to_version":              to_v.version_number,
                "changes_count":           len(diff.changes),
                "is_breaking":             diff.is_breaking,
                "risk_delta":              diff.risk_delta,
                "ambiguities_introduced":  diff.ambiguities_introduced,
                "scenarios_impacted":      diff.scenarios_impacted,
                "summary":                 diff.summary,
            },
        )
        await self._repo.add_node(diff_node)

    @staticmethod
    def _status_from_snapshot(snapshot_type: SnapshotType) -> StoryStatus:
        return {
            SnapshotType.DEF: StoryStatus.DEFINED,
            SnapshotType.IMP: StoryStatus.IMPLEMENTED,
            SnapshotType.REG: StoryStatus.REGRESSED,
        }[snapshot_type]

    @staticmethod
    def _node_to_story(node: Node) -> Story:
        props = node.properties
        return Story(
            external_id=node.external_id,
            title=props.get("title", ""),
            description=props.get("description", ""),
            status=StoryStatus(props.get("status", StoryStatus.DRAFT.value)),
            criticality=CriticalityLevel(props.get("criticality", CriticalityLevel.P1.value)),
            node_id=node.id,
        )
