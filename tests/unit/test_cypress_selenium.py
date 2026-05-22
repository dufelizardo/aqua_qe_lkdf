"""
tests/unit/test_cypress_selenium.py
AQuA-QE LKDF v1.4 — Unit Tests: Cypress Adapter + Selenium Adapter
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from runtime_core.adapters.cypress.adapter import CypressAdapter
from runtime_core.adapters.selenium.adapter import SeleniumAdapter, _MockWebDriver
from runtime_core.adapters.factory import AdapterFactory
from shared.models import AdapterType, ProjectContext, RuntimeContext


def make_ctx(base_url="http://localhost:4200") -> RuntimeContext:
    from shared.models import ProjectContext
    return RuntimeContext(project=ProjectContext(base_url=base_url))


# ===========================================================================
# Cypress Adapter
# ===========================================================================

class TestCypressAdapter:

    @pytest.mark.asyncio
    async def test_setup(self):
        adapter = CypressAdapter(base_url="http://localhost:3000")
        ctx = make_ctx()
        await adapter.setup(ctx)
        assert adapter._work_dir is not None

    @pytest.mark.asyncio
    async def test_execute_navigate(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        cmd = await adapter.execute_action("navigate", {"page": "login"}, make_ctx())
        assert "cy.visit" in cmd

    @pytest.mark.asyncio
    async def test_execute_fill(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        cmd = await adapter.execute_action("fill", {"field": "email", "value": "test@test.com"}, make_ctx())
        assert "cy.get" in cmd
        assert "type" in cmd

    @pytest.mark.asyncio
    async def test_execute_click(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        cmd = await adapter.execute_action("click_element", {"element": "entrar"}, make_ctx())
        assert "cy.get" in cmd
        assert "click" in cmd

    @pytest.mark.asyncio
    async def test_execute_assert_text(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        cmd = await adapter.execute_action("assert_text", {"text": "Login realizado"}, make_ctx())
        assert "cy.contains" in cmd

    @pytest.mark.asyncio
    async def test_execute_assert_url(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        cmd = await adapter.execute_action("assert_url", {"url": "/dashboard"}, make_ctx())
        assert "cy.url" in cmd

    @pytest.mark.asyncio
    async def test_execute_wait_seconds(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        cmd = await adapter.execute_action("wait_seconds", {"seconds": "2"}, make_ctx())
        assert "cy.wait" in cmd
        assert "2000" in cmd

    @pytest.mark.asyncio
    async def test_scenario_lifecycle(self):
        adapter = CypressAdapter()
        await adapter.setup(make_ctx())
        await adapter.begin_scenario("ValidLogin")
        await adapter.execute_action("navigate", {"page": "login"}, make_ctx())
        await adapter.execute_action("fill", {"field": "email", "value": "u@t.com"}, make_ctx())
        await adapter.end_scenario("ValidLogin", passed=True)
        assert len(adapter._it_blocks) == 1
        assert adapter._it_blocks[0]["name"] == "ValidLogin"
        assert len(adapter._it_blocks[0]["commands"]) == 2

    @pytest.mark.asyncio
    async def test_generate_spec_file(self, tmp_path):
        adapter = CypressAdapter(base_url="http://localhost:3000")
        adapter._work_dir = tmp_path
        await adapter.begin_scenario("TestScenario")
        await adapter.execute_action("navigate", {"page": "/"}, make_ctx())
        await adapter.end_scenario("TestScenario", True)

        spec = adapter._generate_spec()
        content = spec.read_text()
        assert "describe(" in content
        assert "it('TestScenario'" in content
        assert "cy.visit" in content

    @pytest.mark.asyncio
    async def test_generate_config(self, tmp_path):
        import json
        adapter = CypressAdapter(base_url="http://app.com")
        adapter._work_dir = tmp_path
        config_path = adapter._generate_config()
        config = json.loads(config_path.read_text())
        assert config["e2e"]["baseUrl"] == "http://app.com"

    @pytest.mark.asyncio
    async def test_collect_evidence(self, tmp_path):
        adapter = CypressAdapter()
        adapter._work_dir = tmp_path
        await adapter.begin_scenario("S1")
        await adapter.execute_action("navigate", {"page": "/"}, make_ctx())
        await adapter.end_scenario("S1", True)
        evidence = await adapter.collect_evidence(make_ctx())
        assert len(evidence) >= 2
        assert any(str(p).endswith(".ts") for p in evidence)

    def test_locator_resolution_email(self):
        sel = CypressAdapter._resolve_locator("email")
        assert "email" in sel or "testid" in sel

    def test_locator_resolution_generic(self):
        sel = CypressAdapter._resolve_locator("meu-campo-custom")
        assert "data-testid" in sel

    def test_locator_resolution_empty(self):
        sel = CypressAdapter._resolve_locator("")
        assert "[data-testid]" in sel

    def test_action_registry(self):
        adapter  = CypressAdapter()
        registry = adapter._action_registry()
        for action in ("navigate", "fill", "click_element", "assert_text", "assert_url"):
            assert action in registry

    def test_adapter_type(self):
        assert CypressAdapter.adapter_type == AdapterType.CYPRESS


# ===========================================================================
# Selenium Adapter (uses _MockWebDriver)
# ===========================================================================

class TestSeleniumAdapter:

    @pytest.mark.asyncio
    async def test_setup_with_mock(self):
        adapter = SeleniumAdapter(base_url="http://localhost:4200")
        ctx = make_ctx()
        await adapter.setup(ctx)
        assert adapter._driver is not None
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_navigate_action(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        await adapter.execute_action("navigate", {"page": "login"}, ctx)
        assert len(adapter._executed_actions) == 1
        assert adapter._executed_actions[0]["status"] == "passed"
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_fill_action(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        await adapter.execute_action("fill", {"field": "email", "field_raw": "email", "value": "test@test.com"}, ctx)
        assert adapter._executed_actions[0]["status"] == "passed"
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_click_action(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        await adapter.execute_action("click_element", {"element": "entrar", "element_raw": "entrar"}, ctx)
        assert adapter._executed_actions[0]["status"] == "passed"
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_assert_text_passes_with_mock(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        # MockWebDriver page_source contains "Mock content"
        await adapter.execute_action("assert_text", {"text": "Mock content"}, ctx)
        assert adapter._executed_actions[0]["status"] == "passed"
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_assert_text_fails_wrong_text(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        with pytest.raises(AssertionError):
            await adapter.execute_action("assert_text", {"text": "TEXTO_QUE_NAO_EXISTE_XYZ"}, ctx)
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_wait_seconds(self):
        import asyncio
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        t0 = asyncio.get_event_loop().time()
        await adapter.execute_action("wait_seconds", {"seconds": "0.05"}, ctx)
        elapsed = asyncio.get_event_loop().time() - t0
        assert elapsed >= 0.04
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_scenario_lifecycle(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        await adapter.begin_scenario("ValidLogin")
        await adapter.execute_action("navigate", {"page": "login"}, ctx)
        await adapter.execute_action("assert_text", {"text": "Mock"}, ctx)
        await adapter.end_scenario("ValidLogin", passed=True)
        assert len(adapter._executed_actions) >= 2
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_collect_evidence_saves_log(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        await adapter.execute_action("navigate", {"page": "/"}, ctx)
        evidence = await adapter.collect_evidence(ctx)
        assert len(evidence) >= 1
        assert any("selenium_log.json" in p for p in evidence)
        await adapter.teardown(ctx)

    @pytest.mark.asyncio
    async def test_multiple_actions_tracked(self):
        adapter = SeleniumAdapter()
        ctx = make_ctx()
        await adapter.setup(ctx)
        for action in ["navigate", "navigate", "navigate"]:
            await adapter.execute_action(action, {"page": "/"}, ctx)
        assert len(adapter._executed_actions) == 3
        await adapter.teardown(ctx)

    def test_adapter_type(self):
        assert SeleniumAdapter.adapter_type == AdapterType.SELENIUM

    def test_action_registry(self):
        adapter = SeleniumAdapter()
        registry = adapter._action_registry()
        for action in ("navigate", "fill", "click_element", "assert_text"):
            assert action in registry


# ===========================================================================
# Mock WebDriver
# ===========================================================================

class TestMockWebDriver:

    def test_get_updates_url(self):
        d = _MockWebDriver("http://base.com")
        d.get("http://base.com/login")
        assert d.current_url == "http://base.com/login"

    def test_page_source(self):
        d = _MockWebDriver("http://base.com")
        assert "Mock" in d.page_source

    def test_find_element(self):
        from runtime_core.adapters.selenium.adapter import MockEl
        d = _MockWebDriver("http://base.com")
        el = d.find_element("css", "button")
        assert isinstance(el, MockEl)

    def test_title(self):
        d = _MockWebDriver("http://base.com")
        assert d.title == "Mock Page"


# ===========================================================================
# Factory integration
# ===========================================================================

class TestFactoryCypressSelenium:

    def test_creates_cypress_adapter(self):
        ctx = ProjectContext(base_url="http://app.com")
        adapter = AdapterFactory.create(AdapterType.CYPRESS, ctx)
        assert isinstance(adapter, CypressAdapter)

    def test_creates_selenium_adapter(self):
        ctx = ProjectContext(base_url="http://app.com")
        adapter = AdapterFactory.create(AdapterType.SELENIUM, ctx)
        assert isinstance(adapter, SeleniumAdapter)

    def test_creates_from_string_cypress(self):
        adapter = AdapterFactory.create("cypress", ProjectContext())
        assert isinstance(adapter, CypressAdapter)

    def test_creates_from_string_selenium(self):
        adapter = AdapterFactory.create("selenium", ProjectContext())
        assert isinstance(adapter, SeleniumAdapter)

    def test_cypress_config_propagated(self):
        ctx = ProjectContext(
            base_url="http://myapp.com",
            extra={"browser": "firefox", "headless": False},
        )
        adapter = AdapterFactory.create(AdapterType.CYPRESS, ctx)
        assert adapter._base_url == "http://myapp.com"
        assert adapter._browser  == "firefox"
        assert adapter._headless is False

    def test_selenium_config_propagated(self):
        ctx = ProjectContext(
            base_url="http://myapp.com",
            extra={"browser": "firefox", "headless": True},
        )
        adapter = AdapterFactory.create(AdapterType.SELENIUM, ctx)
        assert adapter._base_url  == "http://myapp.com"
        assert adapter._browser   == "firefox"
        assert adapter._headless  is True
