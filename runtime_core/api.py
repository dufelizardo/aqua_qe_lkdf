"""
runtime_core/api.py
AQuA-QE LKDF v1.4 — FastAPI Gateway (Sprint 1.3)

Reescrito conforme Blueprint §4.2 e Roadmap Sprint 1.3.

Mudanças em relação à versão anterior:
  - lifespan inicializa TODOS os módulos: DB, AI Gateway, Knowledge, Policy
  - Cada módulo é singleton compartilhado entre requests (não instanciado por request)
  - CognitivePipeline v2 (Fase 1 + Fan-Out) exposto em /cognitive/analyze
  - Flows, Stories, Executions persistidos no GraphRepository (SQLite)
  - Knowledge Layer exposto: /knowledge/patterns, /knowledge/learn
  - Policy Engine exposto: /policy/evaluate
  - RTM real via GraphRepository (não in-memory)
  - Todos os endpoints anteriores preservados e funcionais

Blueprint §4.2 — Core Application:
  requirements/ · validation/ · traceability/ · testing/ ·
  accessibility/ · quality/ · knowledge/ · ai_gateway/ ·
  lkdf_runtime/ · adapters/ · persistence/ · shared/
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from shared.models import ExecutionReport, Flow, ProjectContext, RuntimeContext
from shared.semantic import InputSourceType, SDLCPhase

log = structlog.get_logger(__name__)

# ── Singletons do sistema ─────────────────────────────────────────────────
# Inicializados no lifespan — compartilhados entre todos os requests.

_db:          Any = None   # SQLiteGraphAdapter
_gateway:     Any = None   # AIGateway
_knowledge:   Any = None   # KnowledgeFacade
_policy:      Any = None   # PolicyEngine
_cognitive:   Any = None   # CognitivePipeline v2

# Stores in-memory para MVP (migram para GraphRepository nas próximas sprints)
_reports:  dict[str, ExecutionReport] = {}
_flows_db: dict[str, dict]            = {}
_stories:  dict[str, dict]            = {}
_exec_history: list[dict]             = []


# ── Lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicializa todos os módulos cognitivos no startup.
    Blueprint §4.2: nenhum módulo é instanciado por request.
    """
    global _db, _gateway, _knowledge, _policy, _cognitive

    log.info("lkdf_startup", version="1.4", blueprint="Cognitive Enterprise")

    # 1. GraphRepository (SQLite)
    try:
        from runtime_core.persistence.adapters.sqlite_adapter import SQLiteGraphAdapter
        db_url = os.getenv("LKDF_DB_URL", "sqlite+aiosqlite:///./data/lkdf.db")
        os.makedirs("data", exist_ok=True)
        _db = SQLiteGraphAdapter(db_url=db_url)
        await _db.initialize()
        log.info("db_initialized", url=db_url)
    except Exception as exc:
        log.warning("db_init_failed", error=str(exc))
        _db = None

    # 2. AI Gateway (multi-LLM)
    try:
        from ai_engine.gateway.gateway import AIGateway, LLMConfig
        _gateway = AIGateway()
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            from ai_engine.gateway.gateway import LLMProvider, TaskType
            _gateway.register(LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-haiku-4-5",
                api_key=api_key,
                task_types=[TaskType.CLASSIFICATION, TaskType.AMBIGUITY_DETECTION],
            ))
            _gateway.register(LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-sonnet-4-20250514",
                api_key=api_key,
                task_types=[TaskType.REQUIREMENT_ANALYSIS, TaskType.SCENARIO_GENERATION],
                is_default=True,
            ))
        log.info("gateway_initialized", has_key=bool(api_key))
    except Exception as exc:
        log.warning("gateway_init_failed", error=str(exc))
        _gateway = None

    # 3. Knowledge Layer
    try:
        from ai_engine.knowledge.facade import KnowledgeFacade
        _knowledge = KnowledgeFacade(repository=_db)
        await _knowledge.initialize_seeds()
        log.info("knowledge_initialized")
    except Exception as exc:
        log.warning("knowledge_init_failed", error=str(exc))
        _knowledge = None

    # 4. Policy Engine
    try:
        from runtime_core.quality_policy.engine import PolicyEngine
        _policy = PolicyEngine(repository=_db)
        log.info("policy_initialized")
    except Exception as exc:
        log.warning("policy_init_failed", error=str(exc))
        _policy = None

    # 5. CognitivePipeline v2 (Fase 1 + Fan-Out)
    try:
        from ai_engine.pipeline.cognitive import CognitivePipeline
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        _cognitive = CognitivePipeline(
            api_key=api_key,
            extraction_mode="enhanced" if api_key else "rules_only",
            engine_timeout=30,
        )
        log.info("cognitive_pipeline_initialized", has_api=bool(api_key))
    except Exception as exc:
        log.warning("cognitive_pipeline_init_failed", error=str(exc))
        _cognitive = None

    log.info(
        "lkdf_startup_complete",
        db=_db is not None,
        gateway=_gateway is not None,
        knowledge=_knowledge is not None,
        policy=_policy is not None,
        cognitive=_cognitive is not None,
    )

    yield   # ── aplicação rodando ──

    log.info("lkdf_shutdown")
    if _db:
        try:
            await _db.close()
        except Exception:
            pass


# ── FastAPI app ───────────────────────────────────────────────────────────

app = FastAPI(
    title="AQuA-QE LKDF v1.4",
    description=(
        "Plataforma Cognitiva de Engenharia de Qualidade, Requisitos, "
        "Automação Inteligente e Governança do SDLC. "
        "Blueprint: Intent → Semantics → Flow → Scenario → Runtime → Execution → Evidence"
    ),
    version="1.4.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas de request/response ───────────────────────────────────────────

class ParseRequest(BaseModel):
    source:        str
    validate_only: bool = False

class ParseResponse(BaseModel):
    valid:      bool
    flow_name:  str | None = None
    scenarios:  int = 0
    steps:      int = 0
    errors:     list[str] = []
    warnings:   list[str] = []
    flow:       Flow | None = None

class ExecuteRequest(BaseModel):
    source:  str
    context: ProjectContext = Field(default_factory=ProjectContext)
    dry_run: bool = False

class ExecuteResponse(BaseModel):
    execution_id: str
    status:       str
    message:      str

class CognitiveAnalyzeRequest(BaseModel):
    requirement_text: str
    requirement_id:   str = "REQ-AUTO"
    session_id:       str = ""
    input_source:     str = "free_text"
    sdlc_phase:       str = "requirements"
    language_hint:    str = ""
    project_context:  dict[str, Any] = Field(default_factory=dict)
    answers:          dict[str, str] = Field(default_factory=dict)
    skip_fanout:      bool = False

class FlowCreateRequest(BaseModel):
    name:            str
    dsl_source:      str
    requirement_ref: str = ""
    adapter:         str = "playwright"
    priority:        str = "MEDIUM"
    project_id:      str = "default"

class StoryCreateRequest(BaseModel):
    external_id:  str
    title:        str
    description:  str
    criticality:  str = "P1"
    acceptance_criteria: list[str] = Field(default_factory=list)

class LearnRequest(BaseModel):
    domain:   str
    title:    str
    severity: str = "P1"
    description: str = ""

class PolicyEvaluateRequest(BaseModel):
    subject_id: str
    context:    dict[str, Any] = Field(default_factory=dict)

class AmbiguityRequest(BaseModel):
    requirement_text: str
    requirement_id:   str = "REQ-AUTO"
    context:          dict[str, Any] = Field(default_factory=dict)


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health() -> dict[str, Any]:
    """Health check com status de todos os módulos inicializados."""
    return {
        "status":  "ok",
        "version": "1.4.0",
        "blueprint": "Cognitive Enterprise",
        "modules": {
            "graph_repository":   _db        is not None,
            "ai_gateway":         _gateway   is not None,
            "knowledge_layer":    _knowledge is not None,
            "policy_engine":      _policy    is not None,
            "cognitive_pipeline": _cognitive is not None,
        },
        "pipeline": "Intent → Semantics → Flow → Scenario → Runtime → Execution → Evidence",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ════════════════════════════════════════════════════════════════════════════
# COGNITIVE PIPELINE (Blueprint §7)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/cognitive/analyze", tags=["Cognitive Pipeline"])
async def cognitive_analyze(req: CognitiveAnalyzeRequest) -> dict[str, Any]:
    """
    Pipeline Cognitivo v2 completo (Blueprint §7).

    Fase 1 (sequencial): Normalização → Extração → Classificação → Gaps → Perguntas
    Gate de Fan-Out: libera Fase 2 quando perguntas P1 respondidas.
    Fase 2 (paralela): Validação + Qualidade + Acessibilidade + Rastreabilidade + Cenários.

    Human-in-the-loop: se gate_blocked=True, retornar 'answers' com respostas
    às perguntas e chamar novamente com o mesmo session_id.
    """
    if not _cognitive:
        raise HTTPException(503, "Cognitive Pipeline não inicializado.")

    try:
        input_source = InputSourceType(req.input_source)
    except ValueError:
        input_source = InputSourceType.FREE_TEXT

    try:
        sdlc_phase = SDLCPhase(req.sdlc_phase)
    except ValueError:
        sdlc_phase = SDLCPhase.REQUIREMENTS

    result = await _cognitive.run(
        input_text=req.requirement_text,
        requirement_id=req.requirement_id,
        session_id=req.session_id,
        input_source=input_source,
        sdlc_phase=sdlc_phase,
        language_hint=req.language_hint,
        project_context=req.project_context or None,
        answers=req.answers or None,
        skip_fanout=req.skip_fanout,
    )

    return result.to_api_response()


@app.get("/cognitive/health", tags=["Cognitive Pipeline"])
async def cognitive_health() -> dict[str, Any]:
    """Status detalhado do pipeline cognitivo."""
    return {
        "pipeline_v2":   _cognitive is not None,
        "ai_gateway":    _gateway   is not None,
        "knowledge":     _knowledge is not None,
        "policy":        _policy    is not None,
        "has_api_key":   bool(os.getenv("ANTHROPIC_API_KEY", "")),
        "mode":          "enhanced" if os.getenv("ANTHROPIC_API_KEY") else "rules_only",
    }


# ════════════════════════════════════════════════════════════════════════════
# FLOWS (Blueprint §3 — Flow Layer)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/flows", tags=["Flows"])
async def list_flows(
    project_id: str = Query("default"),
    page:       int = Query(0, ge=0),
    size:       int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Lista todos os flows do projeto."""
    all_flows = [
        f for f in _flows_db.values()
        if f.get("project_id") == project_id
    ]
    start = page * size
    return {
        "content":       all_flows[start:start + size],
        "page":          page,
        "size":          size,
        "totalElements": len(all_flows),
        "totalPages":    max(1, (len(all_flows) + size - 1) // size),
        "last":          (page + 1) * size >= len(all_flows),
    }


@app.post("/flows", tags=["Flows"])
async def create_flow(req: FlowCreateRequest) -> dict[str, Any]:
    """Cria um novo flow e persiste no GraphRepository."""
    from runtime_core.parser.dsl_parser import DSLParser, validate_dsl

    # Validar DSL
    validation = validate_dsl(req.dsl_source)
    if not validation.valid:
        raise HTTPException(422, [e.message for e in validation.errors])

    try:
        parser = DSLParser()
        flow   = parser.parse(req.dsl_source)
    except Exception as exc:
        raise HTTPException(422, str(exc))

    flow_record = {
        "id":              str(flow.id),
        "name":            req.name or flow.name,
        "requirement_ref": req.requirement_ref,
        "adapter":         req.adapter,
        "priority":        req.priority,
        "dsl_source":      req.dsl_source,
        "scenario_count":  len(flow.scenarios),
        "step_count":      sum(len(s.steps) for s in flow.scenarios),
        "status":          "DRAFT",
        "project_id":      req.project_id,
        "created_at":      datetime.utcnow().isoformat(),
        "updated_at":      datetime.utcnow().isoformat(),
    }

    _flows_db[str(flow.id)] = flow_record

    # Persistir no grafo se DB disponível
    if _db:
        try:
            from runtime_core.persistence.graph.models import Node
            node = Node(
                label="Flow",
                external_id=str(flow.id),
                properties=flow_record,
            )
            await _db.add_node(node)
        except Exception as exc:
            log.warning("flow_persist_failed", error=str(exc))

    log.info("flow_created", flow_id=str(flow.id), name=flow_record["name"])
    return flow_record


@app.get("/flows/{flow_id}", tags=["Flows"])
async def get_flow(flow_id: str) -> dict[str, Any]:
    """Retorna um flow pelo ID."""
    flow = _flows_db.get(flow_id)
    if not flow:
        raise HTTPException(404, f"Flow '{flow_id}' não encontrado.")
    return flow


@app.patch("/flows/{flow_id}", tags=["Flows"])
async def update_flow(flow_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Atualiza campos de um flow existente."""
    flow = _flows_db.get(flow_id)
    if not flow:
        raise HTTPException(404, f"Flow '{flow_id}' não encontrado.")
    allowed = {"name", "requirement_ref", "adapter", "priority", "dsl_source", "status"}
    for k, v in updates.items():
        if k in allowed:
            flow[k] = v
    flow["updated_at"] = datetime.utcnow().isoformat()
    _flows_db[flow_id] = flow
    return flow


@app.delete("/flows/{flow_id}", tags=["Flows"])
async def delete_flow(flow_id: str) -> dict[str, str]:
    """Remove um flow."""
    if flow_id not in _flows_db:
        raise HTTPException(404, f"Flow '{flow_id}' não encontrado.")
    del _flows_db[flow_id]
    return {"deleted": flow_id}


@app.post("/flows/parse", tags=["Flows"], response_model=ParseResponse)
async def parse_flow(req: ParseRequest) -> ParseResponse:
    """Parse e valida DSL semântico."""
    from runtime_core.parser.dsl_parser import DSLParser, validate_dsl
    validation = validate_dsl(req.source)
    if req.validate_only or not validation.valid:
        return ParseResponse(
            valid=validation.valid,
            errors=[e.message for e in validation.errors],
            warnings=[w.message for w in validation.warnings],
        )
    try:
        flow = DSLParser().parse(req.source)
        return ParseResponse(
            valid=True,
            flow_name=flow.name,
            scenarios=len(flow.scenarios),
            steps=sum(len(s.steps) for s in flow.scenarios),
            warnings=[w.message for w in validation.warnings],
            flow=flow,
        )
    except Exception as exc:
        raise HTTPException(422, str(exc))


# ════════════════════════════════════════════════════════════════════════════
# EXECUTIONS (Blueprint §3 — Test Layer)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/flows/execute", tags=["Executions"], response_model=ExecuteResponse)
async def execute_flow_endpoint(req: ExecuteRequest, background: BackgroundTasks) -> ExecuteResponse:
    """Inicia execução de flow em background."""
    from runtime_core.parser.dsl_parser import DSLParser
    try:
        flow = DSLParser().parse(req.source)
    except Exception as exc:
        raise HTTPException(422, f"DSL inválido: {exc}")

    context = RuntimeContext(flow=flow, project=req.context)
    exec_id = str(context.execution_id)

    background.add_task(_run_execution_bg, flow, context, exec_id, req.dry_run)

    return ExecuteResponse(
        execution_id=exec_id,
        status="running",
        message=f"Execução iniciada para '{flow.name}' — {len(flow.scenarios)} scenarios.",
    )


@app.get("/flows/execute/{execution_id}", tags=["Executions"])
async def get_execution(execution_id: str) -> ExecutionReport:
    """Retorna relatório de execução."""
    report = _reports.get(execution_id)
    if not report:
        raise HTTPException(404, "Execução não encontrada ou ainda em andamento.")
    return report


@app.get("/executions", tags=["Executions"])
async def list_executions(
    flow_id: str = Query(""),
    page:    int = Query(0, ge=0),
    size:    int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Histórico de execuções com filtro opcional por flow."""
    history = _exec_history
    if flow_id:
        history = [e for e in history if e.get("flow_id") == flow_id]
    start = page * size
    return {
        "content":       history[start:start + size],
        "page":          page,
        "size":          size,
        "totalElements": len(history),
        "totalPages":    max(1, (len(history) + size - 1) // size),
        "last":          (page + 1) * size >= len(history),
    }


@app.post("/flows/execute/stream", tags=["Executions"])
async def execute_stream(req: ExecuteRequest) -> StreamingResponse:
    """Execução com streaming SSE em tempo real."""
    from runtime_core.parser.dsl_parser import DSLParser
    from runtime_core.adapters.robot.robot_adapter import RobotAdapter
    from runtime_core.execution_engine.engine import ExecutionEngine
    try:
        flow = DSLParser().parse(req.source)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    context = RuntimeContext(flow=flow, project=req.context)
    adapter = RobotAdapter(base_url=req.context.base_url or "http://localhost:4200")
    engine  = ExecutionEngine(adapter=adapter)

    async def events():
        async for result in engine.execute_flow_stream(flow, context):
            yield f"data: {result.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


# ════════════════════════════════════════════════════════════════════════════
# STORIES — Story Lifecycle (Blueprint §10)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/stories", tags=["Stories"])
async def list_stories(page: int = Query(0, ge=0), size: int = Query(20)) -> dict[str, Any]:
    """Lista histórias cadastradas."""
    all_s = list(_stories.values())
    start = page * size
    return {
        "content": all_s[start:start + size],
        "totalElements": len(all_s),
        "page": page, "size": size,
    }


@app.post("/stories", tags=["Stories"])
async def create_story(req: StoryCreateRequest) -> dict[str, Any]:
    """Cria uma nova história com versionamento semântico (Blueprint §10)."""
    try:
        from runtime_core.story_lifecycle.service import StoryService
        from runtime_core.story_lifecycle.models import CriticalityLevel as SLC
        svc = StoryService(repository=_db)
        story = await svc.create_story(
            external_id=req.external_id,
            title=req.title,
            description=req.description,
            criticality=SLC(req.criticality),
            acceptance_criteria=req.acceptance_criteria,
        )
        record = {
            "external_id":        story.external_id,
            "title":              story.title,
            "status":             story.status,
            "current_version":    story.current_version,
            "criticality":        story.criticality,
            "created_at":         story.created_at.isoformat(),
            "updated_at":         story.updated_at.isoformat(),
        }
        _stories[story.external_id] = record
        return record
    except Exception as exc:
        log.warning("story_create_failed", error=str(exc))
        # Fallback: store simples
        record = {
            "external_id": req.external_id,
            "title":       req.title,
            "description": req.description,
            "criticality": req.criticality,
            "status":      "active",
            "version":     1,
            "created_at":  datetime.utcnow().isoformat(),
        }
        _stories[req.external_id] = record
        return record


@app.get("/stories/{external_id}", tags=["Stories"])
async def get_story(external_id: str) -> dict[str, Any]:
    """Retorna uma história pelo ID externo."""
    story = _stories.get(external_id)
    if not story:
        raise HTTPException(404, f"História '{external_id}' não encontrada.")
    return story


# ════════════════════════════════════════════════════════════════════════════
# RTM — Traceability (Blueprint §5.3)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/rtm", tags=["Traceability"])
async def get_rtm(page: int = Query(0, ge=0), size: int = Query(50)) -> dict[str, Any]:
    """Requirement Traceability Matrix via GraphRepository."""
    if _db:
        try:
            nodes = await _db.find_nodes(label="TraceEntry")
            entries = [n.properties for n in nodes]
            start = page * size
            return {
                "content":       entries[start:start + size],
                "totalElements": len(entries),
                "page": page, "size": size,
            }
        except Exception as exc:
            log.warning("rtm_db_failed", error=str(exc))

    # Fallback in-memory (TraceabilityEngine)
    from runtime_core.evidence_engine.collector import TraceabilityEngine
    tracer = TraceabilityEngine()
    return tracer.coverage_report()


@app.get("/rtm/summary", tags=["Traceability"])
async def rtm_summary() -> list[dict]:
    """Sumário de cobertura por requisito."""
    if _db:
        try:
            nodes = await _db.find_nodes(label="Requirement")
            return [
                {
                    "requirement_id": n.external_id,
                    "title":          n.properties.get("title", ""),
                    "last_status":    n.properties.get("last_status", "PENDING"),
                    "coverage_pct":   n.properties.get("coverage_pct", 0),
                }
                for n in nodes
            ]
        except Exception as exc:
            log.warning("rtm_summary_failed", error=str(exc))
    return []


# ════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE LAYER (Blueprint §5.8)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/knowledge/patterns", tags=["Knowledge"])
async def list_patterns(domain: str = Query("")) -> dict[str, Any]:
    """Lista padrões aprendidos pelo Knowledge Layer."""
    if not _knowledge:
        return {"patterns": [], "message": "Knowledge Layer não inicializado."}
    try:
        from ai_engine.knowledge.memory.store import OrganizationalMemoryStore
        from ai_engine.knowledge.models import MemoryType
        memories = await _knowledge.memory.find_by_type(MemoryType.DEFECT_PATTERN)
        patterns = [
            {
                "title":      m.title,
                "domain":     m.domain,
                "confidence": m.confidence,
                "frequency":  m.frequency,
                "type":       m.memory_type.value,
            }
            for m in memories
            if not domain or m.domain == domain
        ]
        return {"patterns": patterns, "total": len(patterns)}
    except Exception as exc:
        log.warning("knowledge_patterns_failed", error=str(exc))
        return {"patterns": [], "error": str(exc)}


@app.post("/knowledge/learn", tags=["Knowledge"])
async def learn_from_defect(req: LearnRequest) -> dict[str, Any]:
    """Alimenta o Knowledge Layer com um defeito histórico."""
    if not _knowledge:
        raise HTTPException(503, "Knowledge Layer não inicializado.")
    try:
        from ai_engine.knowledge.learning.engine import DefectRecord
        record = DefectRecord(
            id=f"DEF-{uuid4().hex[:6].upper()}",
            title=req.title,
            severity=req.severity,
            domain=req.domain,
            description=req.description,
        )
        patterns = await _knowledge.learn_from_defect(record)
        return {
            "learned":  True,
            "domain":   req.domain,
            "patterns": len(patterns) if patterns else 0,
        }
    except Exception as exc:
        log.warning("knowledge_learn_failed", error=str(exc))
        raise HTTPException(500, str(exc))


@app.get("/knowledge/suggestions", tags=["Knowledge"])
async def get_suggestions(
    requirement_text: str = Query(...),
    domain:           str = Query(""),
) -> dict[str, Any]:
    """Sugestões preventivas para um requisito baseadas no histórico organizacional."""
    if not _knowledge:
        return {"suggestions": []}
    try:
        suggestions = await _knowledge.suggest_for(
            requirement_text=requirement_text,
            domain=domain or None,
        )
        return {
            "suggestions": [
                {
                    "title":       s.title,
                    "description": s.description,
                    "priority":    s.priority,
                    "confidence":  s.confidence,
                    "action_items":s.action_items,
                }
                for s in (suggestions or [])
            ]
        }
    except Exception as exc:
        log.warning("knowledge_suggestions_failed", error=str(exc))
        return {"suggestions": [], "error": str(exc)}


# ════════════════════════════════════════════════════════════════════════════
# QUALITY POLICY (Blueprint §5.7)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/policy/evaluate", tags=["Quality Policy"])
async def evaluate_policy(req: PolicyEvaluateRequest) -> dict[str, Any]:
    """Avalia quality gates de uma Story ou Flow."""
    if not _policy:
        raise HTTPException(503, "Policy Engine não inicializado.")
    try:
        from runtime_core.quality_policy.engine import PolicyEngine
        ctx = _policy.build_story_context(**req.context) if req.context else _policy.build_story_context()
        report = await _policy.evaluate_story(req.subject_id, ctx)
        return {
            "subject_id":        report.subject_id,
            "policy_name":       report.policy_name,
            "passed":            report.passed,
            "blocking_failures": report.blocking_failures,
            "warnings":          report.warnings,
            "gate_summary":      report.gate_summary,
            "failed_gates":      report.failed_gates,
        }
    except Exception as exc:
        log.warning("policy_evaluate_failed", error=str(exc))
        raise HTTPException(500, str(exc))


# ════════════════════════════════════════════════════════════════════════════
# REQUIREMENTS — análise legada + nova (mantida para compatibilidade)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/requirements/analyze", tags=["Requirements"])
async def analyze_requirement(req: AmbiguityRequest) -> dict[str, Any]:
    """
    Análise de requisito via CognitivePipeline v2.
    Substitui o RequirementAgent direto — agora usa o pipeline completo.
    """
    if _cognitive:
        result = await _cognitive.run(
            input_text=req.requirement_text,
            requirement_id=req.requirement_id,
            skip_fanout=False,
        )
        return result.to_api_response()

    # Fallback: RequirementAgent direto
    try:
        from ai_engine.requirement_agent.agent import RequirementAgent
        agent    = RequirementAgent()
        analysis = await agent.analyze(
            requirement_text=req.requirement_text,
            requirement_id=req.requirement_id,
        )
        return {
            "requirement_id":     analysis.requirement_id,
            "interpreted_intent": analysis.interpreted_intent,
            "business_rules":     [{"description": r.description} for r in analysis.business_rules],
            "ambiguities":        analysis.ambiguities,
            "gaps":               analysis.gaps,
            "suggested_scenarios":analysis.suggested_scenarios,
            "risk_level":         analysis.risk_level,
            "generated_flow_dsl": analysis.generated_flow_dsl,
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/requirements/ambiguity", tags=["Requirements"])
async def analyze_ambiguity(req: AmbiguityRequest) -> dict[str, Any]:
    """Ambiguity Engine — regras determinísticas (offline)."""
    from ai_engine.ambiguity_engine.analyzer import AmbiguityAnalyzer
    analyzer = AmbiguityAnalyzer(mode="rules_only")
    report   = await analyzer.analyze(
        requirement_text=req.requirement_text,
        requirement_id=req.requirement_id,
    )
    return report.summary()


@app.post("/requirements/ambiguity/full", tags=["Requirements"])
async def analyze_ambiguity_full(req: AmbiguityRequest) -> dict[str, Any]:
    """Ambiguity Engine com Claude — análise profunda."""
    from ai_engine.ambiguity_engine.analyzer import AmbiguityAnalyzer
    analyzer = AmbiguityAnalyzer(mode="full")
    report   = await analyzer.analyze(
        requirement_text=req.requirement_text,
        requirement_id=req.requirement_id,
    )
    return {
        **report.summary(),
        "ambiguities": [
            {
                "id": a.id, "type": a.type, "severity": a.severity,
                "text": a.text, "question": a.question,
                "excerpt": a.excerpt, "options": a.options,
                "impact": a.impact, "scenario_hint": a.scenario_hint,
            }
            for a in report.ambiguities
        ],
        "business_rules": [
            {"id": r.id, "description": r.description,
             "source": r.source, "confidence": r.confidence}
            for r in report.business_rules
        ],
        "gaps": [
            {"id": g.id, "description": g.description,
             "gap_type": g.gap_type, "priority": g.priority}
            for g in report.gaps
        ],
    }


# ════════════════════════════════════════════════════════════════════════════
# Background tasks
# ════════════════════════════════════════════════════════════════════════════

async def _run_execution_bg(
    flow:    Flow,
    context: RuntimeContext,
    exec_id: str,
    dry_run: bool,
) -> None:
    from runtime_core.adapters.robot.robot_adapter import RobotAdapter
    from runtime_core.execution_engine.engine import ExecutionEngine
    from runtime_core.evidence_engine.collector import EvidenceCollector, TraceabilityEngine

    adapter  = RobotAdapter(base_url=context.project.base_url or "http://localhost:4200")
    engine   = ExecutionEngine(adapter=adapter)
    evidence = EvidenceCollector()
    tracer   = TraceabilityEngine()

    try:
        report = await engine.execute_flow(flow, context)
        _reports[exec_id] = report

        evidence_paths = evidence.collect_from_report(report)
        report.evidence_paths = evidence_paths
        tracer.from_report(report)

        # Registrar no histórico
        _exec_history.append({
            "execution_id":     exec_id,
            "flow_name":        flow.name,
            "flow_id":          str(flow.id),
            "status":           report.status.value,
            "total_scenarios":  len(report.scenario_results),
            "passed_scenarios": sum(1 for s in report.scenario_results if s.passed),
            "failed_scenarios": sum(1 for s in report.scenario_results if not s.passed),
            "duration_ms":      report.duration_ms,
            "finished_at":      datetime.utcnow().isoformat(),
        })

        # Persistir no grafo se DB disponível
        if _db:
            try:
                from runtime_core.persistence.graph.models import Node
                node = Node(
                    label="Execution",
                    external_id=exec_id,
                    properties=_exec_history[-1],
                )
                await _db.add_node(node)
            except Exception:
                pass

        log.info("execution_done", exec_id=exec_id, status=report.status)
    except Exception as exc:
        log.error("execution_error", exec_id=exec_id, error=str(exc))


# ── Dev entrypoint ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("runtime_core.api:app", host="0.0.0.0", port=8080, reload=True)
