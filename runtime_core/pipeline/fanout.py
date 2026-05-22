"""
runtime_core/pipeline/fanout.py
AQuA-QE LKDF v1.4 — Fan-Out Pipeline

Refatoração do pipeline sequencial v1.1 para:
  Sequencial → Sequencial + Fan-Out paralelo assíncrono

Arquitetura:
  - PipelineStage: unidade atômica de processamento
  - StageDependency: define DAG de dependências entre stages
  - FanOutPipeline: executor que resolve o DAG e paraleliza stages independentes
  - PipelineContext: estado compartilhado entre stages + trace completo
  - PipelineResult: resultado com trace, custo, tempo, artefatos

Regra arquitetural do Blueprint v1.4:
  "Stages independentes no mesmo nível executam em paralelo (fan-out).
   Stages com dependências aguardam seus predecessores (sequencial)."
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import structlog

from runtime_core.persistence.graph.models import Node, RelationType
from runtime_core.persistence.graph.repository import GraphRepository

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stage models
# ---------------------------------------------------------------------------

class StageStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class StageResult:
    stage_id:    str
    stage_name:  str
    status:      StageStatus
    output:      Any                  = None
    error:       str                  = ""
    duration_ms: int                  = 0
    artifacts:   list[str]            = field(default_factory=list)
    metadata:    dict[str, Any]       = field(default_factory=dict)


@dataclass
class PipelineContext:
    """Estado compartilhado entre todos os stages do pipeline."""
    execution_id:  UUID                    = field(default_factory=uuid4)
    inputs:        dict[str, Any]          = field(default_factory=dict)
    outputs:       dict[str, Any]          = field(default_factory=dict)   # stage_id → output
    graph:         GraphRepository | None  = None
    metadata:      dict[str, Any]          = field(default_factory=dict)
    trace:         list[dict[str, Any]]    = field(default_factory=list)

    def set_output(self, stage_id: str, value: Any) -> None:
        self.outputs[stage_id] = value

    def get_output(self, stage_id: str, default: Any = None) -> Any:
        return self.outputs.get(stage_id, default)

    def add_trace(self, stage_id: str, event: str, data: dict | None = None) -> None:
        self.trace.append({
            "stage_id":  stage_id,
            "event":     event,
            "timestamp": time.time(),
            "data":      data or {},
        })


@dataclass
class PipelineResult:
    pipeline_id:  str
    execution_id: UUID
    status:       StageStatus
    stage_results: list[StageResult]      = field(default_factory=list)
    context:      PipelineContext | None  = None
    total_ms:     int                     = 0
    artifacts:    list[str]               = field(default_factory=list)
    error:        str                     = ""

    @property
    def passed(self) -> int:
        return sum(1 for s in self.stage_results if s.status == StageStatus.COMPLETED)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.stage_results if s.status == StageStatus.FAILED)

    @property
    def all_artifacts(self) -> list[str]:
        result = list(self.artifacts)
        for s in self.stage_results:
            result.extend(s.artifacts)
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "pipeline_id":  self.pipeline_id,
            "execution_id": str(self.execution_id),
            "status":       self.status,
            "stages":       len(self.stage_results),
            "passed":       self.passed,
            "failed":       self.failed,
            "total_ms":     self.total_ms,
            "artifacts":    len(self.all_artifacts),
        }


# ---------------------------------------------------------------------------
# Stage base class
# ---------------------------------------------------------------------------

class PipelineStage(ABC):
    """
    Unidade atômica de processamento do pipeline.
    Cada stage é puro: recebe PipelineContext, produz output, não tem side effects globais.
    """

    def __init__(
        self,
        stage_id:   str,
        name:       str,
        depends_on: list[str] | None = None,
        optional:   bool             = False,
    ) -> None:
        self.stage_id   = stage_id
        self.name       = name
        self.depends_on = depends_on or []
        self.optional   = optional

    @abstractmethod
    async def execute(self, context: PipelineContext) -> Any:
        """
        Executa o stage. Retorna o output que será armazenado em context.outputs[stage_id].
        Levanta exceção em caso de falha crítica.
        """

    async def on_failure(self, context: PipelineContext, error: Exception) -> None:
        """Hook chamado em caso de falha. Override para cleanup."""
        pass

    def __repr__(self) -> str:
        return f"Stage({self.stage_id}:{self.name})"


# ---------------------------------------------------------------------------
# Fan-Out Pipeline executor
# ---------------------------------------------------------------------------

class FanOutPipeline:
    """
    Executor de pipeline com suporte a Fan-Out paralelo.

    Resolve o DAG de dependências entre stages e agrupa em níveis:
      Nível 0: stages sem dependências → executam em paralelo
      Nível 1: stages que dependem apenas de nível 0 → paralelo após nível 0 concluir
      Nível N: idem

    Uso:
        pipeline = FanOutPipeline("requirement-analysis", stages=[
            ParseStage("parse", "DSL Parser"),
            SemanticStage("semantic", "Semantic Engine", depends_on=["parse"]),
            ScenarioStage("scenario", "Scenario Gen", depends_on=["parse"]),   # paralelo com semantic
            AmbiguityStage("ambiguity", "Ambiguity", depends_on=["parse"]),    # paralelo com semantic
            SynthesisStage("synthesis", "Synthesis", depends_on=["semantic","scenario","ambiguity"]),
        ])
        result = await pipeline.run(context)
    """

    def __init__(
        self,
        pipeline_id:      str,
        stages:           list[PipelineStage],
        max_concurrent:   int  = 10,
        fail_fast:        bool = False,
    ) -> None:
        self.pipeline_id    = pipeline_id
        self.stages         = {s.stage_id: s for s in stages}
        self.max_concurrent = max_concurrent
        self.fail_fast      = fail_fast

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, context: PipelineContext) -> PipelineResult:
        t0           = time.perf_counter()
        stage_results: list[StageResult] = []
        overall_status = StageStatus.COMPLETED

        log.info("pipeline_start", pipeline_id=self.pipeline_id,
                 stages=len(self.stages), execution_id=str(context.execution_id))

        levels = self._resolve_levels()

        for level_idx, level_stage_ids in enumerate(levels):
            level_stages = [self.stages[sid] for sid in level_stage_ids]

            # Check if any required predecessor failed
            runnable = [
                s for s in level_stages
                if self._can_run(s, context, stage_results)
            ]
            skipped = [s for s in level_stages if s not in runnable]

            for s in skipped:
                stage_results.append(StageResult(
                    stage_id=s.stage_id, stage_name=s.name, status=StageStatus.SKIPPED
                ))

            if not runnable:
                continue

            # Fan-out: execute all runnable stages in this level in parallel
            log.info("pipeline_level", level=level_idx, stages=[s.stage_id for s in runnable])
            sem      = asyncio.Semaphore(self.max_concurrent)
            tasks    = [self._run_stage(s, context, sem) for s in runnable]
            results  = await asyncio.gather(*tasks, return_exceptions=False)

            for result in results:
                stage_results.append(result)
                if result.status == StageStatus.FAILED:
                    overall_status = StageStatus.FAILED
                    if self.fail_fast and not self.stages[result.stage_id].optional:
                        log.warning("pipeline_fail_fast", stage=result.stage_id)
                        goto_done = True
                        break
            else:
                goto_done = False

            if goto_done:
                break

        total_ms = int((time.perf_counter() - t0) * 1000)

        # Persist pipeline trace to graph if repository is available
        if context.graph:
            await self._persist_trace(context, stage_results)

        result = PipelineResult(
            pipeline_id=self.pipeline_id,
            execution_id=context.execution_id,
            status=overall_status,
            stage_results=stage_results,
            context=context,
            total_ms=total_ms,
        )

        log.info("pipeline_done", pipeline_id=self.pipeline_id,
                 status=overall_status, total_ms=total_ms,
                 passed=result.passed, failed=result.failed)
        return result

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    async def _run_stage(
        self,
        stage:   PipelineStage,
        context: PipelineContext,
        sem:     asyncio.Semaphore,
    ) -> StageResult:
        async with sem:
            t0 = time.perf_counter()
            context.add_trace(stage.stage_id, "start")
            log.info("stage_start", stage_id=stage.stage_id, name=stage.name)

            try:
                output = await stage.execute(context)
                context.set_output(stage.stage_id, output)
                ms = int((time.perf_counter() - t0) * 1000)
                context.add_trace(stage.stage_id, "complete", {"duration_ms": ms})
                log.info("stage_complete", stage_id=stage.stage_id, ms=ms)
                return StageResult(
                    stage_id=stage.stage_id,
                    stage_name=stage.name,
                    status=StageStatus.COMPLETED,
                    output=output,
                    duration_ms=ms,
                )
            except Exception as exc:
                ms = int((time.perf_counter() - t0) * 1000)
                context.add_trace(stage.stage_id, "error", {"error": str(exc)})
                log.error("stage_failed", stage_id=stage.stage_id, error=str(exc))
                await stage.on_failure(context, exc)
                return StageResult(
                    stage_id=stage.stage_id,
                    stage_name=stage.name,
                    status=StageStatus.FAILED if not stage.optional else StageStatus.SKIPPED,
                    error=str(exc),
                    duration_ms=ms,
                )

    # ------------------------------------------------------------------
    # DAG resolution
    # ------------------------------------------------------------------

    def _resolve_levels(self) -> list[list[str]]:
        """
        Resolve o DAG de dependências em níveis de execução.
        Algoritmo: topological sort por nível (Kahn's algorithm).
        """
        in_degree: dict[str, int] = {sid: 0 for sid in self.stages}
        for stage in self.stages.values():
            for dep in stage.depends_on:
                if dep in self.stages:
                    in_degree[stage.stage_id] += 1

        levels: list[list[str]] = []
        remaining = set(self.stages.keys())

        while remaining:
            # Current level: stages with in_degree == 0
            current_level = [sid for sid in remaining if in_degree[sid] == 0]
            if not current_level:
                raise ValueError(
                    f"Ciclo detectado no pipeline '{self.pipeline_id}'. "
                    f"Stages restantes: {remaining}"
                )
            levels.append(current_level)
            for sid in current_level:
                remaining.discard(sid)
                # Reduce in_degree of dependents
                for stage in self.stages.values():
                    if sid in stage.depends_on and stage.stage_id in remaining:
                        in_degree[stage.stage_id] -= 1

        return levels

    def _can_run(
        self,
        stage:         PipelineStage,
        context:       PipelineContext,
        completed:     list[StageResult],
    ) -> bool:
        """Stage pode rodar se todos os predecessores obrigatórios completaram com sucesso."""
        completed_ids  = {r.stage_id for r in completed if r.status == StageStatus.COMPLETED}
        failed_ids     = {r.stage_id for r in completed if r.status == StageStatus.FAILED}
        for dep in stage.depends_on:
            if dep in failed_ids:
                stage_obj = self.stages.get(dep)
                if stage_obj and not stage_obj.optional:
                    return False
            if dep not in completed_ids and dep in self.stages:
                return False
        return True

    # ------------------------------------------------------------------
    # Graph persistence
    # ------------------------------------------------------------------

    async def _persist_trace(
        self,
        context:       PipelineContext,
        stage_results: list[StageResult],
    ) -> None:
        """Persiste o trace do pipeline como grafo para auditoria."""
        try:
            root = Node(
                label="PipelineExecution",
                external_id=str(context.execution_id),
                properties={
                    "pipeline_id": self.pipeline_id,
                    "status":      str(stage_results[-1].status if stage_results else "unknown"),
                    "stages":      len(stage_results),
                },
            )
            root = await context.graph.add_node(root)

            for sr in stage_results:
                stage_node = Node(
                    label="StageExecution",
                    external_id=f"{context.execution_id}:{sr.stage_id}",
                    properties={
                        "stage_id":    sr.stage_id,
                        "stage_name":  sr.stage_name,
                        "status":      sr.status,
                        "duration_ms": sr.duration_ms,
                        "error":       sr.error,
                    },
                )
                stage_node = await context.graph.add_node(stage_node)
                await context.graph.add_edge(
                    root.id, stage_node.id, RelationType.HAS_EXECUTION
                )
        except Exception as exc:
            log.warning("pipeline_trace_persist_failed", error=str(exc))
