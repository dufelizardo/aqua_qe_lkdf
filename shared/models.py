"""
shared/models.py
AQuA-QE LKDF — Domain Models & Contracts
Camada de contratos compartilhados entre todos os módulos do Runtime Core.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class StepKeyword(str, Enum):
    DADO = "Dado"
    E = "E"
    QUANDO = "Quando"
    ENTAO = "Então"
    MAS = "Mas"


class StepType(str, Enum):
    GIVEN = "given"
    WHEN = "when"
    THEN = "then"
    AND = "and"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class AdapterType(str, Enum):
    ROBOT = "robot-framework"
    PLAYWRIGHT = "playwright"
    CYPRESS = "cypress"
    SELENIUM = "selenium"
    API = "api"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ---------------------------------------------------------------------------
# POM Layer
# ---------------------------------------------------------------------------

class Locator(BaseModel):
    strategy: str = "css"          # css | xpath | id | testid | text
    value: str
    description: str = ""


class PageElement(BaseModel):
    name: str
    locator: Locator
    page: str


class PageObject(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    url_pattern: str = ""
    elements: dict[str, PageElement] = {}
    actions: dict[str, str] = {}    # action_name -> keyword


# ---------------------------------------------------------------------------
# Flow Layer  (DSL semântica)
# ---------------------------------------------------------------------------

class SemanticStep(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    keyword: StepKeyword
    step_type: StepType
    text: str
    intent: str = ""                # resolved intent
    action: str = ""                # mapped action
    parameters: dict[str, Any] = {}
    raw_line: str = ""


class Scenario(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    tags: list[str] = []
    steps: list[SemanticStep] = []
    priority: Priority = Priority.MEDIUM
    requirement_ref: str = ""


class Flow(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    requirement_ref: str = ""
    adapter: AdapterType = AdapterType.ROBOT
    priority: Priority = Priority.MEDIUM
    tags: list[str] = []
    scenarios: list[Scenario] = []
    metadata: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Execution Layer
# ---------------------------------------------------------------------------

class StepResult(BaseModel):
    step_id: UUID
    status: ExecutionStatus
    duration_ms: int = 0
    message: str = ""
    screenshot_path: str | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ScenarioResult(BaseModel):
    scenario_id: UUID
    scenario_name: str
    status: ExecutionStatus
    step_results: list[StepResult] = []
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None


class ExecutionReport(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    flow_id: UUID
    flow_name: str
    adapter: AdapterType
    status: ExecutionStatus = ExecutionStatus.PENDING
    scenario_results: list[ScenarioResult] = []
    total_scenarios: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    evidence_paths: list[str] = []
    requirement_ref: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_scenarios == 0:
            return 0.0
        return self.passed / self.total_scenarios * 100


# ---------------------------------------------------------------------------
# Traceability Layer
# ---------------------------------------------------------------------------

class TraceEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    requirement_id: str
    business_rule: str = ""
    flow_id: UUID | None = None
    flow_name: str = ""
    scenario_id: UUID | None = None
    scenario_name: str = ""
    execution_id: UUID | None = None
    execution_status: ExecutionStatus | None = None
    evidence_paths: list[str] = []
    defect_refs: list[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Context Layer
# ---------------------------------------------------------------------------

class ProjectContext(BaseModel):
    """Contexto do projeto coletado via Requirement Intake."""
    project_name: str = ""
    framework: str = ""             # Angular, React, Vue...
    has_rest_api: bool = False
    has_graphql: bool = False
    auth_type: str = ""             # JWT, OAuth2, Session...
    use_bdd: bool = True
    locator_strategy: str = "css"
    adapter: AdapterType = AdapterType.ROBOT
    base_url: str = ""
    extra: dict[str, Any] = {}


class RuntimeContext(BaseModel):
    """Contexto enriquecido em runtime para cada execução."""
    execution_id: UUID = Field(default_factory=uuid4)
    flow: Flow | None = None
    project: ProjectContext = Field(default_factory=ProjectContext)
    variables: dict[str, Any] = {}
    current_page: str = ""
    state: dict[str, Any] = {}
