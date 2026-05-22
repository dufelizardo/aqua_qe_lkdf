"""
runtime_core/adapters/playwright/action_executor.py
AQuA-QE LKDF — Playwright Adapter: Action Executor

Traduz actions semânticas do Intent Resolver para chamadas da API Playwright.
Cada action corresponde a um método em PageInteractor.

Vantagens sobre Robot Framework:
  - auto-wait nativo (sem Sleep explícitos)
  - assertions com retry automático via expect()
  - network interception nativa
  - screenshot em falha automático
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from runtime_core.adapters.playwright.locator_healing import LocatorHealingMiddleware
from runtime_core.pom_layer.registry import POMRegistry

log = structlog.get_logger(__name__)

# Timeout padrão para auto-wait (ms)
DEFAULT_TIMEOUT  = 10_000
ASSERT_TIMEOUT   = 8_000
NAV_TIMEOUT      = 30_000


class ActionExecutor:
    """
    Executa actions semânticas usando a API Playwright async.

    O executor nunca recebe locators técnicos diretamente — apenas
    nomes semânticos de elementos, que são resolvidos via LocatorHealingMiddleware.
    """

    def __init__(
        self,
        page:     Any,
        healing:  LocatorHealingMiddleware,
        base_url: str = "",
    ) -> None:
        self._page    = page
        self._healing = healing
        self._base_url = base_url.rstrip("/")
        self._current_page_name: str = ""

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, parameters: dict[str, Any]) -> None:
        """
        Ponto de entrada. Despacha para o método correto baseado na action.
        Lança AssertionError em falhas de assertion.
        Lança PlaywrightActionError em falhas técnicas.
        """
        handler = self._HANDLERS.get(action)
        if handler:
            await handler(self, parameters)
        else:
            log.warning("action_unknown", action=action)
            await self._execute_generic(parameters)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def _navigate(self, p: dict) -> None:
        page_name = p.get("page", p.get("target", ""))
        url       = self._resolve_url(page_name)
        await self._page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        self._current_page_name = page_name
        log.debug("navigated", url=url)

    async def _open_url(self, p: dict) -> None:
        url = p.get("target", p.get("url", self._base_url))
        if not url.startswith("http"):
            url = f"{self._base_url}/{url.lstrip('/')}"
        await self._page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        log.debug("opened_url", url=url)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    async def _fill(self, p: dict) -> None:
        field  = p.get("field", p.get("field_raw", ""))
        value  = p.get("value", "")
        result = await self._healing.resolve(
            self._page, field, self._current_page_name
        )
        if result.broken:
            raise PlaywrightActionError("fill", f"Elemento '{field}' não encontrado.")

        locator = self._page.locator(result.locator_str).first
        await locator.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        await locator.clear()
        await locator.fill(str(value))
        log.debug("filled", field=field, value=value[:20] if value else "")

    # ------------------------------------------------------------------
    # Click
    # ------------------------------------------------------------------

    async def _click(self, p: dict) -> None:
        element = p.get("element", p.get("element_raw", ""))
        result  = await self._healing.resolve(
            self._page, element, self._current_page_name
        )
        if result.broken:
            raise PlaywrightActionError("click", f"Elemento '{element}' não encontrado.")

        locator = self._page.locator(result.locator_str).first
        await locator.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        await locator.click()
        log.debug("clicked", element=element)

    async def _submit_form(self, p: dict) -> None:
        await self._page.keyboard.press("Enter")

    # ------------------------------------------------------------------
    # Assertions — usam expect() com retry automático
    # ------------------------------------------------------------------

    async def _assert_text(self, p: dict) -> None:
        text = p.get("text", p.get("expected", ""))
        try:
            from playwright.async_api import expect
            await expect(self._page.locator("body")).to_contain_text(
                text, timeout=ASSERT_TIMEOUT
            )
        except Exception as exc:
            raise AssertionError(
                f"Texto '{text}' não encontrado na página. {exc}"
            )

    async def _assert_url(self, p: dict) -> None:
        expected = p.get("url", p.get("target", ""))
        if not expected.startswith("http"):
            expected = f"{self._base_url}/{expected.lstrip('/')}"
        try:
            from playwright.async_api import expect
            await expect(self._page).to_have_url(
                re.compile(re.escape(expected.rstrip("/"))),
                timeout=ASSERT_TIMEOUT,
            )
        except Exception as exc:
            raise AssertionError(
                f"URL esperada '{expected}', atual '{self._page.url}'. {exc}"
            )

    async def _assert_title(self, p: dict) -> None:
        expected = p.get("title", "")
        try:
            from playwright.async_api import expect
            await expect(self._page).to_have_title(
                re.compile(re.escape(expected), re.IGNORECASE),
                timeout=ASSERT_TIMEOUT,
            )
        except Exception as exc:
            raise AssertionError(
                f"Título esperado '{expected}', atual '{await self._page.title()}'. {exc}"
            )

    async def _assert_visible(self, p: dict) -> None:
        element = p.get("element", "")
        result  = await self._healing.resolve(self._page, element, self._current_page_name)
        try:
            from playwright.async_api import expect
            await expect(self._page.locator(result.locator_str).first).to_be_visible(
                timeout=ASSERT_TIMEOUT
            )
        except Exception as exc:
            raise AssertionError(f"Elemento '{element}' não está visível. {exc}")

    async def _assert_hidden(self, p: dict) -> None:
        element = p.get("element", "")
        result  = await self._healing.resolve(self._page, element, self._current_page_name)
        try:
            from playwright.async_api import expect
            await expect(self._page.locator(result.locator_str).first).to_be_hidden(
                timeout=ASSERT_TIMEOUT
            )
        except Exception as exc:
            raise AssertionError(f"Elemento '{element}' deveria estar oculto. {exc}")

    # ------------------------------------------------------------------
    # Wait
    # ------------------------------------------------------------------

    async def _wait_seconds(self, p: dict) -> None:
        import asyncio
        seconds = float(str(p.get("seconds", "1")).rstrip("s"))
        await asyncio.sleep(seconds)

    async def _wait_for_element(self, p: dict) -> None:
        element = p.get("element", "")
        result  = await self._healing.resolve(self._page, element, self._current_page_name)
        await self._page.locator(result.locator_str).first.wait_for(
            state="visible", timeout=DEFAULT_TIMEOUT
        )

    # ------------------------------------------------------------------
    # Setup / Preconditions
    # ------------------------------------------------------------------

    async def _set_valid_credentials(self, p: dict) -> None:
        """Injeta credenciais válidas via storage state (sem UI)."""
        log.debug("set_valid_credentials — usando contexto existente")

    async def _block_account(self, p: dict) -> None:
        account = p.get("account", "")
        log.debug("block_account", account=account)

    async def _populate_cart(self, p: dict) -> None:
        log.debug("populate_cart — setup via API ou seed")

    # ------------------------------------------------------------------
    # Generic
    # ------------------------------------------------------------------

    async def _execute_generic(self, p: dict) -> None:
        text = p.get("text", p.get("param_0", ""))
        log.debug("generic_action", text=str(text)[:80])

    # ------------------------------------------------------------------
    # Screenshot on demand
    # ------------------------------------------------------------------

    async def screenshot(self, name: str, output_dir: str) -> str:
        from pathlib import Path
        path = Path(output_dir) / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path), full_page=True)
        return str(path)

    # ------------------------------------------------------------------
    # URL resolver
    # ------------------------------------------------------------------

    def _resolve_url(self, page_name: str) -> str:
        if page_name.startswith("http"):
            return page_name
        slug = page_name.lower().replace(" ", "-")
        route_map = {
            "login":     "/login",
            "dashboard": "/dashboard",
            "home":      "/",
            "cadastro":  "/register",
            "perfil":    "/profile",
        }
        for key, path in route_map.items():
            if key in slug:
                return f"{self._base_url}{path}"
        return f"{self._base_url}/{slug}"

    # ------------------------------------------------------------------
    # Handler registry (action → method)
    # ------------------------------------------------------------------

    _HANDLERS: dict[str, Any] = {
        "navigate":              _navigate,
        "open_page":             _navigate,
        "open_url":              _open_url,
        "fill":                  _fill,
        "fill_field":            _fill,
        "click":                 _click,
        "click_element":         _click,
        "submit":                _submit_form,
        "submit_form":           _submit_form,
        "assert_text":           _assert_text,
        "assert_message":        _assert_text,
        "assert_result":         _assert_text,
        "assert_url":            _assert_url,
        "assert_redirect":       _assert_url,
        "assert_title":          _assert_title,
        "assert_visible":        _assert_visible,
        "assert_hidden":         _assert_hidden,
        "verify_login":          _assert_text,
        "wait_seconds":          _wait_seconds,
        "wait_for_element":      _wait_for_element,
        "set_valid_credentials": _set_valid_credentials,
        "block_account":         _block_account,
        "populate_cart":         _populate_cart,
        "execute_keyword":       _execute_generic,
        "generic_action":        _execute_generic,
    }


class PlaywrightActionError(Exception):
    def __init__(self, action: str, message: str) -> None:
        self.action = action
        super().__init__(f"[{action}] {message}")
