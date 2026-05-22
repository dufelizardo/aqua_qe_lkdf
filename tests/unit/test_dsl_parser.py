"""
tests/unit/test_dsl_parser.py
AQuA-QE LKDF — Unit Tests: DSL Parser & Semantic Engine
"""
from __future__ import annotations

import sys
from pathlib import Path

# Adjust path for monorepo imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from runtime_core.parser.dsl_parser import DSLParser, DSLParseError, tokenize, validate_dsl, TokenType
from runtime_core.semantic_engine.intent_resolver import IntentResolver, ContextAnalyzer
from shared.models import AdapterType, Priority, StepType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_DSL = """\
# Flow: LoginFlow
# Requirement: REQ-001 — Login deve ser autenticado
# Adapter: robot-framework
# Priority: HIGH

@flow LoginFlow
  @scenario ValidLogin
    Dado que o usuário está na página de login
    E que o usuário possui credenciais válidas
    Quando o usuário insere "usuario@empresa.com" no campo email
    E o usuário insere "senha123" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que o usuário seja redirecionado para o dashboard
    E é esperado que a mensagem "Login realizado com sucesso" seja exibida

  @scenario InvalidLogin
    Dado que o usuário está na página de login
    Quando o usuário insere "errado@email.com" no campo email
    E o usuário insere "senhaerrada" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Credenciais inválidas" seja exibida
"""

INVALID_DSL_NO_FLOW = """\
@scenario SomeScenario
  Dado que algo existe
  Então é esperado resultado
"""

INVALID_DSL_NO_STEPS = """\
@flow EmptyFlow
  @scenario EmptyScenario
"""


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------

class TestTokenizer:

    def test_tokenizes_flow_definition(self):
        tokens = list(tokenize("@flow LoginFlow"))
        assert tokens[0].type == TokenType.FLOW_DEF
        assert tokens[0].value == "LoginFlow"

    def test_tokenizes_scenario_definition(self):
        tokens = list(tokenize("@scenario ValidLogin"))
        assert tokens[0].type == TokenType.SCENARIO_DEF
        assert tokens[0].value == "ValidLogin"

    def test_tokenizes_meta_comment(self):
        tokens = list(tokenize("# Requirement: REQ-001 — Test"))
        assert tokens[0].type == TokenType.META
        assert "Requirement" in tokens[0].value

    def test_tokenizes_step(self):
        tokens = list(tokenize("Dado que o usuário está na página"))
        assert tokens[0].type == TokenType.STEP

    def test_tokenizes_blank_line(self):
        tokens = list(tokenize("\n"))  # newline produces one blank token
        assert len(tokens) >= 1
        assert tokens[0].type == TokenType.BLANK

    def test_tokenizes_empty_string_yields_nothing(self):
        tokens = list(tokenize(""))
        assert tokens == []

    def test_tokenizes_multiline(self):
        tokens = list(tokenize(VALID_DSL))
        flow_tokens = [t for t in tokens if t.type == TokenType.FLOW_DEF]
        scenario_tokens = [t for t in tokens if t.type == TokenType.SCENARIO_DEF]
        step_tokens = [t for t in tokens if t.type == TokenType.STEP]
        assert len(flow_tokens) == 1
        assert len(scenario_tokens) == 2
        assert len(step_tokens) >= 10


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestDSLValidator:

    def test_valid_dsl_passes(self):
        result = validate_dsl(VALID_DSL)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_flow_fails(self):
        result = validate_dsl(INVALID_DSL_NO_FLOW)
        assert result.valid is False
        assert any("@flow" in e.message for e in result.errors)

    def test_missing_steps_fails(self):
        result = validate_dsl(INVALID_DSL_NO_STEPS)
        assert result.valid is False

    def test_empty_string_fails(self):
        result = validate_dsl("")
        assert result.valid is False


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestDSLParser:
    parser = DSLParser()

    def test_parses_flow_name(self):
        flow = self.parser.parse(VALID_DSL)
        assert flow.name == "LoginFlow"

    def test_parses_adapter(self):
        flow = self.parser.parse(VALID_DSL)
        assert flow.adapter == AdapterType.ROBOT

    def test_parses_priority(self):
        flow = self.parser.parse(VALID_DSL)
        assert flow.priority == Priority.HIGH

    def test_parses_requirement_ref(self):
        flow = self.parser.parse(VALID_DSL)
        assert "REQ-001" in flow.requirement_ref

    def test_parses_scenarios_count(self):
        flow = self.parser.parse(VALID_DSL)
        assert len(flow.scenarios) == 2

    def test_parses_scenario_names(self):
        flow = self.parser.parse(VALID_DSL)
        names = [s.name for s in flow.scenarios]
        assert "ValidLogin" in names
        assert "InvalidLogin" in names

    def test_parses_steps(self):
        flow = self.parser.parse(VALID_DSL)
        first_scenario = flow.scenarios[0]
        assert len(first_scenario.steps) > 0

    def test_step_types_resolved(self):
        flow = self.parser.parse(VALID_DSL)
        types = {s.step_type for s in flow.scenarios[0].steps}
        assert StepType.GIVEN in types
        assert StepType.WHEN in types
        assert StepType.THEN in types

    def test_extracts_parameters_from_steps(self):
        flow = self.parser.parse(VALID_DSL)
        steps_with_params = [
            s for s in flow.scenarios[0].steps if s.parameters
        ]
        assert len(steps_with_params) > 0

    def test_invalid_dsl_raises(self):
        with pytest.raises(DSLParseError):
            self.parser.parse(INVALID_DSL_NO_FLOW)

    def test_flow_has_uuid(self):
        flow = self.parser.parse(VALID_DSL)
        assert flow.id is not None

    def test_scenarios_have_uuids(self):
        flow = self.parser.parse(VALID_DSL)
        for s in flow.scenarios:
            assert s.id is not None


# ---------------------------------------------------------------------------
# Intent Resolver tests
# ---------------------------------------------------------------------------

class TestIntentResolver:
    resolver = IntentResolver()

    def _make_step(self, text: str, step_type=StepType.WHEN):
        from shared.models import SemanticStep, StepKeyword
        return SemanticStep(
            keyword=StepKeyword.QUANDO,
            step_type=step_type,
            text=text,
        )

    def test_resolves_fill_intent(self):
        step = self._make_step('Quando o usuário insere "test@test.com" no campo email')
        resolved = self.resolver.resolve(step)
        assert resolved.intent == "fill_field"
        assert resolved.action == "fill"

    def test_resolves_click_intent(self):
        step = self._make_step('Quando o usuário clica no botão "Entrar"')
        resolved = self.resolver.resolve(step)
        assert resolved.intent == "click"
        assert resolved.action == "click_element"

    def test_resolves_assert_message(self):
        step = self._make_step('Então é esperado que a mensagem "Erro" seja exibida', StepType.THEN)
        resolved = self.resolver.resolve(step)
        assert "assert" in resolved.intent

    def test_resolves_navigate(self):
        step = self._make_step("Dado que o usuário está na página de login", StepType.GIVEN)
        resolved = self.resolver.resolve(step)
        assert resolved.intent == "navigate"

    def test_extracts_parameter_from_fill(self):
        step = self._make_step('Quando o usuário insere "usuario@empresa.com" no campo email')
        resolved = self.resolver.resolve(step)
        assert "value" in resolved.entities
        assert resolved.entities["value"] == "usuario@empresa.com"

    def test_confidence_is_between_0_and_1(self):
        step = self._make_step("Quando o usuário clica no botão Entrar")
        resolved = self.resolver.resolve(step)
        assert 0.0 <= resolved.confidence <= 1.0

    def test_enrich_step(self):
        step = self._make_step('Quando o usuário insere "abc" no campo email')
        enriched = self.resolver.enrich_step(step)
        assert enriched.intent == "fill_field"
        assert enriched.action == "fill"


# ---------------------------------------------------------------------------
# Context Analyzer tests
# ---------------------------------------------------------------------------

class TestContextAnalyzer:
    analyzer = ContextAnalyzer()

    def test_analyzes_full_scenario(self):
        parser = DSLParser()
        flow   = parser.parse(VALID_DSL)
        steps  = flow.scenarios[0].steps

        analysis = self.analyzer.analyze_scenario(steps)
        assert "intents" in analysis
        assert analysis["has_navigation"] is True
        assert analysis["has_assertions"] is True
        assert 0.0 <= analysis["coverage_score"] <= 1.0
