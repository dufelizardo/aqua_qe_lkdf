"""
runtime_core/api.py
AQuA-QE LKDF — FastAPI REST API

Expõe o Runtime Core como serviço HTTP.
Endpoints principais:
  POST /flows/parse          — Parse e validação de DSL
  POST /flows/execute        — Execução de Flow (async)
  GET  /flows/{id}/report    — Resultado de execução
  POST /requirements/analyze — Análise cognitiva de requisito (AI)
  GET  /rtm                  — Requirement Traceability Matrix
  GET  /health               — Health check
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import structlog
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from shared.models import (
    ExecutionReport,
    Flow,
    ProjectContext,
    RuntimeContext,
)
from runtime_core.parser.dsl_parser import DSLParser, validate_dsl
from runtime_core.execution_engine.engine import ExecutionEngine
from runtime_core.adapters.robot.robot_adapter import RobotAdapter
from runtime_core.evidence_engine.collector import EvidenceCollector, TraceabilityEngine
from ai_engine.requirement_agent.agent import RequirementAgent, RequirementAnalysis

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# In-memory store (MVP — substituir por PostgreSQL na Fase 2)
# ---------------------------------------------------------------------------

_reports: dict[str, ExecutionReport] = {}
_flows:   dict[str, Flow]            = {}
_tracer   = TraceabilityEngine()
_evidence = EvidenceCollector()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("lkdf_runtime_start", version="1.1", adapter="robot-framework")
    yield
    log.info("lkdf_runtime_shutdown")


app = FastAPI(
    title="AQuA-QE LKDF Runtime Core",
    description="Layered Keyword-Driven Framework — Plataforma Cognitiva de Qualidade",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ParseRequest(BaseModel):
    source: str
    validate_only: bool = False


class ParseResponse(BaseModel):
    valid: bool
    flow_name: str | None = None
    scenarios: int = 0
    steps: int = 0
    errors: list[str] = []
    warnings: list[str] = []
    flow: Flow | None = None


class ExecuteRequest(BaseModel):
    source: str
    context: ProjectContext = ProjectContext()
    dry_run: bool = False


class ExecuteResponse(BaseModel):
    execution_id: str
    status: str
    message: str


class AnalyzeRequest(BaseModel):
    requirement_text: str
    requirement_id: str = "REQ-AUTO"
    context: dict[str, Any] = {}


class HealthResponse(BaseModel):
    status: str
    version: str
    adapter: str
    runtime: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        version="1.1.0",
        adapter="robot-framework",
        runtime="lkdf-python",
    )


@app.post("/flows/parse", response_model=ParseResponse)
async def parse_flow(req: ParseRequest):
    """Parse e valida o DSL semântico. Obrigatório antes de qualquer execução."""
    validation = validate_dsl(req.source)

    if req.validate_only or not validation.valid:
        return ParseResponse(
            valid=validation.valid,
            errors=[e.message for e in validation.errors],
            warnings=[w.message for w in validation.warnings],
        )

    try:
        parser = DSLParser()
        flow   = parser.parse(req.source)
        _flows[str(flow.id)] = flow

        total_steps = sum(len(s.steps) for s in flow.scenarios)
        return ParseResponse(
            valid=True,
            flow_name=flow.name,
            scenarios=len(flow.scenarios),
            steps=total_steps,
            warnings=[w.message for w in validation.warnings],
            flow=flow,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/flows/execute", response_model=ExecuteResponse)
async def execute_flow(req: ExecuteRequest, background: BackgroundTasks):
    """
    Inicia a execução de um Flow.
    Processa em background e retorna execution_id para polling.
    """
    try:
        parser = DSLParser()
        flow   = parser.parse(req.source)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"DSL inválido: {exc}")

    context = RuntimeContext(
        flow=flow,
        project=req.context,
    )
    exec_id = str(context.execution_id)

    background.add_task(_run_execution, flow, context, exec_id, req.dry_run)

    return ExecuteResponse(
        execution_id=exec_id,
        status="running",
        message=f"Execução iniciada para '{flow.name}' — {len(flow.scenarios)} scenarios.",
    )


@app.get("/flows/execute/{execution_id}", response_model=ExecutionReport)
async def get_execution_report(execution_id: str):
    """Retorna o relatório de uma execução concluída."""
    report = _reports.get(execution_id)
    if not report:
        raise HTTPException(status_code=404, detail="Execução não encontrada ou ainda em andamento.")
    return report


@app.post("/flows/execute/stream")
async def execute_flow_stream(req: ExecuteRequest):
    """
    Execução com streaming de resultados em tempo real.
    Retorna Server-Sent Events com StepResult e ScenarioResult à medida que ocorrem.
    """
    try:
        parser = DSLParser()
        flow   = parser.parse(req.source)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    context = RuntimeContext(flow=flow, project=req.context)
    adapter = RobotAdapter(base_url=req.context.base_url or "http://localhost:4200")
    engine  = ExecutionEngine(adapter=adapter)

    async def event_generator():
        async for result in engine.execute_flow_stream(flow, context):
            yield f"data: {result.model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/requirements/analyze")
async def analyze_requirement(req: AnalyzeRequest) -> dict[str, Any]:
    """
    Cognitive Engine: analisa um requisito e gera Flow DSL automaticamente.
    Usa o Requirement Agent (Claude) para reasoning semântico.
    """
    agent    = RequirementAgent()
    analysis = await agent.analyze(
        requirement_text=req.requirement_text,
        requirement_id=req.requirement_id,
        context=req.context or None,
    )
    return {
        "requirement_id":    analysis.requirement_id,
        "interpreted_intent": analysis.interpreted_intent,
        "business_rules":    [
            {
                "description": r.description,
                "entities":    r.entities,
                "conditions":  r.conditions,
                "outcomes":    r.outcomes,
            }
            for r in analysis.business_rules
        ],
        "ambiguities":       analysis.ambiguities,
        "gaps":              analysis.gaps,
        "suggested_scenarios": analysis.suggested_scenarios,
        "risk_level":        analysis.risk_level,
        "generated_flow_dsl": analysis.generated_flow_dsl,
    }


@app.get("/rtm")
async def get_rtm():
    """Retorna a Requirement Traceability Matrix."""
    return _tracer.coverage_report()


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

async def _run_execution(
    flow: Flow,
    context: RuntimeContext,
    exec_id: str,
    dry_run: bool,
) -> None:
    adapter = RobotAdapter(base_url=context.project.base_url or "http://localhost:4200")
    engine  = ExecutionEngine(adapter=adapter)

    try:
        report = await engine.execute_flow(flow, context)
        _reports[exec_id] = report

        # Collect evidence & update traceability
        evidence_paths = _evidence.collect_from_report(report)
        report.evidence_paths = evidence_paths
        _tracer.from_report(report)

        log.info("background_execution_done", exec_id=exec_id, status=report.status)
    except Exception as exc:
        log.error("background_execution_error", exec_id=exec_id, error=str(exc))


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("runtime_core.api:app", host="0.0.0.0", port=8080, reload=True)
