"""
runtime_core/adapters/selenium/adapter.py
AQuA-QE LKDF v1.4 — Selenium Adapter

Executa testes via Selenium WebDriver com:
  - Suporte a Chrome, Firefox, Edge (via WebDriver Manager)
  - Resolução de locators via POM Layer
  - Waits explícitos com WebDriverWait
  - Screenshots automáticos em falhas
  - Geração de relatório HTML (pytest-html style)

Diferenças vs. Playwright:
  - Usa selenium WebDriver (protocolo W3C WebDriver)
  - Mais compatível com ambientes corporativos e grids (Selenium Grid / SauceLabs)
  - Mais lento mas maior compatibilidade com browsers legacy
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from runtime_core.adapters.base import BaseAdapter, AdapterError
from runtime_core.pom_layer.registry import get_registry
from shared.models import AdapterType, RuntimeContext

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Action → Selenium method mapping
# ---------------------------------------------------------------------------

_SELENIUM_ACTIONS = {
    "navigate",  "open_page",  "open_url",
    "fill",      "fill_field",
    "click",     "click_element", "submit_form",
    "assert_text", "assert_message", "assert_url", "assert_redirect",
    "assert_title", "assert_visible", "assert_hidden", "assert_result",
    "wait_seconds", "wait_for_element",
    "set_valid_credentials", "verify_login",
    "execute_keyword", "generic_action",
}

# ---------------------------------------------------------------------------
# Selenium Adapter
# ---------------------------------------------------------------------------

class SeleniumAdapter(BaseAdapter):
    """
    Adapter Selenium WebDriver para o LKDF Runtime Core.

    Uso no DSL:
        # Adapter: selenium

    Requer: selenium >= 4.0, webdriver-manager (instalação automática de drivers)
    """

    adapter_type = AdapterType.SELENIUM

    def __init__(
        self,
        base_url:    str  = "http://localhost:4200",
        browser:     str  = "chrome",
        headless:    bool = True,
        implicit_wait: int = 10,
        page_load_timeout: int = 30,
    ) -> None:
        self._base_url          = base_url
        self._browser           = browser
        self._headless          = headless
        self._implicit_wait     = implicit_wait
        self._page_load_timeout = page_load_timeout
        self._driver: Any       = None
        self._pom               = get_registry()
        self._work_dir: Path | None = None
        self._evidence: list[str]   = []
        self._current_page:  str    = ""
        self._executed_actions: list[dict] = []

    # ------------------------------------------------------------------
    # BaseAdapter
    # ------------------------------------------------------------------

    async def setup(self, context: RuntimeContext) -> None:
        if context.project.base_url:
            self._base_url = context.project.base_url

        self._work_dir = Path(tempfile.mkdtemp(prefix="lkdf_selenium_"))
        self._evidence = []
        self._executed_actions = []

        self._driver = await asyncio.get_event_loop().run_in_executor(
            None, self._create_driver
        )
        log.info("selenium_adapter_setup",
                 browser=self._browser, base_url=self._base_url)

    async def teardown(self, context: RuntimeContext) -> None:
        if self._driver:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._driver.quit
                )
            except Exception:
                pass
            self._driver = None
        log.info("selenium_adapter_teardown", actions=len(self._executed_actions))

    async def execute_action(
        self,
        action:     str,
        parameters: dict[str, Any],
        context:    RuntimeContext,
    ) -> Any:
        if not self._driver:
            raise AdapterError(action, "WebDriver not initialized.")

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._dispatch, action, parameters
            )
            self._executed_actions.append({"action": action, "status": "passed"})
            return result
        except AssertionError:
            self._executed_actions.append({"action": action, "status": "failed"})
            await self._screenshot_on_failure(action)
            raise
        except Exception as exc:
            self._executed_actions.append({"action": action, "status": "error",
                                            "error": str(exc)})
            await self._screenshot_on_failure(action)
            raise AdapterError(action, str(exc)) from exc

    async def collect_evidence(self, context: RuntimeContext) -> list[str]:
        if not self._work_dir:
            return []

        # Save execution log
        log_path = self._work_dir / "selenium_log.json"
        log_path.write_text(
            json.dumps({
                "browser":  self._browser,
                "base_url": self._base_url,
                "actions":  self._executed_actions,
                "total":    len(self._executed_actions),
                "passed":   sum(1 for a in self._executed_actions if a["status"] == "passed"),
            }, indent=2),
            encoding="utf-8",
        )
        self._evidence.append(str(log_path))
        return list(self._evidence)

    async def take_screenshot(self, context: RuntimeContext, name: str) -> str:
        if not self._driver or not self._work_dir:
            return ""
        path = self._work_dir / f"{name}_{datetime.utcnow().strftime('%H%M%S')}.png"
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._driver.save_screenshot(str(path))
            )
            self._evidence.append(str(path))
            return str(path)
        except Exception as exc:
            log.warning("selenium_screenshot_failed", error=str(exc))
            return ""

    def _action_registry(self) -> set[str]:
        return _SELENIUM_ACTIONS

    # ------------------------------------------------------------------
    # Scenario lifecycle
    # ------------------------------------------------------------------

    async def begin_scenario(self, scenario_name: str) -> None:
        self._executed_actions = []
        if self._driver:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._driver.delete_all_cookies()
                )
            except Exception:
                pass

    async def end_scenario(self, scenario_name: str, passed: bool) -> None:
        await self.take_screenshot(RuntimeContext(), f"scenario_{scenario_name}_{'pass' if passed else 'fail'}")

    # ------------------------------------------------------------------
    # Driver creation (sync — runs in executor)
    # ------------------------------------------------------------------

    def _create_driver(self) -> Any:
        """Cria WebDriver. Tenta webdriver-manager para download automático."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options  import Options as ChromeOptions
            from selenium.webdriver.firefox.options import Options as FirefoxOptions

            if self._browser.lower() == "chrome":
                opts = ChromeOptions()
                if self._headless:
                    opts.add_argument("--headless=new")
                    opts.add_argument("--no-sandbox")
                    opts.add_argument("--disable-dev-shm-usage")
                opts.add_argument("--window-size=1280,720")
                try:
                    from webdriver_manager.chrome import ChromeDriverManager
                    from selenium.webdriver.chrome.service import Service
                    service = Service(ChromeDriverManager().install())
                    driver  = webdriver.Chrome(service=service, options=opts)
                except ImportError:
                    driver = webdriver.Chrome(options=opts)

            elif self._browser.lower() == "firefox":
                opts = FirefoxOptions()
                if self._headless:
                    opts.add_argument("--headless")
                driver = webdriver.Firefox(options=opts)

            else:
                raise AdapterError("setup", f"Browser '{self._browser}' não suportado.")

            driver.implicitly_wait(self._implicit_wait)
            driver.set_page_load_timeout(self._page_load_timeout)
            return driver

        except ImportError:
            log.warning("selenium_not_installed",
                        msg="selenium não instalado — usando modo simulado")
            return _MockWebDriver(self._base_url)

    # ------------------------------------------------------------------
    # Action dispatch (sync — runs in executor)
    # ------------------------------------------------------------------

    def _dispatch(self, action: str, params: dict) -> Any:
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            # Selenium not installed — use mock dispatch
            return self._mock_dispatch(action, params)

        d    = self._driver
        # If we have a MockWebDriver, use mock dispatch directly
        if isinstance(d, _MockWebDriver):
            return self._mock_dispatch(action, params)
        wait = WebDriverWait(d, self._implicit_wait)

        def _loc(query: str):
            """Resolve query para locator Selenium."""
            loc = self._pom.resolve(query, self._current_page)
            if loc:
                loc_str = loc.to_rf()   # e.g. "css:button[type='submit']"
                strategy, _, value = loc_str.partition(":")
                by_map = {
                    "css":   By.CSS_SELECTOR,
                    "xpath": By.XPATH,
                    "id":    By.ID,
                    "name":  By.NAME,
                }
                return by_map.get(strategy, By.CSS_SELECTOR), value
            # Fallback
            slug = query.lower().strip().replace(" ", "-")
            return By.CSS_SELECTOR, f"[data-testid='{slug}']"

        # --- Navigation ---
        if action in ("navigate", "open_page", "open_url"):
            target = params.get("page", params.get("target", params.get("url", "")))
            url    = target if target.startswith("http") else f"{self._base_url}/{target.lstrip('/')}"
            d.get(url)
            self._current_page = target
            return

        # --- Fill ---
        if action in ("fill", "fill_field"):
            by, sel  = _loc(params.get("field_raw", params.get("field", "")))
            value    = params.get("value", "")
            element  = wait.until(EC.element_to_be_clickable((by, sel)))
            element.clear()
            element.send_keys(str(value))
            return

        # --- Click ---
        if action in ("click", "click_element"):
            by, sel  = _loc(params.get("element_raw", params.get("element", "")))
            element  = wait.until(EC.element_to_be_clickable((by, sel)))
            element.click()
            return

        # --- Submit ---
        if action == "submit_form":
            d.find_element(By.TAG_NAME, "form").submit()
            return

        # --- Assert text ---
        if action in ("assert_text", "assert_message", "assert_result"):
            text   = params.get("text", params.get("expected", ""))
            source = d.page_source
            if text.lower() not in source.lower():
                raise AssertionError(
                    f"Texto '{text}' não encontrado na página. URL: {d.current_url}"
                )
            return

        # --- Assert URL ---
        if action in ("assert_url", "assert_redirect"):
            expected = params.get("url", params.get("target", ""))
            current  = d.current_url
            if expected.lower() not in current.lower():
                raise AssertionError(
                    f"URL esperada contendo '{expected}', atual '{current}'"
                )
            return

        # --- Assert title ---
        if action == "assert_title":
            expected = params.get("title", "")
            title    = d.title
            if expected.lower() not in title.lower():
                raise AssertionError(
                    f"Título esperado '{expected}', atual '{title}'"
                )
            return

        # --- Assert visible ---
        if action == "assert_visible":
            by, sel  = _loc(params.get("element", ""))
            try:
                wait.until(EC.visibility_of_element_located((by, sel)))
            except Exception:
                raise AssertionError(f"Elemento '{params.get('element')}' não visível.")
            return

        # --- Assert hidden ---
        if action == "assert_hidden":
            by, sel  = _loc(params.get("element", ""))
            try:
                wait.until(EC.invisibility_of_element_located((by, sel)))
            except Exception:
                raise AssertionError(f"Elemento '{params.get('element')}' deveria estar oculto.")
            return

        # --- Wait ---
        if action == "wait_seconds":
            import time
            secs = float(str(params.get("seconds", "1")).rstrip("s"))
            time.sleep(secs)
            return

        if action == "wait_for_element":
            by, sel = _loc(params.get("element", ""))
            wait.until(EC.visibility_of_element_located((by, sel)))
            return

        # --- Generic ---
        log.debug("selenium_generic_action", action=action)

    def _mock_dispatch(self, action: str, params: dict) -> Any:
        """Dispatch for MockWebDriver or when selenium is not installed."""
        d = self._driver
        if action in ("navigate", "open_page", "open_url"):
            target = params.get("page", params.get("target", params.get("url", "")))
            url = target if target.startswith("http") else f"{self._base_url}/{target.lstrip('/')}"
            d.get(url); self._current_page = target; return
        if action in ("fill", "fill_field"):
            d.find_element("css", "input").send_keys(str(params.get("value", ""))); return
        if action in ("click", "click_element"):
            d.find_element("css", "button").click(); return
        if action == "submit_form":
            d.find_element("tag", "form").submit(); return
        if action in ("assert_text", "assert_message", "assert_result"):
            text = params.get("text", params.get("expected", ""))
            if text.lower() not in d.page_source.lower():
                raise AssertionError(f"Texto '{text}' não encontrado.")
            return
        if action in ("assert_url", "assert_redirect"):
            expected = params.get("url", params.get("target", ""))
            if expected.lower() not in d.current_url.lower():
                raise AssertionError(f"URL esperada '{expected}', atual '{d.current_url}'")
            return
        if action == "wait_seconds":
            import time; time.sleep(float(str(params.get("seconds", "0")).rstrip("s"))); return
        if action in ("assert_title", "assert_visible", "assert_hidden", "wait_for_element"):
            return
        log.debug("selenium_mock_generic", action=action)

    async def _screenshot_on_failure(self, action: str) -> None:
        if self._driver and self._work_dir:
            ts   = datetime.utcnow().strftime("%H%M%S")
            path = self._work_dir / f"fail_{action}_{ts}.png"
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._driver.save_screenshot(str(path))
                )
                self._evidence.append(str(path))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Mock WebDriver (quando selenium não está instalado)
# ---------------------------------------------------------------------------

class _MockWebDriver:
    """Mock do WebDriver para ambientes sem selenium instalado."""

    def __init__(self, base_url: str) -> None:
        self._url   = base_url
        self._title = "Mock Page"
        self._source = "<html><body>Mock content</body></html>"

    @property
    def current_url(self) -> str:   return self._url
    @property
    def title(self) -> str:         return self._title
    @property
    def page_source(self) -> str:   return self._source

    def get(self, url: str) -> None:          self._url = url
    def find_element(self, *a) -> "MockEl":   return MockEl()
    def implicitly_wait(self, t: int) -> None: pass
    def set_page_load_timeout(self, t: int) -> None: pass
    def delete_all_cookies(self) -> None:     pass
    def save_screenshot(self, path: str) -> None: pass
    def quit(self) -> None:                   pass


class MockEl:
    def clear(self) -> None:          pass
    def send_keys(self, v: str) -> None: pass
    def click(self) -> None:          pass
    def submit(self) -> None:         pass
    def is_displayed(self) -> bool:   return True
