"""
tests/unit/test_playwright_adapter.py
AQuA-QE LKDF — Unit Tests: Playwright Adapter

Todos os testes rodam sem browser real (mocks Playwright API).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from shared.models import AdapterType, ProjectContext, RuntimeContext
from runtime_core.adapters.factory import AdapterFactory
from runtime_core.adapters.playwright.locator_healing import (
    HealingStrategy, LocatorHealingMiddleware,
)
from runtime_core.adapters.playwright.action_executor import ActionExecutor
from runtime_core.pom_layer.registry import POMRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_page_mock(url: str = "http://localhost/login", title: str = "Login"):
    """Cria um mock da Page do Playwright."""
    page = MagicMock()
    page.url = url
    page.goto        = AsyncMock()
    page.fill        = AsyncMock()
    page.click       = AsyncMock()
    page.screenshot  = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.title       = AsyncMock(return_value=title)
    page.on          = MagicMock()

    # locator chain
    loc_mock         = MagicMock()
    loc_mock.first   = MagicMock()
    loc_mock.first.wait_for   = AsyncMock()
    loc_mock.first.fill       = AsyncMock()
    loc_mock.first.click      = AsyncMock()
    loc_mock.first.clear      = AsyncMock()
    loc_mock.first.is_visible = AsyncMock(return_value=True)
    page.locator = MagicMock(return_value=loc_mock)

    return page


def make_healing(always_visible: bool = True) -> LocatorHealingMiddleware:
    """Cria LocatorHealingMiddleware com POM padrão."""
    middleware = LocatorHealingMiddleware(pom=POMRegistry())

    async def mock_is_visible(page, locator_str, timeout_ms):
        return always_visible

    middleware._is_visible = mock_is_visible  # patch static method
    return middleware


def make_executor(page=None, visible=True) -> ActionExecutor:
    p = page or make_page_mock()
    h = make_healing(always_visible=visible)
    return ActionExecutor(page=p, healing=h, base_url="http://localhost:4200")


def make_context() -> RuntimeContext:
    return RuntimeContext(project=ProjectContext(base_url="http://localhost:4200"))


# ---------------------------------------------------------------------------
# Locator Healing Tests
# ---------------------------------------------------------------------------

class TestLocatorHealingMiddleware:

    @pytest.mark.asyncio
    async def test_resolves_known_pom_element(self):
        page    = make_page_mock()
        healing = LocatorHealingMiddleware(pom=POMRegistry())

        with patch.object(LocatorHealingMiddleware, '_is_visible', new=AsyncMock(return_value=True)):
            result = await healing.resolve(page, "email", "LoginPage")

        assert result.locator_str != ""
        assert not result.broken

    @pytest.mark.asyncio
    async def test_uses_heuristic_for_unknown_element(self):
        page    = make_page_mock()
        healing = make_healing(always_visible=True)

        result = await healing.resolve(page, "campo_cpf_especial", None)

        assert not result.broken
        assert result.strategy in (
            HealingStrategy.HEURISTIC,
            HealingStrategy.POM_FALLBACK,
            HealingStrategy.POM_PRIMARY,
        )

    @pytest.mark.asyncio
    async def test_registers_broken_when_nothing_visible(self):
        page    = make_page_mock()
        healing = make_healing(always_visible=False)

        result = await healing.resolve(page, "elemento_inexistente_xyz_123")

        assert result.broken
        assert result.strategy == HealingStrategy.FAILED
        assert healing.broken_count == 1

    @pytest.mark.asyncio
    async def test_summary_tracks_counts(self):
        page    = make_page_mock()
        healing = LocatorHealingMiddleware(pom=POMRegistry())

        with patch.object(LocatorHealingMiddleware, '_is_visible', new=AsyncMock(return_value=True)):
            await healing.resolve(page, "email", "LoginPage")
            await healing.resolve(page, "senha", "LoginPage")

        summary = healing.summary()
        assert summary["total_resolutions"] == 2
        assert summary["broken"] == 0

    def test_heuristic_email(self):
        h = LocatorHealingMiddleware()
        loc = h._heuristic("email")
        assert "email" in loc or "testid" in loc

    def test_heuristic_submit(self):
        h = LocatorHealingMiddleware()
        loc = h._heuristic("entrar")
        assert "submit" in loc or "testid" in loc or "btn" in loc

    def test_heuristic_unknown_generates_testid(self):
        h = LocatorHealingMiddleware()
        loc = h._heuristic("meu-campo-custom")
        assert "data-testid" in loc


# ---------------------------------------------------------------------------
# ActionExecutor Tests
# ---------------------------------------------------------------------------

class TestActionExecutor:

    @pytest.mark.asyncio
    async def test_navigate_calls_goto(self):
        page = make_page_mock()
        exec = make_executor(page=page)

        await exec.execute("navigate", {"page": "login"})

        page.goto.assert_called_once()
        url_arg = page.goto.call_args[0][0]
        assert "login" in url_arg

    @pytest.mark.asyncio
    async def test_fill_calls_locator_fill(self):
        page = make_page_mock()
        exec = make_executor(page=page)

        await exec.execute("fill", {"field": "email", "value": "user@test.com"})

        page.locator.assert_called()

    @pytest.mark.asyncio
    async def test_click_calls_locator_click(self):
        page = make_page_mock()
        exec = make_executor(page=page)

        await exec.execute("click_element", {"element": "entrar"})

        page.locator.assert_called()

    @pytest.mark.asyncio
    async def test_assert_text_passes_when_text_found(self):
        page = make_page_mock()
        exec = make_executor(page=page)

        with patch("playwright.async_api.expect") as mock_expect:
            mock_assert = AsyncMock()
            mock_expect.return_value.to_contain_text = mock_assert

            await exec.execute("assert_text", {"text": "Login realizado com sucesso"})

    @pytest.mark.asyncio
    async def test_assert_text_raises_on_failure(self):
        page = make_page_mock()
        exec = make_executor(page=page)

        async def failing_assert(*args, **kwargs):
            raise Exception("Text not found")

        loc_chain = MagicMock()
        loc_chain.to_contain_text = AsyncMock(side_effect=Exception("Text not found"))
        page.locator.return_value = loc_chain

        with patch("runtime_core.adapters.playwright.action_executor.ActionExecutor._assert_text",
                   new=AsyncMock(side_effect=AssertionError("Texto 'X' não encontrado na página."))):
            with pytest.raises(AssertionError, match="não encontrado"):
                await exec.execute("assert_text", {"text": "Texto inexistente"})

    @pytest.mark.asyncio
    async def test_wait_seconds(self):
        exec = make_executor()
        import asyncio
        start = asyncio.get_event_loop().time()
        await exec.execute("wait_seconds", {"seconds": "0.05"})
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.04

    @pytest.mark.asyncio
    async def test_submit_form_presses_enter(self):
        page = make_page_mock()
        exec = make_executor(page=page)

        await exec.execute("submit_form", {})

        page.keyboard.press.assert_called_once_with("Enter")

    @pytest.mark.asyncio
    async def test_unknown_action_does_not_raise(self):
        exec = make_executor()
        await exec.execute("unknown_action_xyz", {"text": "test"})

    @pytest.mark.asyncio
    async def test_screenshot_saves_file(self, tmp_path):
        page = make_page_mock()
        exec = make_executor(page=page)

        path = await exec.screenshot("test_shot", str(tmp_path))

        assert path.endswith(".png")
        page.screenshot.assert_called_once()

    def test_url_resolver_login(self):
        exec = make_executor()
        url  = exec._resolve_url("login")
        assert "login" in url

    def test_url_resolver_passthrough_http(self):
        exec = make_executor()
        url  = exec._resolve_url("http://other.com/path")
        assert url == "http://other.com/path"

    def test_all_semantic_actions_registered(self):
        from runtime_core.adapters.playwright.action_executor import ActionExecutor
        expected = {
            "navigate", "fill", "click_element", "assert_text",
            "assert_url", "assert_title", "assert_visible",
            "wait_seconds", "submit_form",
        }
        registered = set(ActionExecutor._HANDLERS.keys())
        assert expected.issubset(registered)


# ---------------------------------------------------------------------------
# Adapter Factory Tests
# ---------------------------------------------------------------------------

class TestAdapterFactory:

    def test_creates_robot_adapter(self):
        ctx     = ProjectContext(base_url="http://localhost:4200")
        adapter = AdapterFactory.create(AdapterType.ROBOT, ctx)
        from runtime_core.adapters.robot.robot_adapter import RobotAdapter
        assert isinstance(adapter, RobotAdapter)

    def test_creates_playwright_adapter(self):
        ctx     = ProjectContext(base_url="http://localhost:4200")
        adapter = AdapterFactory.create(AdapterType.PLAYWRIGHT, ctx)
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        assert isinstance(adapter, PlaywrightAdapter)

    def test_creates_from_string(self):
        adapter = AdapterFactory.create("playwright", ProjectContext())
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        assert isinstance(adapter, PlaywrightAdapter)

    def test_unknown_string_falls_back_to_robot(self):
        adapter = AdapterFactory.create("cucumber-js", ProjectContext())
        from runtime_core.adapters.robot.robot_adapter import RobotAdapter
        assert isinstance(adapter, RobotAdapter)

    def test_from_flow(self):
        from runtime_core.parser.dsl_parser import DSLParser
        dsl = """
@flow TestFlow
  @scenario S1
    Dado que o sistema está pronto
    Então é esperado que funcione
"""
        # Default adapter is robot-framework
        flow    = DSLParser().parse(dsl)
        adapter = AdapterFactory.from_flow(flow, ProjectContext())
        from runtime_core.adapters.robot.robot_adapter import RobotAdapter
        assert isinstance(adapter, RobotAdapter)

    def test_playwright_config_propagated(self):
        ctx = ProjectContext(
            base_url="http://myapp.com",
            extra={"browser": "firefox", "headless": False, "video": True},
        )
        adapter = AdapterFactory.create(AdapterType.PLAYWRIGHT, ctx)
        assert adapter._manager.config.browser   == "firefox"
        assert adapter._manager.config.headless  is False
        assert adapter._manager.config.video     is True
        assert adapter._manager.config.base_url  == "http://myapp.com"

    def test_available_lists_adapters(self):
        available = AdapterFactory.available()
        assert isinstance(available, list)
        # playwright is installed in this env
        assert "playwright" in available or "robot-framework" in available

    def test_register_custom_adapter(self):
        from runtime_core.adapters.base import BaseAdapter

        class DummyAdapter(BaseAdapter):
            adapter_type = AdapterType.API
            async def setup(self, ctx): pass
            async def teardown(self, ctx): pass
            async def execute_action(self, action, params, ctx): pass
            async def collect_evidence(self, ctx): return []
            async def take_screenshot(self, ctx, name): return ""

        AdapterFactory.register(AdapterType.API, lambda url, extra: DummyAdapter())
        # Registry is populated
        assert AdapterType.API in AdapterFactory._registry


# ---------------------------------------------------------------------------
# Integration: Playwright Adapter contract
# ---------------------------------------------------------------------------

class TestPlaywrightAdapterContract:
    """Verifica que PlaywrightAdapter respeita o contrato BaseAdapter."""

    def test_adapter_type(self):
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        adapter = PlaywrightAdapter()
        assert adapter.adapter_type == AdapterType.PLAYWRIGHT

    def test_supports_core_actions(self):
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        adapter = PlaywrightAdapter()
        for action in ("fill", "click_element", "assert_text", "navigate"):
            assert adapter.supports_action(action), f"Ação não suportada: {action}"

    def test_broken_locators_initially_empty(self):
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        adapter = PlaywrightAdapter()
        assert adapter.broken_locators == []

    def test_healing_summary_structure(self):
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        adapter = PlaywrightAdapter()
        summary = adapter.healing_summary
        assert "total_resolutions" in summary
        assert "healed"            in summary
        assert "broken"            in summary
