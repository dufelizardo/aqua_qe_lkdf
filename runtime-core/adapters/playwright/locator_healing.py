"""
runtime_core/adapters/playwright/locator_healing.py
AQuA-QE LKDF — Playwright Adapter: Locator Healing Middleware

Implementa a cadeia de resolução de locators:
  1. Locator primário do POM (data-testid preferido)
  2. Fallbacks do POM (id, css, xpath, aria)
  3. Heurística semântica (baseada no nome do elemento)
  4. Registro de elemento "quebrado" → base para Repair Agent (Fase 4)

A separação em middleware garante que o ActionExecutor nunca precisa
conhecer detalhes de resolução — apenas recebe um locator funcional ou
sabe que o elemento está quebrado.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from runtime_core.pom_layer.registry import POMRegistry, get_registry

log = structlog.get_logger(__name__)


class HealingStrategy(str, Enum):
    POM_PRIMARY   = "pom_primary"
    POM_FALLBACK  = "pom_fallback"
    HEURISTIC     = "heuristic"
    FAILED        = "failed"


@dataclass
class HealingResult:
    locator_str:  str
    strategy:     HealingStrategy
    element_query: str
    healed:       bool = False      # True se usou fallback (não o primário)
    broken:       bool = False      # True se todos falharam


@dataclass
class BrokenLocatorReport:
    """Registrado quando nenhuma estratégia resolve o elemento."""
    element_query: str
    page_name:     str
    tried:         list[str] = field(default_factory=list)
    context_url:   str = ""


class LocatorHealingMiddleware:
    """
    Middleware de resolução e healing de locators.

    Chamado pelo ActionExecutor antes de qualquer interação com elementos.
    Mantém histórico de locators quebrados para o Repair Agent (Fase 4).
    """

    def __init__(self, pom: POMRegistry | None = None) -> None:
        self.pom             = pom or get_registry()
        self._broken_reports: list[BrokenLocatorReport] = []
        self._healing_log:    list[HealingResult]       = []

    # ------------------------------------------------------------------
    # Main resolution API
    # ------------------------------------------------------------------

    async def resolve(
        self,
        page:          Any,           # Playwright Page
        element_query: str,
        page_name:     str | None = None,
        timeout_ms:    int        = 3000,
    ) -> HealingResult:
        """
        Resolve um query semântico para um locator Playwright funcional.
        Tenta cada estratégia em ordem e para no primeiro sucesso.
        """
        tried: list[str] = []

        # 1. POM Primary
        pom_page = self.pom.get_page(page_name or "")
        if pom_page:
            elem = pom_page.find_element(element_query)
            if elem and elem.primary_locator:
                loc_str = elem.primary_locator.to_playwright()
                tried.append(loc_str)
                if await self._is_visible(page, loc_str, timeout_ms):
                    result = HealingResult(
                        locator_str=loc_str,
                        strategy=HealingStrategy.POM_PRIMARY,
                        element_query=element_query,
                    )
                    self._healing_log.append(result)
                    return result

                # 2. POM Fallbacks
                for fallback in elem.locators[1:]:
                    fb_str = fallback.to_playwright()
                    tried.append(fb_str)
                    if await self._is_visible(page, fb_str, timeout_ms):
                        result = HealingResult(
                            locator_str=fb_str,
                            strategy=HealingStrategy.POM_FALLBACK,
                            element_query=element_query,
                            healed=True,
                        )
                        log.warning(
                            "locator_healed",
                            element=element_query,
                            strategy="pom_fallback",
                            used=fb_str,
                        )
                        self._healing_log.append(result)
                        return result

        # 3. Global POM search
        loc = self.pom.resolve(element_query)
        if loc:
            loc_str = loc.to_playwright()
            tried.append(loc_str)
            if await self._is_visible(page, loc_str, timeout_ms):
                result = HealingResult(
                    locator_str=loc_str,
                    strategy=HealingStrategy.POM_FALLBACK,
                    element_query=element_query,
                    healed=True,
                )
                self._healing_log.append(result)
                return result

        # 4. Heuristic fallback
        heuristic = self._heuristic(element_query)
        tried.append(heuristic)
        if await self._is_visible(page, heuristic, timeout_ms):
            result = HealingResult(
                locator_str=heuristic,
                strategy=HealingStrategy.HEURISTIC,
                element_query=element_query,
                healed=True,
            )
            log.warning(
                "locator_healed_heuristic",
                element=element_query,
                used=heuristic,
            )
            self._healing_log.append(result)
            return result

        # 5. All strategies failed — register as broken
        current_url = ""
        try:
            current_url = page.url
        except Exception:
            pass

        report = BrokenLocatorReport(
            element_query=element_query,
            page_name=page_name or "",
            tried=tried,
            context_url=current_url,
        )
        self._broken_reports.append(report)
        log.error(
            "locator_broken",
            element=element_query,
            tried=tried,
            url=current_url,
        )

        # Return last tried so execution can fail with meaningful error
        result = HealingResult(
            locator_str=tried[-1] if tried else element_query,
            strategy=HealingStrategy.FAILED,
            element_query=element_query,
            healed=False,
            broken=True,
        )
        self._healing_log.append(result)
        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def broken_reports(self) -> list[BrokenLocatorReport]:
        return list(self._broken_reports)

    @property
    def healing_log(self) -> list[HealingResult]:
        return list(self._healing_log)

    @property
    def healed_count(self) -> int:
        return sum(1 for r in self._healing_log if r.healed)

    @property
    def broken_count(self) -> int:
        return sum(1 for r in self._healing_log if r.broken)

    def summary(self) -> dict:
        return {
            "total_resolutions": len(self._healing_log),
            "primary_hits":      sum(1 for r in self._healing_log
                                     if r.strategy == HealingStrategy.POM_PRIMARY),
            "healed":            self.healed_count,
            "broken":            self.broken_count,
            "broken_elements":   [r.element_query for r in self._broken_reports],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _is_visible(page: Any, locator_str: str, timeout_ms: int) -> bool:
        """Verifica se um locator existe e está visível na página."""
        try:
            loc = page.locator(locator_str).first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    @staticmethod
    def _heuristic(query: str) -> str:
        """
        Gera locator de fallback via heurística semântica.
        Prioridade: data-testid → aria-label → text → role.
        """
        q = query.lower().strip().strip('"')

        # Semantic → testid slug
        semantic_map = {
            "email":    "[data-testid='email-input'], input[type='email']",
            "senha":    "[data-testid='password-input'], input[type='password']",
            "password": "input[type='password']",
            "entrar":   "[data-testid='login-btn'], button[type='submit']",
            "enviar":   "button[type='submit']",
            "submit":   "button[type='submit']",
            "login":    "[data-testid='login-btn'], button[type='submit']",
            "usuário":  "input[name='username'], input[name='user']",
            "usuario":  "input[name='username'], input[name='user']",
            "buscar":   "input[type='search'], [data-testid='search']",
            "cancelar": "button:has-text('Cancelar'), [data-testid='cancel-btn']",
            "confirmar":"button:has-text('Confirmar'), [data-testid='confirm-btn']",
            "fechar":   "[aria-label='Fechar'], [data-testid='close-btn']",
            "nome":     "input[name='name'], [data-testid='name-input']",
            "cpf":      "input[name='cpf'], [data-testid='cpf-input']",
        }

        for key, loc in semantic_map.items():
            if key in q:
                return loc.split(",")[0].strip()

        # Generic: try text match then testid slug
        slug = q.replace(" ", "-").replace('"', "")
        return f"[data-testid='{slug}']"
