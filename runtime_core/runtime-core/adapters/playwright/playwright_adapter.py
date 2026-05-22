"""
runtime_core/adapters/playwright/playwright_adapter.py
AQuA-QE LKDF — Playwright Adapter

Implementação completa de BaseAdapter para Playwright.
Substitui o Robot Framework Adapter mantendo 100% do contrato.

Diferenças chave vs. Robot Adapter:
  - Execução in-process (sem subprocess)
  - auto-wait nativo (sem Sleep nos steps)
  - BrowserContext isolado por scenario (cookies, storage limpos)
  - Playwright Trace Viewer como artefato de evidência
  - LocatorHealingMiddleware integrado (base para Repair Agent Fase 4)
  - Suporte a Chromium, Firefox e WebKit
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from shared.models import AdapterType, RuntimeContext
from runtime_core.adapters.base import BaseAdapter, AdapterError
from runtime_core.adapters.playwright.browser_manager import BrowserConfig, BrowserManager
from runtime_core.adapters.playwright.action_executor import ActionExecutor, PlaywrightActionError
from runtime_core.adapters.playwright.locator_healing import LocatorHealingMiddleware
from runtime_core.pom_layer.registry import get_registry

log = structlog.get_logger(__name__)


class PlaywrightAdapter(BaseAdapter):
    """
    Adapter Playwright para o LKDF Runtime Core.

    Uso no DSL:
        # Adapter: playwright

    Configuração via ProjectContext:
        base_url  → URL base da aplicação
        extra:
          browser   → chromium | firefox | webkit  (default: chromium)
          headless  → true | false                 (default: true)
          video     → true | false                 (default: false)
          trace     → true | false                 (default: true)
          slow_mo   → int ms                       (default: 0)
    """

    adapter_type = AdapterType.PLAYWRIGHT

    def __init__(
        self,
        base_url:  str  = "http://localhost:4200",
        browser:   str  = "chromium",
        headless:  bool = True,
        video:     bool = False,
        trace:     bool = True,
        slow_mo:   int  = 0,
    ) -> None:
        config = BrowserConfig(
            browser=browser,
            headless=headless,
            slow_mo=slow_mo,
            base_url=base_url,
            video=video,
            trace=trace,
        )
        self._manager  = BrowserManager(config)
        self._healing  = LocatorHealingMiddleware(pom=get_registry())
        self._executor: ActionExecutor | None = None
        self._work_dir: Path = Path(tempfile.mkdtemp(prefix="lkdf_pw_"))
        self._evidence: list[str] = []
        self._current_scenario: str = ""

    # ------------------------------------------------------------------
    # BaseAdapter contract
    # ------------------------------------------------------------------

    async def setup(self, context: RuntimeContext) -> None:
        """
        Lança o browser. Chamado uma vez no início do Flow.
        O BrowserContext por scenario é criado em _begin_scenario().
        """
        # Override base_url from context if provided
        if context.project.base_url:
            self._manager.config.base_url = context.project.base_url

        # Apply extra config from ProjectContext
        extra = context.project.extra or {}
        if "browser"  in extra:
            self._manager.config.browser  = extra["browser"]
        if "headless" in extra:
            self._manager.config.headless = extra["headless"]
        if "video"    in extra:
            self._manager.config.video    = extra["video"]
        if "slow_mo"  in extra:
            self._manager.config.slow_mo  = int(extra["slow_mo"])

        await self._manager.start()
        log.info(
            "playwright_adapter_setup",
            base_url=self._manager.config.base_url,
            browser=self._manager.config.browser,
        )

    async def teardown(self, context: RuntimeContext) -> None:
        """Para o browser. Chamado ao fim do Flow."""
        await self._manager.stop()
        log.info("playwright_adapter_teardown", evidence=len(self._evidence))

    async def execute_action(
        self,
        action:     str,
        parameters: dict[str, Any],
        context:    RuntimeContext,
    ) -> Any:
        """
        Executa uma action semântica.
        O ActionExecutor traduz para Playwright API.
        Lança AssertionError em falhas de assertion.
        Lança AdapterError em falhas técnicas.
        """
        if not self._executor:
            raise AdapterError(action, "Nenhum scenario ativo. execute_action chamado fora de contexto.")

        try:
            await self._executor.execute(action, parameters)
        except AssertionError:
            # Captura screenshot em falha de assertion
            ts  = datetime.utcnow().strftime("%H%M%S")
            ss  = await self._executor.screenshot(
                f"fail_{action}_{ts}", str(self._work_dir)
            )
            self._evidence.append(ss)
            raise
        except PlaywrightActionError as exc:
            raise AdapterError(exc.action, str(exc)) from exc
        except Exception as exc:
            raise AdapterError(action, f"Erro inesperado: {exc}") from exc

    async def collect_evidence(self, context: RuntimeContext) -> list[str]:
        """Retorna todos os artefatos coletados no Flow."""
        healing_summary = self._healing.summary()
        if healing_summary["healed"] > 0 or healing_summary["broken"] > 0:
            log.info("healing_summary", **healing_summary)
        return list(self._evidence)

    async def take_screenshot(self, context: RuntimeContext, name: str) -> str:
        if not self._executor:
            return ""
        path = await self._executor.screenshot(name, str(self._work_dir))
        self._evidence.append(path)
        return path

    def _action_registry(self) -> set[str]:
        from runtime_core.adapters.playwright.action_executor import ActionExecutor
        return set(ActionExecutor._HANDLERS.keys())

    # ------------------------------------------------------------------
    # Scenario lifecycle hooks
    # Called by ExecutionEngine._execute_scenario via duck-typing check.
    # ------------------------------------------------------------------

    async def begin_scenario(self, scenario_name: str) -> None:
        """
        Cria um BrowserContext isolado para o scenario.
        Chamado antes de cada scenario pelo Execution Engine.
        """
        self._current_scenario = scenario_name
        scenario_dir = self._work_dir / scenario_name.replace(" ", "_")
        scenario_dir.mkdir(parents=True, exist_ok=True)

        page = await self._manager.new_context(scenario_name, scenario_dir)
        self._executor = ActionExecutor(
            page=page,
            healing=self._healing,
            base_url=self._manager.config.base_url,
        )
        log.info("scenario_begin", name=scenario_name)

    async def end_scenario(self, scenario_name: str, passed: bool) -> None:
        """
        Fecha o BrowserContext e coleta evidências do scenario.
        """
        scenario_dir = self._work_dir / scenario_name.replace(" ", "_")
        artifacts    = await self._manager.close_context(
            scenario_name, scenario_dir, passed
        )
        self._evidence.extend(artifacts)
        self._executor = None
        log.info(
            "scenario_end",
            name=scenario_name,
            passed=passed,
            artifacts=len(artifacts),
        )

    # ------------------------------------------------------------------
    # Healing report (Fase 4 hook)
    # ------------------------------------------------------------------

    @property
    def broken_locators(self) -> list:
        """Lista de locators quebrados — input para o Repair Agent."""
        return self._healing.broken_reports

    @property
    def healing_summary(self) -> dict:
        return self._healing.summary()
