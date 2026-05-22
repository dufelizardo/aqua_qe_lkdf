"""
runtime_core/scenario_engine/engine.py
AQuA-QE LKDF — Scenario Engine

Responsável por:
  - Compor e enriquecer Scenarios a partir de Flows
  - Gerar datasets de parametrização (data-driven testing)
  - Expandir scenarios com variações automáticas (negative, boundary, edge)
  - Analisar cobertura de scenarios por requisito
  - Priorizar execução por risco e impacto
  - Detectar duplicatas e conflitos entre scenarios
"""
from __future__ import annotations

import hashlib
import itertools
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

import structlog

from shared.models import Flow, Priority, Scenario, SemanticStep, StepType

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Scenario types
# ---------------------------------------------------------------------------

class ScenarioCategory(str, Enum):
    HAPPY_PATH   = "happy_path"
    NEGATIVE     = "negative"
    BOUNDARY     = "boundary"
    EDGE_CASE    = "edge_case"
    PERFORMANCE  = "performance"
    SECURITY     = "security"
    REGRESSION   = "regression"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

@dataclass
class TestDataset:
    """Conjunto de parâmetros para execução data-driven."""
    name: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    def from_boundary_values(
        cls,
        field_name: str,
        valid: list[Any],
        invalid: list[Any],
        boundary: list[Any] | None = None,
    ) -> "TestDataset":
        rows: list[dict[str, Any]] = []
        for v in valid:
            rows.append({field_name: v, "expected": "success", "type": "valid"})
        for v in invalid:
            rows.append({field_name: v, "expected": "error", "type": "invalid"})
        for v in (boundary or []):
            rows.append({field_name: v, "expected": "boundary", "type": "boundary"})
        return cls(name=f"dataset_{field_name}", rows=rows)


# ---------------------------------------------------------------------------
# Composed Scenario
# ---------------------------------------------------------------------------

@dataclass
class ComposedScenario:
    """
    Scenario enriquecido pelo Scenario Engine com metadados de execução.
    """
    scenario: Scenario
    category: ScenarioCategory
    dataset: TestDataset | None = None
    priority_score: float = 0.5     # 0.0 = baixíssima, 1.0 = crítica
    estimated_duration_ms: int = 0
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)   # scenario names
    coverage_contribution: dict[str, bool] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Hash único do scenario para detecção de duplicatas."""
        content = "|".join(s.text for s in self.scenario.steps)
        return hashlib.md5(content.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Coverage Report
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    requirement_id: str
    flow_name: str
    total_scenarios: int
    by_category: dict[str, int] = field(default_factory=dict)
    has_happy_path: bool = False
    has_negative: bool = False
    has_boundary: bool = False
    coverage_score: float = 0.0
    gaps: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scenario Engine
# ---------------------------------------------------------------------------

class ScenarioEngine:
    """
    Motor de composição e gestão de Scenarios do LKDF.

    Recebe um Flow (parsado pelo DSL Parser) e produz ScenarioS enriquecidos,
    prontos para execução pelo Execution Engine.
    """

    def __init__(self) -> None:
        self._fingerprints: set[str] = set()

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def compose(self, flow: Flow) -> list[ComposedScenario]:
        """
        Ponto de entrada principal.
        Recebe um Flow e retorna lista de ComposedScenario prontos para execução.
        """
        composed: list[ComposedScenario] = []
        self._fingerprints.clear()

        for scenario in flow.scenarios:
            category   = self._classify_scenario(scenario)
            priority   = self._calculate_priority(scenario, flow.priority, category)
            duration   = self._estimate_duration(scenario)
            composed_s = ComposedScenario(
                scenario=scenario,
                category=category,
                priority_score=priority,
                estimated_duration_ms=duration,
                tags=scenario.tags + [category.value],
                coverage_contribution=self._coverage_map(scenario),
            )

            # Detect duplicate
            fp = composed_s.fingerprint
            if fp in self._fingerprints:
                log.warning("scenario_duplicate_detected", name=scenario.name)
                continue
            self._fingerprints.add(fp)

            composed.append(composed_s)

        # Sort by priority (highest first)
        composed.sort(key=lambda c: c.priority_score, reverse=True)

        log.info(
            "scenario_engine_compose",
            flow=flow.name,
            total=len(composed),
            categories={c.value: sum(1 for s in composed if s.category == c)
                        for c in ScenarioCategory},
        )
        return composed

    def expand_with_variations(
        self,
        composed: list[ComposedScenario],
        max_variations: int = 3,
    ) -> list[ComposedScenario]:
        """
        Gera variações automáticas de scenarios existentes:
        - Para cada HappyPath, gera negative variation
        - Para campos de input, gera boundary variations
        """
        expanded: list[ComposedScenario] = list(composed)

        for c in composed:
            if c.category != ScenarioCategory.HAPPY_PATH:
                continue
            if len(expanded) >= len(composed) + max_variations:
                break

            # Negative variation
            neg = self._generate_negative_variation(c)
            if neg and neg.fingerprint not in self._fingerprints:
                self._fingerprints.add(neg.fingerprint)
                expanded.append(neg)

        return expanded

    def build_dataset(
        self,
        scenario: Scenario,
        field_specs: dict[str, dict[str, list[Any]]],
    ) -> TestDataset:
        """
        Gera dataset para data-driven testing de um scenario.
        field_specs: {"email": {"valid": [...], "invalid": [...], "boundary": [...]}}
        """
        rows: list[dict[str, Any]] = [{}]

        for field_name, spec in field_specs.items():
            new_rows: list[dict[str, Any]] = []
            for row in rows:
                for v in spec.get("valid", []):
                    new_rows.append({**row, field_name: v, f"{field_name}_type": "valid"})
                for v in spec.get("invalid", []):
                    new_rows.append({**row, field_name: v, f"{field_name}_type": "invalid"})
                for v in spec.get("boundary", []):
                    new_rows.append({**row, field_name: v, f"{field_name}_type": "boundary"})
            rows = new_rows

        return TestDataset(
            name=f"dataset_{scenario.name}",
            rows=rows,
            description=f"Dataset gerado para: {scenario.name}",
        )

    def analyze_coverage(self, flow: Flow) -> CoverageReport:
        """
        Analisa a cobertura de um Flow e gera recomendações.
        Implementa o critério de aceite Fase 1: recomendar cobertura de cenários.
        """
        composed = self.compose(flow)
        categories = {c.category for c in composed}

        has_happy    = ScenarioCategory.HAPPY_PATH in categories
        has_negative = ScenarioCategory.NEGATIVE   in categories
        has_boundary = ScenarioCategory.BOUNDARY   in categories

        # Coverage score: 0-100
        score = 0.0
        if has_happy:    score += 40.0
        if has_negative: score += 30.0
        if has_boundary: score += 20.0
        if len(composed) >= 3: score += 10.0

        gaps: list[str] = []
        recs: list[str] = []

        if not has_happy:
            gaps.append("Nenhum cenário de Happy Path definido.")
            recs.append("Adicione um scenario com o fluxo principal de sucesso.")
        if not has_negative:
            gaps.append("Nenhum cenário negativo (dados inválidos, erros).")
            recs.append("Adicione scenarios para entradas inválidas e estados de erro.")
        if not has_boundary:
            gaps.append("Nenhum teste de valores de borda.")
            recs.append("Considere testar limites: campo vazio, tamanho máximo, caracteres especiais.")
        if len(composed) < 3:
            recs.append(f"Flow tem apenas {len(composed)} scenario(s). Recomendado: mínimo 3.")

        # Check assertion coverage
        all_steps = [s for sc in flow.scenarios for s in sc.steps]
        assertion_steps = [s for s in all_steps if s.step_type == StepType.THEN]
        if len(assertion_steps) < len(flow.scenarios):
            gaps.append("Alguns scenarios não têm assertions (Então/Entao).")
            recs.append("Cada scenario deve verificar pelo menos um resultado esperado.")

        by_category = {
            c.value: sum(1 for s in composed if s.category == c)
            for c in ScenarioCategory
        }

        return CoverageReport(
            requirement_id=flow.requirement_ref,
            flow_name=flow.name,
            total_scenarios=len(composed),
            by_category=by_category,
            has_happy_path=has_happy,
            has_negative=has_negative,
            has_boundary=has_boundary,
            coverage_score=score,
            gaps=gaps,
            recommendations=recs,
        )

    def prioritize(
        self,
        composed: list[ComposedScenario],
        risk_weight: float = 0.4,
        coverage_weight: float = 0.4,
        duration_weight: float = 0.2,
    ) -> list[ComposedScenario]:
        """
        Reordena scenarios por score de prioridade ponderado.
        Usado para smoke runs e execuções parciais por tempo.
        """
        max_dur = max((c.estimated_duration_ms for c in composed), default=1)

        def score(c: ComposedScenario) -> float:
            risk     = c.priority_score * risk_weight
            coverage = (1.0 if c.category == ScenarioCategory.HAPPY_PATH else 0.5) * coverage_weight
            speed    = (1.0 - c.estimated_duration_ms / max_dur) * duration_weight
            return risk + coverage + speed

        return sorted(composed, key=score, reverse=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_scenario(self, scenario: Scenario) -> ScenarioCategory:
        """Classifica um scenario por categoria baseado nos steps e nome."""
        name_lower = scenario.name.lower()
        steps_text = " ".join(s.text.lower() for s in scenario.steps)

        negative_signals = [
            "inválid", "invalid", "error", "erro", "falha", "fail",
            "bloqueado", "blocked", "negativ", "wrong", "errado",
            "inexistent", "não encontrado", "vazio", "empty",
        ]
        boundary_signals = [
            "limite", "boundary", "máximo", "mínimo", "max", "min",
            "borda", "edge", "overflow", "caracteres especiais",
        ]
        security_signals = [
            "injeção", "injection", "sql", "xss", "csrf", "script",
            "permissão", "autorização", "unauthorized", "forbidden",
        ]

        combined = name_lower + " " + steps_text

        if any(s in combined for s in security_signals):
            return ScenarioCategory.SECURITY
        if any(s in combined for s in boundary_signals):
            return ScenarioCategory.BOUNDARY
        if any(s in combined for s in negative_signals):
            return ScenarioCategory.NEGATIVE

        return ScenarioCategory.HAPPY_PATH

    def _calculate_priority(
        self,
        scenario: Scenario,
        flow_priority: Priority,
        category: ScenarioCategory,
    ) -> float:
        """Calcula score de prioridade 0.0-1.0."""
        base = {
            Priority.HIGH:   0.8,
            Priority.MEDIUM: 0.5,
            Priority.LOW:    0.2,
        }[flow_priority]

        category_bonus = {
            ScenarioCategory.HAPPY_PATH:  0.15,
            ScenarioCategory.NEGATIVE:    0.10,
            ScenarioCategory.SECURITY:    0.20,
            ScenarioCategory.BOUNDARY:    0.05,
            ScenarioCategory.EDGE_CASE:   0.05,
            ScenarioCategory.PERFORMANCE: 0.00,
            ScenarioCategory.REGRESSION:  0.00,
        }[category]

        # Scenarios with more assertions are higher priority
        assertion_count = sum(1 for s in scenario.steps if s.step_type == StepType.THEN)
        assertion_bonus = min(0.1, assertion_count * 0.03)

        return min(1.0, base + category_bonus + assertion_bonus)

    def _estimate_duration(self, scenario: Scenario) -> int:
        """Estima duração em ms baseado nos tipos de steps."""
        durations = {
            StepType.GIVEN:  200,   # setup steps
            StepType.WHEN:   400,   # action steps (click, fill)
            StepType.THEN:   300,   # assertion steps
            StepType.AND:    300,   # continuation
        }
        total = sum(durations.get(s.step_type, 300) for s in scenario.steps)
        # Add overhead: page load, screenshots, etc.
        return total + 500

    def _coverage_map(self, scenario: Scenario) -> dict[str, bool]:
        """Mapa de cobertura por tipo de verificação."""
        types = {s.step_type for s in scenario.steps}
        intents = {s.intent for s in scenario.steps}
        return {
            "has_navigation":    "navigate" in intents or "open_page" in intents,
            "has_input":         "fill_field" in intents,
            "has_action":        "click" in intents,
            "has_assertion":     StepType.THEN in types,
            "has_given":         StepType.GIVEN in types,
            "has_when":          StepType.WHEN in types,
        }

    def _generate_negative_variation(
        self, original: ComposedScenario
    ) -> ComposedScenario | None:
        """
        Gera variação negativa de um HappyPath scenario.
        Modifica steps de input para usar dados inválidos.
        """
        new_steps: list[SemanticStep] = []
        modified = False

        for step in original.scenario.steps:
            if step.intent == "fill_field" and "value" in step.parameters:
                # Inject invalid data
                invalid_value = self._invalid_value_for(step.parameters["value"])
                new_params = {**step.parameters, "value": invalid_value}
                new_step = step.model_copy(update={
                    "parameters": new_params,
                    "text": step.text.replace(
                        f'"{step.parameters["value"]}"',
                        f'"{invalid_value}"',
                    ),
                })
                new_steps.append(new_step)
                modified = True
            elif step.step_type == StepType.THEN and "assert_message" in step.intent:
                # Change expected message to error
                new_steps.append(step.model_copy(update={
                    "text": "Então é esperado que uma mensagem de erro seja exibida",
                    "parameters": {**step.parameters, "text": "erro"},
                }))
            else:
                new_steps.append(step)

        if not modified:
            return None

        new_scenario = Scenario(
            name=f"{original.scenario.name}_NegativePath",
            description="Variação negativa gerada automaticamente pelo Scenario Engine",
            steps=new_steps,
            tags=original.scenario.tags + ["auto-generated", "negative"],
            requirement_ref=original.scenario.requirement_ref,
        )

        return ComposedScenario(
            scenario=new_scenario,
            category=ScenarioCategory.NEGATIVE,
            priority_score=original.priority_score * 0.8,
            estimated_duration_ms=original.estimated_duration_ms,
            tags=["auto-generated", "negative"],
        )

    @staticmethod
    def _invalid_value_for(value: str) -> str:
        """Gera valor inválido correspondente ao valor válido."""
        if "@" in value:        # email
            return "nao-e-um-email"
        if value.isdigit():     # number
            return "-1"
        if len(value) > 5:     # long string → empty
            return ""
        return "INVALIDO_TESTE"
