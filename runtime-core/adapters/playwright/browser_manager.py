"""
runtime_core/adapters/playwright/browser_manager.py
AQuA-QE LKDF — Playwright Adapter: Browser Manager

Responsável por:
  - Inicializar e encerrar o Playwright runtime
  - Criar BrowserContext isolado por scenario (cookies, storage, network limpos)
  - Expor Page para o ActionExecutor
  - Gerenciar configurações de browser (headless, viewport, locale, timezone)
  - Interceptar network requests para logging e mock (base para Fase 3 API Adapter)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class BrowserConfig:
    """Configurações do browser para o Playwright Adapter."""
    browser:        str   = "chromium"       # chromium | firefox | webkit
    headless:       bool  = True
    slow_mo:        int   = 0                # ms entre ações (debug)
    viewport_width: int   = 1280
    viewport_height:int   = 720
    locale:         str   = "pt-BR"
    timezone:       str   = "America/Sao_Paulo"
    base_url:       str   = ""
    video:          bool  = False            # gravar vídeo do scenario
    trace:          bool  = True             # gerar Playwright Trace
    ignore_https_errors: bool = True
    extra_args:     list[str] = field(default_factory=list)


class BrowserManager:
    """
    Gerencia o ciclo de vida do browser no Playwright Adapter.

    Hierarquia de isolamento:
      Playwright → Browser (reutilizado) → BrowserContext (por scenario) → Page
    
    O BrowserContext garante que cada scenario começa com:
      - cookies limpos
      - localStorage/sessionStorage limpos
      - service workers limpos
      - interceptors de network resetados
    """

    def __init__(self, config: BrowserConfig) -> None:
        self.config   = config
        self._pw:      Any | None = None    # Playwright instance
        self._browser: Any | None = None    # Browser instance (reutilizado)
        self._context: Any | None = None    # BrowserContext (por scenario)
        self._page:    Any | None = None    # Page atual
        self._trace_started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Inicializa Playwright e lança o browser. Chamado uma vez por Flow."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright não instalado. Execute: pip install playwright && playwright install"
            )

        self._pw      = await async_playwright().start()
        browser_type  = getattr(self._pw, self.config.browser)
        self._browser = await browser_type.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
            args=self.config.extra_args,
        )
        log.info(
            "browser_launched",
            browser=self.config.browser,
            headless=self.config.headless,
        )

    async def new_context(self, scenario_name: str, artifacts_dir: Path) -> Any:
        """
        Cria um BrowserContext isolado para o scenario.
        Deve ser chamado antes de cada scenario pelo Adapter.
        Retorna a Page pronta para uso.
        """
        if not self._browser:
            raise RuntimeError("Browser não inicializado. Chame start() primeiro.")

        ctx_options: dict[str, Any] = {
            "viewport":         {"width": self.config.viewport_width,
                                 "height": self.config.viewport_height},
            "locale":           self.config.locale,
            "timezone_id":      self.config.timezone,
            "ignore_https_errors": self.config.ignore_https_errors,
            "base_url":         self.config.base_url or None,
        }

        if self.config.video:
            video_dir = artifacts_dir / "videos"
            video_dir.mkdir(parents=True, exist_ok=True)
            ctx_options["record_video_dir"]  = str(video_dir)
            ctx_options["record_video_size"] = {
                "width":  self.config.viewport_width,
                "height": self.config.viewport_height,
            }

        self._context = await self._browser.new_context(**ctx_options)

        if self.config.trace:
            await self._context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=False,
            )
            self._trace_started = True

        self._page = await self._context.new_page()
        self._setup_page_logging()

        log.info("context_created", scenario=scenario_name)
        return self._page

    async def close_context(self, scenario_name: str, artifacts_dir: Path, passed: bool) -> list[str]:
        """
        Fecha o BrowserContext do scenario atual e coleta evidências.
        Retorna lista de caminhos dos artefatos gerados.
        """
        artifacts: list[str] = []
        if not self._context:
            return artifacts

        try:
            # Captura screenshot final
            if self._page:
                suffix  = "pass" if passed else "fail"
                ss_path = artifacts_dir / f"screenshot_{scenario_name}_{suffix}.png"
                ss_path.parent.mkdir(parents=True, exist_ok=True)
                await self._page.screenshot(path=str(ss_path), full_page=True)
                artifacts.append(str(ss_path))

            # Salva Playwright Trace
            if self._trace_started:
                trace_path = artifacts_dir / f"trace_{scenario_name}.zip"
                await self._context.tracing.stop(path=str(trace_path))
                artifacts.append(str(trace_path))
                self._trace_started = False

            # Coleta vídeo
            if self.config.video and self._page:
                video = self._page.video
                if video:
                    video_path = artifacts_dir / f"video_{scenario_name}.webm"
                    await video.save_as(str(video_path))
                    artifacts.append(str(video_path))

        finally:
            await self._context.close()
            self._context = None
            self._page    = None

        log.info("context_closed", scenario=scenario_name, artifacts=len(artifacts))
        return artifacts

    async def stop(self) -> None:
        """Para o browser e o Playwright. Chamado ao fim do Flow."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        log.info("browser_stopped")

    # ------------------------------------------------------------------
    # Page access
    # ------------------------------------------------------------------

    @property
    def page(self) -> Any:
        if not self._page:
            raise RuntimeError("Nenhuma Page ativa. Chame new_context() primeiro.")
        return self._page

    # ------------------------------------------------------------------
    # Page logging
    # ------------------------------------------------------------------

    def _setup_page_logging(self) -> None:
        """Registra listeners de console e erros da página."""
        if not self._page:
            return

        def on_console(msg: Any) -> None:
            if msg.type in ("error", "warning"):
                log.debug("browser_console", type=msg.type, text=msg.text[:200])

        def on_pageerror(exc: Any) -> None:
            log.warning("browser_page_error", error=str(exc)[:200])

        self._page.on("console",   on_console)
        self._page.on("pageerror", on_pageerror)
