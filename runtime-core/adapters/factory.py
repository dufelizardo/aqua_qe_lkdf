"""
runtime_core/adapters/factory.py
AQuA-QE LKDF — Adapter Factory

Resolve qual adapter instanciar baseado no campo `adapter:` do DSL.
Desacopla o Execution Engine de qualquer adapter concreto.

Uso:
    adapter = AdapterFactory.create(flow, context)
    engine  = ExecutionEngine(adapter=adapter)
"""
from __future__ import annotations

from typing import Any

import structlog

from shared.models import AdapterType, Flow, ProjectContext, RuntimeContext
from runtime_core.adapters.base import BaseAdapter

log = structlog.get_logger(__name__)


class AdapterFactory:
    """
    Factory central do LKDF.
    Instancia o adapter correto de forma lazy (import só quando necessário).
    """

    @staticmethod
    def create(
        adapter_type: AdapterType | str,
        context:      ProjectContext | None = None,
    ) -> BaseAdapter:
        """
        Instancia e retorna o adapter correspondente ao tipo.
        
        Args:
            adapter_type: AdapterType enum ou string ('playwright', 'robot-framework', ...)
            context:      ProjectContext com configurações (base_url, extra, ...)
        """
        if isinstance(adapter_type, str):
            try:
                adapter_type = AdapterType(adapter_type)
            except ValueError:
                log.warning("unknown_adapter_type", raw=adapter_type, fallback="robot")
                adapter_type = AdapterType.ROBOT

        ctx    = context or ProjectContext()
        extra  = ctx.extra or {}
        url    = ctx.base_url or "http://localhost:4200"

        if adapter_type == AdapterType.PLAYWRIGHT:
            return AdapterFactory._create_playwright(url, extra)

        if adapter_type == AdapterType.ROBOT:
            return AdapterFactory._create_robot(url, extra)

        if adapter_type == AdapterType.AUTO:
            # Heurística: usa Playwright se disponível, senão Robot
            return AdapterFactory._create_auto(url, extra)

        # Outros adapters (Fase 3)
        log.warning(
            "adapter_not_implemented",
            type=adapter_type,
            fallback="robot-framework",
        )
        return AdapterFactory._create_robot(url, extra)

    @staticmethod
    def from_flow(flow: Flow, context: ProjectContext | None = None) -> BaseAdapter:
        """Cria adapter diretamente a partir de um Flow parseado."""
        return AdapterFactory.create(flow.adapter, context)

    # ------------------------------------------------------------------
    # Concrete factories
    # ------------------------------------------------------------------

    @staticmethod
    def _create_playwright(url: str, extra: dict) -> BaseAdapter:
        from runtime_core.adapters.playwright.playwright_adapter import PlaywrightAdapter
        return PlaywrightAdapter(
            base_url=url,
            browser=extra.get("browser",  "chromium"),
            headless=extra.get("headless", True),
            video=extra.get("video",       False),
            trace=extra.get("trace",       True),
            slow_mo=int(extra.get("slow_mo", 0)),
        )

    @staticmethod
    def _create_robot(url: str, extra: dict) -> BaseAdapter:
        from runtime_core.adapters.robot.robot_adapter import RobotAdapter
        return RobotAdapter(
            base_url=url,
            headless=extra.get("headless", True),
        )

    @staticmethod
    def _create_auto(url: str, extra: dict) -> BaseAdapter:
        try:
            import playwright  # noqa: F401
            log.info("adapter_auto_resolved", choice="playwright")
            return AdapterFactory._create_playwright(url, extra)
        except ImportError:
            log.info("adapter_auto_resolved", choice="robot-framework")
            return AdapterFactory._create_robot(url, extra)

    # ------------------------------------------------------------------
    # Registry (para futuro plugin system)
    # ------------------------------------------------------------------

    _registry: dict[AdapterType, Any] = {}

    @classmethod
    def register(cls, adapter_type: AdapterType, factory_fn: Any) -> None:
        """Registra um adapter customizado. Permite extensão sem modificar o core."""
        cls._registry[adapter_type] = factory_fn

    @classmethod
    def available(cls) -> list[str]:
        """Retorna adapters disponíveis no ambiente atual."""
        available = []
        try:
            import playwright  # noqa: F401
            available.append("playwright")
        except ImportError:
            pass
        try:
            import robot  # noqa: F401
            available.append("robot-framework")
        except ImportError:
            pass
        available.extend(cls._registry.keys())
        return available
