"""
runtime_core/context_engine/engine.py
AQuA-QE LKDF — Context Engine

Responsável por:
  - Gerenciar o contexto de projeto (framework, auth, adapter, URLs)
  - Manter o estado de runtime durante a execução (variáveis, página atual, sessão)
  - Enriquecer steps com contexto semântico (resolução de variáveis, substituição)
  - Detectar mudanças de contexto entre steps (navegação, autenticação)
  - Integrar com o POM Layer para resolução de elementos
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from shared.models import ProjectContext, RuntimeContext, SemanticStep
from runtime_core.pom_layer.registry import POMRegistry, get_registry

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Context Events
# ---------------------------------------------------------------------------

@dataclass
class ContextEvent:
    event_type: str       # navigate | login | logout | variable_set | page_change
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Variable Store
# ---------------------------------------------------------------------------

class VariableStore:
    """
    Store de variáveis de runtime do LKDF.
    Suporta escopos: global, flow, scenario, step.
    Resolve referências ${VAR} e %{ENV_VAR} no texto dos steps.
    """

    _VAR_RE = re.compile(r"\$\{(\w+)\}")
    _ENV_RE = re.compile(r"%\{(\w+)\}")

    def __init__(self) -> None:
        self._global:   dict[str, Any] = {}
        self._flow:     dict[str, Any] = {}
        self._scenario: dict[str, Any] = {}
        self._step:     dict[str, Any] = {}

    # --- Setters por escopo ---
    def set_global(self, key: str, value: Any) -> None:
        self._global[key] = value

    def set_flow(self, key: str, value: Any) -> None:
        self._flow[key] = value

    def set_scenario(self, key: str, value: Any) -> None:
        self._scenario[key] = value

    def set_step(self, key: str, value: Any) -> None:
        self._step[key] = value

    def set(self, key: str, value: Any, scope: str = "scenario") -> None:
        getattr(self, f"set_{scope}")(key, value)

    # --- Resolution (escopo mais específico ganha) ---
    def get(self, key: str, default: Any = None) -> Any:
        for store in (self._step, self._scenario, self._flow, self._global):
            if key in store:
                return store[key]
        return default

    def resolve(self, text: str) -> str:
        """Substitui ${VAR} e %{ENV} no texto."""
        import os
        result = self._VAR_RE.sub(
            lambda m: str(self.get(m.group(1), m.group(0))), text
        )
        result = self._ENV_RE.sub(
            lambda m: os.environ.get(m.group(1), m.group(0)), result
        )
        return result

    def clear_scenario(self) -> None:
        self._scenario.clear()
        self._step.clear()

    def clear_flow(self) -> None:
        self._flow.clear()
        self.clear_scenario()

    def snapshot(self) -> dict[str, Any]:
        return {
            "global":   dict(self._global),
            "flow":     dict(self._flow),
            "scenario": dict(self._scenario),
        }


# ---------------------------------------------------------------------------
# Context Engine
# ---------------------------------------------------------------------------

class ContextEngine:
    """
    Motor de gerenciamento de contexto do LKDF Runtime.

    Integra com:
      - VariableStore: resolução de variáveis nos steps
      - POMRegistry:   resolução de elementos semânticos para locators
      - RuntimeContext: estado mutável da execução atual

    O ContextEngine é o único componente que sabe "onde o sistema está"
    em qualquer momento da execução.
    """

    def __init__(
        self,
        project: ProjectContext,
        pom: POMRegistry | None = None,
    ) -> None:
        self.project    = project
        self.pom        = pom or get_registry()
        self.variables  = VariableStore()
        self._events:   list[ContextEvent] = []
        self._current_page: str = ""
        self._authenticated: bool = False
        self._session_data: dict[str, Any] = {}

        self._init_default_variables()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_default_variables(self) -> None:
        """Popula variáveis padrão baseadas no ProjectContext."""
        self.variables.set_global("BASE_URL",   self.project.base_url or "http://localhost:4200")
        self.variables.set_global("FRAMEWORK",  self.project.framework)
        self.variables.set_global("AUTH_TYPE",  self.project.auth_type)
        self.variables.set_global("ADAPTER",    self.project.adapter)
        self.variables.set_global("TIMESTAMP",  datetime.utcnow().isoformat())

    # ------------------------------------------------------------------
    # Step enrichment
    # ------------------------------------------------------------------

    def enrich_step(self, step: SemanticStep) -> SemanticStep:
        """
        Enriquece um step com contexto de runtime:
        - Resolve variáveis ${VAR} no texto e parâmetros
        - Resolve locators semânticos via POM
        - Detecta mudanças de contexto (navigate, login, etc.)
        - Atualiza estado interno
        """
        # 1. Resolve variáveis no texto
        resolved_text = self.variables.resolve(step.text)

        # 2. Resolve variáveis nos parâmetros + POM locators
        resolved_params = {}
        for k, v in step.parameters.items():
            val = self.variables.resolve(str(v))

            # Se é uma referência a elemento de UI, resolve via POM
            if k in ("field", "element", "locator"):
                locator = self.pom.resolve_to_string(val, self._current_page)
                resolved_params[k] = locator
                resolved_params[f"{k}_raw"] = val      # mantém nome original
            else:
                resolved_params[k] = val

        # 3. Detecta mudanças de contexto
        self._detect_context_change(step)

        # 4. Injeta variáveis de contexto nos parâmetros
        resolved_params["__page__"]           = self._current_page
        resolved_params["__authenticated__"]  = self._authenticated
        resolved_params["__base_url__"]       = self.variables.get("BASE_URL")

        return step.model_copy(update={
            "text":       resolved_text,
            "parameters": {**step.parameters, **resolved_params},
        })

    def _detect_context_change(self, step: SemanticStep) -> None:
        intent = step.intent

        if intent in ("navigate", "open_page", "open_url"):
            page = step.parameters.get("page", step.parameters.get("target", ""))
            self._on_navigate(page)

        elif intent in ("assert_authenticated", "set_valid_credentials"):
            self._on_login()

        elif intent == "logout":
            self._on_logout()

        elif intent in ("fill_field",) and "page" in step.parameters:
            self._current_page = step.parameters["page"]

    # ------------------------------------------------------------------
    # Context state transitions
    # ------------------------------------------------------------------

    def _on_navigate(self, destination: str) -> None:
        prev = self._current_page
        self._current_page = destination

        # Try to find matching Page Object
        page_obj = self.pom.find_page_for_url(destination)
        if page_obj:
            self._current_page = page_obj.name
            log.debug("context_navigate", to=page_obj.name, url=destination)
        else:
            log.debug("context_navigate_unknown", to=destination)

        self._emit(ContextEvent(
            event_type="navigate",
            data={"from": prev, "to": self._current_page, "url": destination},
        ))

    def _on_login(self) -> None:
        if not self._authenticated:
            self._authenticated = True
            self._emit(ContextEvent(event_type="login"))
            log.debug("context_login")

    def _on_logout(self) -> None:
        self._authenticated = False
        self.variables.clear_scenario()
        self._emit(ContextEvent(event_type="logout"))
        log.debug("context_logout")

    # ------------------------------------------------------------------
    # Scenario lifecycle
    # ------------------------------------------------------------------

    def begin_scenario(self, scenario_name: str) -> None:
        """Prepara o contexto para execução de um novo scenario."""
        self.variables.clear_scenario()
        self.variables.set_scenario("SCENARIO_NAME", scenario_name)
        self._emit(ContextEvent(
            event_type="scenario_begin",
            data={"name": scenario_name},
        ))
        log.debug("context_scenario_begin", name=scenario_name)

    def end_scenario(self, scenario_name: str, status: str) -> None:
        self._emit(ContextEvent(
            event_type="scenario_end",
            data={"name": scenario_name, "status": status},
        ))

    def begin_flow(self, flow_name: str) -> None:
        self.variables.clear_flow()
        self.variables.set_flow("FLOW_NAME", flow_name)
        self._emit(ContextEvent(event_type="flow_begin", data={"name": flow_name}))

    def end_flow(self, flow_name: str, status: str) -> None:
        self._emit(ContextEvent(event_type="flow_end", data={"name": flow_name, "status": status}))

    # ------------------------------------------------------------------
    # Variable management (DSL-level)
    # ------------------------------------------------------------------

    def set_variable(self, name: str, value: Any, scope: str = "scenario") -> None:
        self.variables.set(name, value, scope)
        self._emit(ContextEvent(
            event_type="variable_set",
            data={"name": name, "scope": scope},
        ))

    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)

    def resolve_text(self, text: str) -> str:
        return self.variables.resolve(text)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def current_page(self) -> str:
        return self._current_page

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    def build_runtime_context(self) -> RuntimeContext:
        """Constrói um RuntimeContext atualizado com o estado atual."""
        return RuntimeContext(
            project=self.project,
            variables=self.variables.snapshot(),
            current_page=self._current_page,
            state={
                "authenticated": self._authenticated,
                "session":       self._session_data,
                "events":        len(self._events),
            },
        )

    def events_log(self) -> list[dict[str, Any]]:
        return [
            {
                "type":      e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "data":      e.data,
            }
            for e in self._events
        ]

    def _emit(self, event: ContextEvent) -> None:
        self._events.append(event)
