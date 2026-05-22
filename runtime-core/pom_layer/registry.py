"""
runtime_core/pom_layer/registry.py
AQuA-QE LKDF — POM Layer (Page Object Model Layer)

Responsável por:
  - Registrar e gerenciar Page Objects de forma semântica
  - Resolver nomes de elementos para locators concretos
  - Abstrair locators do DSL (o DSL nunca referencia locators técnicos)
  - Suportar múltiplas estratégias: css, xpath, id, testid, text, aria
  - Detectar e alertar sobre Page Objects desatualizados (base para self-healing Fase 4)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Locator strategies
# ---------------------------------------------------------------------------

class LocatorStrategy(str, Enum):
    CSS      = "css"
    XPATH    = "xpath"
    ID       = "id"
    TESTID   = "testid"      # data-testid
    TEXT     = "text"
    ARIA     = "aria-label"
    NAME     = "name"
    CLASS    = "class"


@dataclass
class Locator:
    strategy: LocatorStrategy
    value: str
    description: str = ""
    fragile: bool = False        # True = propenso a quebrar (base para self-healing)

    def to_rf(self) -> str:
        """Converte para sintaxe Robot Framework SeleniumLibrary."""
        mapping = {
            LocatorStrategy.CSS:    f"css:{self.value}",
            LocatorStrategy.XPATH:  f"xpath:{self.value}",
            LocatorStrategy.ID:     f"id:{self.value}",
            LocatorStrategy.TESTID: f"css:[data-testid='{self.value}']",
            LocatorStrategy.TEXT:   f"xpath://*[contains(text(), '{self.value}')]",
            LocatorStrategy.ARIA:   f"css:[aria-label='{self.value}']",
            LocatorStrategy.NAME:   f"name:{self.value}",
            LocatorStrategy.CLASS:  f"css:.{self.value}",
        }
        return mapping[self.strategy]

    def to_playwright(self) -> str:
        """Converte para sintaxe Playwright (Fase 3)."""
        mapping = {
            LocatorStrategy.CSS:    self.value,
            LocatorStrategy.XPATH:  f"xpath={self.value}",
            LocatorStrategy.ID:     f"#{self.value}",
            LocatorStrategy.TESTID: f"[data-testid='{self.value}']",
            LocatorStrategy.TEXT:   f"text={self.value}",
            LocatorStrategy.ARIA:   f"[aria-label='{self.value}']",
            LocatorStrategy.NAME:   f"[name='{self.value}']",
            LocatorStrategy.CLASS:  f".{self.value}",
        }
        return mapping[self.strategy]


# ---------------------------------------------------------------------------
# Page Element
# ---------------------------------------------------------------------------

@dataclass
class PageElement:
    """Representa um elemento de UI com seus locators e aliases semânticos."""
    name: str                              # nome canônico: "campo_email"
    aliases: list[str] = field(default_factory=list)   # ["email", "campo de email", "e-mail"]
    locators: list[Locator] = field(default_factory=list)  # ordered by preference
    description: str = ""
    required: bool = True

    @property
    def primary_locator(self) -> Locator | None:
        return self.locators[0] if self.locators else None

    def matches(self, query: str) -> bool:
        """Verifica se uma query semântica corresponde a este elemento."""
        q = query.lower().strip().strip('"')
        return (
            q == self.name.lower()
            or q in [a.lower() for a in self.aliases]
            or any(q in a.lower() for a in self.aliases)
            or self.name.lower() in q
        )


# ---------------------------------------------------------------------------
# Page Object
# ---------------------------------------------------------------------------

@dataclass
class PageObject:
    """Agrupa elementos de uma página/componente."""
    name: str
    url_pattern: str = ""              # regex ou glob: "/login", "/dashboard*"
    title_pattern: str = ""
    elements: dict[str, PageElement] = field(default_factory=dict)
    actions: dict[str, str] = field(default_factory=dict)  # ação → keyword RF
    tags: list[str] = field(default_factory=list)

    def find_element(self, query: str) -> PageElement | None:
        """Busca semântica de elemento por nome ou alias."""
        # Exact match first
        if query in self.elements:
            return self.elements[query]
        # Alias/fuzzy match
        for elem in self.elements.values():
            if elem.matches(query):
                return elem
        return None


# ---------------------------------------------------------------------------
# POM Registry
# ---------------------------------------------------------------------------

class POMRegistry:
    """
    Registro central de Page Objects.
    Resolve queries semânticas do DSL para locators concretos do adapter.
    Completamente desacoplado do adapter — o mesmo POM serve RF, Playwright, Cypress.
    """

    def __init__(self) -> None:
        self._pages: dict[str, PageObject] = {}
        self._loaded_files: list[str] = []
        self._resolution_cache: dict[str, Locator | None] = {}

        # Seed com Page Objects padrão
        self._seed_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, page: PageObject) -> None:
        self._pages[page.name] = page
        self._resolution_cache.clear()

    def register_many(self, pages: list[PageObject]) -> None:
        for page in pages:
            self.register(page)

    def load_from_file(self, path: str | Path) -> None:
        """Carrega Page Objects de arquivo JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for page_data in data.get("pages", []):
            page = self._parse_page_object(page_data)
            self.register(page)
        self._loaded_files.append(str(path))

    def load_from_dict(self, data: dict[str, Any]) -> None:
        for page_data in data.get("pages", []):
            self.register(self._parse_page_object(page_data))

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        element_query: str,
        page_name: str | None = None,
        adapter: str = "robot",
    ) -> Locator | None:
        """
        Resolve uma query semântica para um Locator concreto.
        Procura em todos os Page Objects se page_name não for especificado.
        """
        cache_key = f"{element_query}:{page_name}:{adapter}"
        if cache_key in self._resolution_cache:
            return self._resolution_cache[cache_key]

        result = self._resolve_internal(element_query, page_name)
        self._resolution_cache[cache_key] = result
        return result

    def resolve_to_string(
        self,
        element_query: str,
        page_name: str | None = None,
        adapter: str = "robot",
    ) -> str:
        """Resolve e retorna string pronta para uso no adapter."""
        locator = self.resolve(element_query, page_name, adapter)
        if not locator:
            # Fallback inteligente baseado na query
            return self._smart_fallback(element_query)

        if adapter == "playwright":
            return locator.to_playwright()
        return locator.to_rf()

    def _resolve_internal(
        self, query: str, page_name: str | None
    ) -> Locator | None:
        # 1. Busca na página específica
        if page_name and page_name in self._pages:
            elem = self._pages[page_name].find_element(query)
            if elem and elem.primary_locator:
                return elem.primary_locator

        # 2. Busca global em todos os pages
        for page in self._pages.values():
            elem = page.find_element(query)
            if elem and elem.primary_locator:
                return elem.primary_locator

        return None

    @staticmethod
    def _smart_fallback(query: str) -> str:
        """
        Gera locator de fallback quando elemento não está no POM.
        Usa heurísticas baseadas no nome semântico.
        """
        q = query.lower().strip().strip('"')

        # Known semantic → locator heuristics
        heuristics = {
            "email":      "css:input[type='email'], id:email, name:email",
            "senha":      "css:input[type='password'], id:password, id:senha",
            "password":   "css:input[type='password']",
            "usuario":    "css:input[name='username'], id:username",
            "entrar":     "css:button[type='submit'], css:input[type='submit']",
            "enviar":     "css:button[type='submit']",
            "submit":     "css:button[type='submit']",
            "login":      "css:button[type='submit'], id:login-btn",
            "cancelar":   "css:button[type='button']",
            "fechar":     "css:.close, css:[aria-label='Fechar']",
            "confirmar":  "css:button.confirm, css:[data-testid='confirm-btn']",
            "pesquisar":  "css:input[type='search'], id:search",
            "buscar":     "css:input[type='search']",
            "nome":       "css:input[name='name'], id:name",
            "telefone":   "css:input[type='tel'], name:phone",
            "cpf":        "css:input[name='cpf'], id:cpf",
        }

        for key, locator in heuristics.items():
            if key in q:
                # Return first option
                return locator.split(",")[0].strip()

        # Generic fallback: data-testid slug
        slug = q.replace(" ", "-").replace('"', "")
        return f"css:[data-testid='{slug}']"

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_pages(self) -> list[str]:
        return list(self._pages.keys())

    def get_page(self, name: str) -> PageObject | None:
        return self._pages.get(name)

    def find_page_for_url(self, url: str) -> PageObject | None:
        import re
        for page in self._pages.values():
            if page.url_pattern and re.search(page.url_pattern, url):
                return page
        return None

    def coverage_report(self) -> dict[str, Any]:
        """Relatório de cobertura do POM — elementos registrados vs. usados."""
        return {
            "pages":           len(self._pages),
            "total_elements":  sum(len(p.elements) for p in self._pages.values()),
            "loaded_files":    self._loaded_files,
            "cache_hits":      len(self._resolution_cache),
        }

    # ------------------------------------------------------------------
    # Seed — Page Objects padrão para o MVP
    # ------------------------------------------------------------------

    def _seed_defaults(self) -> None:
        """
        Page Objects padrão para aplicações web comuns.
        Em produção, estes são gerados/atualizados via integração com GitHub/Figma.
        """
        login_page = PageObject(
            name="LoginPage",
            url_pattern=r"/(login|signin|auth)",
            title_pattern="Login",
            elements={
                "campo_email": PageElement(
                    name="campo_email",
                    aliases=["email", "campo email", "e-mail", "usuario", "login"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "email-input", "Campo email"),
                        Locator(LocatorStrategy.ID,    "email"),
                        Locator(LocatorStrategy.CSS,   "input[type='email']"),
                        Locator(LocatorStrategy.NAME,  "email"),
                    ],
                ),
                "campo_senha": PageElement(
                    name="campo_senha",
                    aliases=["senha", "password", "campo senha", "campo de senha"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "password-input"),
                        Locator(LocatorStrategy.ID,    "password"),
                        Locator(LocatorStrategy.CSS,   "input[type='password']"),
                    ],
                ),
                "botao_entrar": PageElement(
                    name="botao_entrar",
                    aliases=["entrar", "login", "enviar", "submit", "logar", "acessar"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "login-btn"),
                        Locator(LocatorStrategy.CSS,   "button[type='submit']"),
                        Locator(LocatorStrategy.XPATH, "//button[contains(text(),'Entrar')]"),
                    ],
                ),
                "mensagem_erro": PageElement(
                    name="mensagem_erro",
                    aliases=["mensagem de erro", "erro", "alerta", "alert"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "error-message"),
                        Locator(LocatorStrategy.CSS,   ".error-message, .alert-danger, [role='alert']"),
                    ],
                    required=False,
                ),
            },
        )

        dashboard_page = PageObject(
            name="DashboardPage",
            url_pattern=r"/(dashboard|home|app)",
            title_pattern="Dashboard",
            elements={
                "titulo": PageElement(
                    name="titulo",
                    aliases=["título", "title", "heading", "h1"],
                    locators=[
                        Locator(LocatorStrategy.CSS,  "h1, .page-title"),
                        Locator(LocatorStrategy.XPATH, "//h1"),
                    ],
                ),
                "menu_usuario": PageElement(
                    name="menu_usuario",
                    aliases=["menu usuário", "user menu", "perfil", "avatar"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "user-menu"),
                        Locator(LocatorStrategy.CSS,    ".user-menu, .avatar"),
                    ],
                ),
                "botao_logout": PageElement(
                    name="botao_logout",
                    aliases=["logout", "sair", "deslogar", "encerrar sessão"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "logout-btn"),
                        Locator(LocatorStrategy.CSS,   "[data-action='logout']"),
                        Locator(LocatorStrategy.XPATH, "//button[contains(text(),'Sair')]"),
                    ],
                ),
                "mensagem_sucesso": PageElement(
                    name="mensagem_sucesso",
                    aliases=["mensagem de sucesso", "sucesso", "bem-vindo", "toast"],
                    locators=[
                        Locator(LocatorStrategy.TESTID, "success-message"),
                        Locator(LocatorStrategy.CSS,   ".toast-success, .alert-success, [role='status']"),
                    ],
                    required=False,
                ),
            },
        )

        self.register(login_page)
        self.register(dashboard_page)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_page_object(data: dict[str, Any]) -> PageObject:
        elements: dict[str, PageElement] = {}
        for name, elem_data in data.get("elements", {}).items():
            locators = [
                Locator(
                    strategy=LocatorStrategy(loc["strategy"]),
                    value=loc["value"],
                    description=loc.get("description", ""),
                    fragile=loc.get("fragile", False),
                )
                for loc in elem_data.get("locators", [])
            ]
            elements[name] = PageElement(
                name=name,
                aliases=elem_data.get("aliases", []),
                locators=locators,
                description=elem_data.get("description", ""),
                required=elem_data.get("required", True),
            )
        return PageObject(
            name=data["name"],
            url_pattern=data.get("url_pattern", ""),
            title_pattern=data.get("title_pattern", ""),
            elements=elements,
            tags=data.get("tags", []),
        )


# ---------------------------------------------------------------------------
# Singleton global registry
# ---------------------------------------------------------------------------

_global_registry: POMRegistry | None = None


def get_registry() -> POMRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = POMRegistry()
    return _global_registry
