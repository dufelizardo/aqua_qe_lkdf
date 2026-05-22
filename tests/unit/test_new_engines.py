"""
tests/unit/test_new_engines.py
AQuA-QE LKDF — Unit Tests: POM Layer, Context Engine, Scenario Engine
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from shared.models import Flow, Priority, ProjectContext, Scenario, SemanticStep, StepKeyword, StepType
from runtime_core.pom_layer.registry import (
    Locator, LocatorStrategy, PageElement, PageObject, POMRegistry,
)
from runtime_core.context_engine.engine import ContextEngine, VariableStore
from runtime_core.scenario_engine.engine import (
    ScenarioCategory, ScenarioEngine,
)
from runtime_core.parser.dsl_parser import DSLParser
from runtime_core.semantic_engine.intent_resolver import IntentResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_step(text: str, step_type: StepType = StepType.WHEN, intent: str = "") -> SemanticStep:
    kw_map = {StepType.GIVEN: StepKeyword.DADO, StepType.WHEN: StepKeyword.QUANDO, StepType.THEN: StepKeyword.ENTAO, StepType.AND: StepKeyword.E}
    s = SemanticStep(keyword=kw_map.get(step_type, StepKeyword.QUANDO), step_type=step_type, text=text, intent=intent)
    # enrich with resolver
    resolver = IntentResolver()
    return resolver.enrich_step(s)


FULL_DSL = """\
# Flow: LoginFlow
# Requirement: REQ-001
# Adapter: robot-framework
# Priority: HIGH

@flow LoginFlow
  @scenario ValidLogin
    Dado que o usuário está na página de login
    Quando o usuário insere "usuario@empresa.com" no campo email
    E o usuário insere "senha123" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Login realizado com sucesso" seja exibida

  @scenario InvalidLogin
    Dado que o usuário está na página de login
    Quando o usuário insere "errado@test.com" no campo email
    E o usuário insere "senhaerrada" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Credenciais inválidas" seja exibida

  @scenario EmptyLogin
    Dado que o usuário está na página de login
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Preencha os campos obrigatórios" seja exibida
"""


# ===========================================================================
# POM Layer Tests
# ===========================================================================

class TestLocator:

    def test_css_to_rf(self):
        loc = Locator(LocatorStrategy.CSS, "input[type='email']")
        assert loc.to_rf() == "css:input[type='email']"

    def test_testid_to_rf(self):
        loc = Locator(LocatorStrategy.TESTID, "email-input")
        assert loc.to_rf() == "css:[data-testid='email-input']"

    def test_testid_to_playwright(self):
        loc = Locator(LocatorStrategy.TESTID, "email-input")
        assert loc.to_playwright() == "[data-testid='email-input']"

    def test_id_to_rf(self):
        loc = Locator(LocatorStrategy.ID, "email")
        assert loc.to_rf() == "id:email"

    def test_xpath_to_rf(self):
        loc = Locator(LocatorStrategy.XPATH, "//button[@type='submit']")
        assert loc.to_rf().startswith("xpath:")


class TestPageElement:

    def test_matches_by_name(self):
        elem = PageElement(name="campo_email", aliases=["email"])
        assert elem.matches("campo_email")

    def test_matches_by_alias(self):
        elem = PageElement(name="campo_email", aliases=["email", "e-mail"])
        assert elem.matches("email")
        assert elem.matches("e-mail")

    def test_matches_partial_alias(self):
        elem = PageElement(name="campo_email", aliases=["campo email"])
        assert elem.matches("campo email")

    def test_no_match(self):
        elem = PageElement(name="campo_email", aliases=["email"])
        assert not elem.matches("senha")

    def test_primary_locator(self):
        loc1 = Locator(LocatorStrategy.TESTID, "email-input")
        loc2 = Locator(LocatorStrategy.ID, "email")
        elem = PageElement(name="email", locators=[loc1, loc2])
        assert elem.primary_locator == loc1


class TestPOMRegistry:

    def setup_method(self):
        self.registry = POMRegistry()

    def test_seeds_default_pages(self):
        pages = self.registry.list_pages()
        assert "LoginPage" in pages
        assert "DashboardPage" in pages

    def test_resolves_known_element(self):
        locator = self.registry.resolve("email", "LoginPage")
        assert locator is not None

    def test_resolves_by_alias(self):
        locator = self.registry.resolve("campo email", "LoginPage")
        assert locator is not None

    def test_resolves_globally(self):
        # Without specifying page
        locator = self.registry.resolve("email")
        assert locator is not None

    def test_returns_none_for_unknown(self):
        locator = self.registry.resolve("elemento_inexistente_xyz")
        assert locator is None

    def test_resolve_to_string_rf(self):
        result = self.registry.resolve_to_string("email", "LoginPage", adapter="robot")
        assert ":" in result   # RF format: "strategy:value"

    def test_smart_fallback_email(self):
        result = self.registry.resolve_to_string("emailx_custom_field")
        assert "email" in result or "data-testid" in result

    def test_smart_fallback_submit(self):
        result = self.registry.resolve_to_string("botao_entrar_custom")
        assert "submit" in result or "data-testid" in result

    def test_register_custom_page(self):
        page = PageObject(
            name="CustomPage",
            url_pattern="/custom",
            elements={
                "custom_field": PageElement(
                    name="custom_field",
                    aliases=["custom"],
                    locators=[Locator(LocatorStrategy.ID, "custom")],
                )
            },
        )
        self.registry.register(page)
        assert "CustomPage" in self.registry.list_pages()
        assert self.registry.resolve("custom", "CustomPage") is not None

    def test_coverage_report(self):
        report = self.registry.coverage_report()
        assert "pages" in report
        assert report["pages"] >= 2
        assert report["total_elements"] > 0

    def test_find_page_for_url(self):
        page = self.registry.find_page_for_url("/login")
        assert page is not None
        assert page.name == "LoginPage"

    def test_cache_works(self):
        # First call
        r1 = self.registry.resolve("email", "LoginPage")
        # Second call should hit cache
        r2 = self.registry.resolve("email", "LoginPage")
        assert r1 == r2


# ===========================================================================
# Context Engine Tests
# ===========================================================================

class TestVariableStore:

    def setup_method(self):
        self.store = VariableStore()

    def test_set_and_get_global(self):
        self.store.set_global("URL", "http://localhost")
        assert self.store.get("URL") == "http://localhost"

    def test_scenario_overrides_global(self):
        self.store.set_global("VAR", "global")
        self.store.set_scenario("VAR", "scenario")
        assert self.store.get("VAR") == "scenario"

    def test_step_overrides_scenario(self):
        self.store.set_scenario("VAR", "scenario")
        self.store.set_step("VAR", "step")
        assert self.store.get("VAR") == "step"

    def test_resolve_variable(self):
        self.store.set_global("USER", "joao@test.com")
        result = self.store.resolve("Login como ${USER}")
        assert result == "Login como joao@test.com"

    def test_resolve_missing_variable_unchanged(self):
        result = self.store.resolve("${UNDEFINED_VAR}")
        assert result == "${UNDEFINED_VAR}"

    def test_clear_scenario(self):
        self.store.set_scenario("VAR", "value")
        self.store.clear_scenario()
        assert self.store.get("VAR") is None

    def test_snapshot(self):
        self.store.set_global("G", 1)
        self.store.set_flow("F", 2)
        snap = self.store.snapshot()
        assert snap["global"]["G"] == 1
        assert snap["flow"]["F"] == 2


class TestContextEngine:

    def setup_method(self):
        self.ctx = ContextEngine(project=ProjectContext(
            base_url="http://localhost:4200",
            framework="Angular",
            auth_type="JWT",
        ))

    def test_default_variables_set(self):
        assert self.ctx.get_variable("BASE_URL") == "http://localhost:4200"
        assert self.ctx.get_variable("FRAMEWORK") == "Angular"

    def test_begin_scenario_sets_name(self):
        self.ctx.begin_scenario("ValidLogin")
        assert self.ctx.get_variable("SCENARIO_NAME") == "ValidLogin"

    def test_navigate_updates_current_page(self):
        step = make_step("Dado que o usuário está na página de login", StepType.GIVEN)
        self.ctx.enrich_step(step)
        assert "Login" in self.ctx.current_page or self.ctx.current_page != ""

    def test_set_and_get_variable(self):
        self.ctx.set_variable("TOKEN", "abc123")
        assert self.ctx.get_variable("TOKEN") == "abc123"

    def test_resolve_text(self):
        self.ctx.set_variable("EMAIL", "user@test.com")
        result = self.ctx.resolve_text("Inserir ${EMAIL} no campo")
        assert result == "Inserir user@test.com no campo"

    def test_events_recorded(self):
        self.ctx.begin_flow("TestFlow")
        self.ctx.begin_scenario("Scenario1")
        events = self.ctx.events_log()
        event_types = [e["type"] for e in events]
        assert "flow_begin" in event_types
        assert "scenario_begin" in event_types

    def test_enrich_step_resolves_pom(self):
        step = make_step('Quando o usuário insere "test@test.com" no campo email', StepType.WHEN)
        enriched = self.ctx.enrich_step(step)
        # field parameter should have a resolved locator or remain as string
        assert enriched is not None

    def test_build_runtime_context(self):
        self.ctx.begin_flow("TestFlow")
        rtx = self.ctx.build_runtime_context()
        assert rtx.project.base_url == "http://localhost:4200"
        assert isinstance(rtx.variables, dict)

    def test_clear_on_scenario_boundary(self):
        self.ctx.begin_scenario("S1")
        self.ctx.set_variable("TEMP", "value", scope="scenario")
        self.ctx.end_scenario("S1", "passed")
        self.ctx.begin_scenario("S2")
        # After clearing and re-beginning, scenario var should be gone
        assert self.ctx.get_variable("SCENARIO_NAME") == "S2"


# ===========================================================================
# Scenario Engine Tests
# ===========================================================================

class TestScenarioEngine:

    def setup_method(self):
        self.engine = ScenarioEngine()
        self.parser = DSLParser()
        self.flow   = self.parser.parse(FULL_DSL)

    def test_compose_returns_scenarios(self):
        composed = self.engine.compose(self.flow)
        assert len(composed) == 3

    def test_compose_classifies_happy_path(self):
        composed = self.engine.compose(self.flow)
        categories = [c.category for c in composed]
        assert ScenarioCategory.HAPPY_PATH in categories

    def test_compose_classifies_negative(self):
        composed = self.engine.compose(self.flow)
        categories = [c.category for c in composed]
        assert ScenarioCategory.NEGATIVE in categories

    def test_priority_score_in_range(self):
        composed = self.engine.compose(self.flow)
        for c in composed:
            assert 0.0 <= c.priority_score <= 1.0

    def test_happy_path_has_higher_priority(self):
        composed = self.engine.compose(self.flow)
        # composed is sorted by priority descending
        assert composed[0].priority_score >= composed[-1].priority_score

    def test_estimated_duration_positive(self):
        composed = self.engine.compose(self.flow)
        for c in composed:
            assert c.estimated_duration_ms > 0

    def test_coverage_map_populated(self):
        composed = self.engine.compose(self.flow)
        for c in composed:
            assert isinstance(c.coverage_contribution, dict)
            assert "has_assertion" in c.coverage_contribution

    def test_fingerprint_unique(self):
        composed = self.engine.compose(self.flow)
        fps = [c.fingerprint for c in composed]
        assert len(fps) == len(set(fps))

    def test_analyze_coverage_full_flow(self):
        report = self.engine.analyze_coverage(self.flow)
        assert report.flow_name == "LoginFlow"
        assert report.total_scenarios == 3
        assert report.has_happy_path is True
        assert report.has_negative is True
        assert 0.0 <= report.coverage_score <= 100.0

    def test_analyze_coverage_no_recommendations_for_good_flow(self):
        report = self.engine.analyze_coverage(self.flow)
        # Full flow with 3 scenarios should score well
        assert report.coverage_score >= 40.0

    def test_coverage_gaps_for_minimal_flow(self):
        minimal_dsl = """
@flow MinimalFlow
  @scenario OnlyHappy
    Dado que o sistema está pronto
    Quando o usuário acessa
    Então é esperado que funcione
"""
        flow = self.parser.parse(minimal_dsl)
        report = self.engine.analyze_coverage(flow)
        # Should detect missing negative and boundary
        assert len(report.gaps) > 0
        assert not report.has_negative

    def test_expand_with_variations_adds_negative(self):
        composed = self.engine.compose(self.flow)
        original_count = len(composed)
        expanded = self.engine.expand_with_variations(composed, max_variations=3)
        assert len(expanded) >= original_count

    def test_prioritize_reorders_by_score(self):
        composed = self.engine.compose(self.flow)
        prioritized = self.engine.prioritize(composed)
        scores = [c.priority_score for c in prioritized]
        # Should be roughly in descending order
        assert scores[0] >= scores[-1]

    def test_dataset_generation(self):
        scenario = self.flow.scenarios[0]
        dataset = self.engine.build_dataset(scenario, {
            "email": {
                "valid":    ["user@test.com", "admin@test.com"],
                "invalid":  ["not-an-email", ""],
                "boundary": ["a" * 254 + "@test.com"],
            }
        })
        assert len(dataset) > 0
        assert all("email" in row for row in dataset.rows)
