"""
runtime_core/adapters/cypress/adapter.py
AQuA-QE LKDF v1.4 — Cypress Adapter

Traduz actions semânticas do LKDF para comandos Cypress (.cy.ts).
Gera arquivos de teste TypeScript e executa via subprocess (npx cypress run).

Diferenças vs. Playwright:
  - Execução via Node.js / npx (não in-process)
  - Output em JSON report (cypress-json-results ou mochawesome)
  - cy.intercept() para mock de rede
  - Comandos customizados via support/commands.ts
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import structlog

from runtime_core.adapters.base import BaseAdapter, AdapterError
from shared.models import AdapterType, RuntimeContext

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Action → Cypress command mapping
# ---------------------------------------------------------------------------

_ACTION_MAP: dict[str, str] = {
    # Navigation
    "navigate":       "cy.visit('{value}')",
    "open_page":      "cy.visit('{value}')",
    "open_url":       "cy.visit('{value}')",

    # Input
    "fill":           "cy.get('{locator}').clear().type('{value}')",
    "fill_field":     "cy.get('{locator}').clear().type('{value}')",

    # Interaction
    "click_element":  "cy.get('{locator}').click()",
    "click":          "cy.get('{locator}').click()",
    "submit":         "cy.get('{locator}').submit()",
    "submit_form":    "cy.get('form').submit()",

    # Assertions
    "assert_text":    "cy.contains('{value}').should('exist')",
    "assert_message": "cy.contains('{value}').should('be.visible')",
    "assert_url":     "cy.url().should('include', '{value}')",
    "assert_redirect":"cy.url().should('include', '{value}')",
    "assert_title":   "cy.title().should('include', '{value}')",
    "assert_visible": "cy.get('{locator}').should('be.visible')",
    "assert_hidden":  "cy.get('{locator}').should('not.be.visible')",
    "assert_result":  "cy.contains('{value}').should('exist')",

    # Wait
    "wait_seconds":   "cy.wait({value})",
    "wait_for_element":"cy.get('{locator}').should('be.visible')",

    # Setup
    "set_valid_credentials": "cy.setCookie('auth', 'valid')",
    "verify_login":   "cy.url().should('not.include', 'login')",
    "execute_keyword":"cy.log('{value}')",
    "generic_action": "cy.log('{value}')",
}

# ---------------------------------------------------------------------------
# Cypress Adapter
# ---------------------------------------------------------------------------

class CypressAdapter(BaseAdapter):
    """
    Adapter Cypress para o LKDF Runtime Core.
    Gera arquivos .cy.ts e executa via `npx cypress run`.

    Uso no DSL:
        # Adapter: cypress
    """

    adapter_type = AdapterType.CYPRESS

    def __init__(
        self,
        base_url:    str  = "http://localhost:4200",
        headless:    bool = True,
        browser:     str  = "chrome",
        spec_dir:    str  = "",
    ) -> None:
        self._base_url = base_url
        self._headless = headless
        self._browser  = browser
        self._spec_dir: Path | None = Path(spec_dir) if spec_dir else None
        self._work_dir: Path | None = None
        self._commands: list[str]   = []
        self._evidence: list[str]   = []
        self._current_describe: str = ""
        self._current_it: str       = ""
        self._it_blocks: list[dict] = []

    # ------------------------------------------------------------------
    # BaseAdapter
    # ------------------------------------------------------------------

    async def setup(self, context: RuntimeContext) -> None:
        if context.project.base_url:
            self._base_url = context.project.base_url
        self._work_dir = Path(tempfile.mkdtemp(prefix="lkdf_cypress_"))
        self._commands = []
        self._evidence = []
        self._it_blocks = []
        log.info("cypress_adapter_setup", base_url=self._base_url)

    async def teardown(self, context: RuntimeContext) -> None:
        log.info("cypress_adapter_teardown",
                 specs=len(self._it_blocks),
                 evidence=len(self._evidence))

    async def execute_action(
        self,
        action:     str,
        parameters: dict[str, Any],
        context:    RuntimeContext,
    ) -> Any:
        cmd = self._action_to_cypress(action, parameters)
        self._commands.append(cmd)
        log.debug("cypress_cmd", action=action, cmd=cmd[:80])
        return cmd

    async def collect_evidence(self, context: RuntimeContext) -> list[str]:
        if not self._work_dir:
            return []

        # Generate spec file
        spec_path = self._generate_spec()
        self._evidence.append(str(spec_path))

        # Generate cypress.config.ts
        config_path = self._generate_config()
        self._evidence.append(str(config_path))

        return self._evidence

    async def take_screenshot(self, context: RuntimeContext, name: str) -> str:
        # Cypress takes screenshots automatically on failure
        # We add a cy.screenshot() command
        self._commands.append(f"cy.screenshot('{name}')")
        path = str(self._work_dir / f"{name}.png") if self._work_dir else ""
        self._evidence.append(path)
        return path

    def _action_registry(self) -> set[str]:
        return set(_ACTION_MAP.keys())

    # ------------------------------------------------------------------
    # Scenario lifecycle hooks
    # ------------------------------------------------------------------

    async def begin_scenario(self, scenario_name: str) -> None:
        self._current_it = scenario_name
        self._commands   = []

    async def end_scenario(self, scenario_name: str, passed: bool) -> None:
        self._it_blocks.append({
            "name":     scenario_name,
            "commands": list(self._commands),
            "passed":   passed,
        })
        self._commands = []

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def _action_to_cypress(self, action: str, params: dict) -> str:
        template = _ACTION_MAP.get(action, "cy.log('unknown action: {value}')")
        p        = params

        locator = self._resolve_locator(
            p.get("field_raw", p.get("element_raw", p.get("field", p.get("element", ""))))
        )
        value = p.get("value", p.get("text", p.get("title",
            p.get("url", p.get("page", p.get("target",
            p.get("seconds", p.get("param_0", ""))))))))

        if action in ("wait_seconds",) and value:
            try:
                value = str(int(float(str(value).rstrip("s")) * 1000))
            except ValueError:
                value = "1000"

        cmd = template.replace("{locator}", locator).replace("{value}", str(value))
        return f"    {cmd};"

    def _generate_spec(self) -> Path:
        """Gera arquivo .cy.ts com todos os it() blocks coletados."""
        ts_lines = [
            "/// <reference types='cypress' />",
            "",
            f"describe('LKDF Generated — {self._current_describe or 'Flow'}', () => {{",
            "  beforeEach(() => {",
            f"    cy.visit('{self._base_url}');",
            "  });",
            "",
        ]

        for block in self._it_blocks:
            ts_lines.append(f"  it('{block['name']}', () => {{")
            for cmd in block["commands"]:
                ts_lines.append(cmd)
            ts_lines.append("  });")
            ts_lines.append("")

        ts_lines.append("});")
        ts_lines.append("")

        spec_path = self._work_dir / "lkdf_generated.cy.ts"
        spec_path.write_text("\n".join(ts_lines), encoding="utf-8")
        log.info("cypress_spec_generated", path=str(spec_path),
                 scenarios=len(self._it_blocks))
        return spec_path

    def _generate_config(self) -> Path:
        config = {
            "e2e": {
                "baseUrl":         self._base_url,
                "specPattern":     "**/*.cy.ts",
                "supportFile":     False,
                "video":           False,
                "screenshotOnRunFailure": True,
                "reporter":        "json",
                "reporterOptions": {"output": "results.json"},
            }
        }
        config_path = self._work_dir / "cypress.config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return config_path

    async def run_cypress(self) -> dict[str, Any]:
        """
        Executa Cypress via subprocess.
        Requer Node.js e cypress instalados no ambiente.
        """
        if not self._work_dir:
            raise AdapterError("run_cypress", "Adapter not initialized.")

        spec = self._work_dir / "lkdf_generated.cy.ts"
        if not spec.exists():
            await self.collect_evidence(RuntimeContext())

        cmd = [
            "npx", "cypress", "run",
            "--spec", str(spec),
            "--config-file", str(self._work_dir / "cypress.config.json"),
            "--browser", self._browser,
        ]
        if self._headless:
            cmd.append("--headless")

        log.info("cypress_run_start", cmd=" ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._work_dir),
        )
        stdout, stderr = await proc.communicate()
        return {
            "returncode": proc.returncode,
            "stdout":     stdout.decode()[:5000],
            "stderr":     stderr.decode()[:2000],
            "passed":     proc.returncode == 0,
        }

    @staticmethod
    def _resolve_locator(query: str) -> str:
        if not query:
            return "[data-testid]"
        q = query.lower().strip().strip('"')
        heuristics = {
            "email":    "[data-testid='email-input']",
            "senha":    "[data-testid='password-input']",
            "password": "[data-testid='password-input']",
            "entrar":   "[data-testid='login-btn']",
            "submit":   "[type='submit']",
            "login":    "[data-testid='login-btn']",
        }
        for key, sel in heuristics.items():
            if key in q:
                return sel
        slug = q.replace(" ", "-").replace('"', "")
        return f"[data-testid='{slug}']"
