"""
runtime_core/parser/dsl_parser.py
AQuA-QE LKDF — DSL Parser & Tokenizer

Responsável por:
  - Tokenizar o DSL Gherkin semântico do LKDF
  - Construir a AST (Abstract Syntax Tree) semântica
  - Validar a estrutura antes de qualquer execução
  - Extrair metadados (requirement_ref, adapter, tags)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator

from shared.models import (
    AdapterType,
    Flow,
    Priority,
    Scenario,
    SemanticStep,
    StepKeyword,
    StepType,
)


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

class TokenType(str, Enum):
    COMMENT     = "COMMENT"
    META        = "META"        # # Key: value
    FLOW_DEF    = "FLOW_DEF"    # @flow Name
    SCENARIO_DEF= "SCENARIO_DEF"# @scenario Name
    STEP        = "STEP"        # Dado/Quando/Então/E/Mas ...
    TAG         = "TAG"         # @tag
    BLANK       = "BLANK"
    UNKNOWN     = "UNKNOWN"


@dataclass
class Token:
    type: TokenType
    value: str
    line_no: int
    raw: str


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_KEYWORD_MAP: dict[str, StepType] = {
    "dado":   StepType.GIVEN,
    "quando": StepType.WHEN,
    "então":  StepType.THEN,
    "entao":  StepType.THEN,
    "e":      StepType.AND,
    "mas":    StepType.AND,
}

_META_RE      = re.compile(r"^#\s*(\w[\w\s/]+?):\s*(.+)$")
_COMMENT_RE   = re.compile(r"^#")
_FLOW_RE      = re.compile(r"^@flow\s+(\w+)")
_SCENARIO_RE  = re.compile(r"^@scenario\s+(\w+)")
_TAG_RE       = re.compile(r"^@(\w+)")
_PARAM_RE     = re.compile(r'"([^"]*)"')


def tokenize(source: str) -> Iterator[Token]:
    if not source:
        return
    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line:
            yield Token(TokenType.BLANK, "", lineno, raw)
            continue

        if m := _META_RE.match(line):
            yield Token(TokenType.META, f"{m.group(1)}={m.group(2)}", lineno, raw)
        elif _COMMENT_RE.match(line):
            yield Token(TokenType.COMMENT, line[1:].strip(), lineno, raw)
        elif m := _FLOW_RE.match(line):
            yield Token(TokenType.FLOW_DEF, m.group(1), lineno, raw)
        elif m := _SCENARIO_RE.match(line):
            yield Token(TokenType.SCENARIO_DEF, m.group(1), lineno, raw)
        elif m := _TAG_RE.match(line):
            yield Token(TokenType.TAG, m.group(1), lineno, raw)
        else:
            first_word = line.split()[0].lower().rstrip("que").rstrip()
            if first_word in _KEYWORD_MAP or line.split()[0].lower() in _KEYWORD_MAP:
                yield Token(TokenType.STEP, line, lineno, raw)
            else:
                yield Token(TokenType.UNKNOWN, line, lineno, raw)


# ---------------------------------------------------------------------------
# DSL Validator
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    line_no: int
    message: str
    severity: str = "error"   # error | warning


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    def add_error(self, line_no: int, msg: str) -> None:
        self.errors.append(ValidationError(line_no, msg, "error"))
        self.valid = False

    def add_warning(self, line_no: int, msg: str) -> None:
        self.warnings.append(ValidationError(line_no, msg, "warning"))


def validate_dsl(source: str) -> ValidationResult:
    """Valida o DSL antes de qualquer execução. Obrigatório conforme diretrizes arquiteturais."""
    result = ValidationResult(valid=True)
    tokens = list(tokenize(source))

    has_flow     = any(t.type == TokenType.FLOW_DEF for t in tokens)
    has_scenario = any(t.type == TokenType.SCENARIO_DEF for t in tokens)
    has_steps    = any(t.type == TokenType.STEP for t in tokens)

    if not has_flow:
        result.add_error(0, "Nenhuma definição @flow encontrada no DSL.")
    if not has_scenario:
        result.add_error(0, "Nenhuma definição @scenario encontrada no DSL.")
    if not has_steps:
        result.add_error(0, "Nenhum step (Dado/Quando/Então) encontrado no DSL.")

    # Check step order within each scenario
    in_scenario = False
    last_step_type: StepType | None = None
    for t in tokens:
        if t.type == TokenType.SCENARIO_DEF:
            in_scenario = True
            last_step_type = None
        elif t.type == TokenType.STEP and in_scenario:
            kw = t.value.split()[0].lower()
            step_type = _KEYWORD_MAP.get(kw)
            if step_type == StepType.THEN and last_step_type == StepType.GIVEN:
                result.add_warning(t.line_no, "Nenhum step 'Quando' antes de 'Então' — verifique o flow.")
            if step_type:
                last_step_type = step_type

    # Unknown tokens
    for t in tokens:
        if t.type == TokenType.UNKNOWN:
            result.add_warning(t.line_no, f"Linha não reconhecida: '{t.value[:50]}'")

    return result


# ---------------------------------------------------------------------------
# DSL Parser  (tokens → Flow AST)
# ---------------------------------------------------------------------------

def _extract_parameters(text: str) -> dict[str, str]:
    """Extrai parâmetros entre aspas do step text."""
    params = _PARAM_RE.findall(text)
    return {f"param_{i}": v for i, v in enumerate(params)}


def _resolve_step_type(keyword: str, last_type: StepType | None) -> StepType:
    """Resolve 'E' e 'Mas' para o tipo do step anterior."""
    kw = keyword.lower()
    mapped = _KEYWORD_MAP.get(kw)
    if mapped == StepType.AND:
        return last_type or StepType.GIVEN
    return mapped or StepType.GIVEN


def _keyword_from_text(text: str) -> StepKeyword:
    first = text.split()[0]
    mapping = {
        "Dado": StepKeyword.DADO,
        "Quando": StepKeyword.QUANDO,
        "Então": StepKeyword.ENTAO,
        "Entao": StepKeyword.ENTAO,
        "E": StepKeyword.E,
        "Mas": StepKeyword.MAS,
    }
    return mapping.get(first, StepKeyword.E)


class DSLParser:
    """Converte source DSL em Flow (AST semântica)."""

    def parse(self, source: str) -> Flow:
        validation = validate_dsl(source)
        if not validation.valid:
            msgs = "; ".join(e.message for e in validation.errors)
            raise DSLParseError(f"DSL inválido: {msgs}")

        tokens = list(tokenize(source))
        meta   = self._extract_meta(tokens)
        flow   = self._build_flow(tokens, meta)
        return flow

    def parse_file(self, path: str | Path) -> Flow:
        return self.parse(Path(path).read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    def _extract_meta(self, tokens: list[Token]) -> dict[str, str]:
        meta: dict[str, str] = {}
        for t in tokens:
            if t.type == TokenType.META:
                k, _, v = t.value.partition("=")
                meta[k.strip().lower()] = v.strip()
        return meta

    def _build_flow(self, tokens: list[Token], meta: dict[str, str]) -> Flow:
        flow_name      = next((t.value for t in tokens if t.type == TokenType.FLOW_DEF), "UnnamedFlow")
        adapter_raw    = meta.get("adapter", "robot-framework")
        requirement    = meta.get("requirement", "")
        priority_raw   = meta.get("priority", "MEDIUM").upper()

        try:
            adapter = AdapterType(adapter_raw)
        except ValueError:
            adapter = AdapterType.ROBOT

        try:
            priority = Priority[priority_raw]
        except KeyError:
            priority = Priority.MEDIUM

        scenarios: list[Scenario] = []
        current_scenario: Scenario | None = None
        last_step_type: StepType | None = None

        for token in tokens:
            if token.type == TokenType.SCENARIO_DEF:
                if current_scenario:
                    scenarios.append(current_scenario)
                current_scenario = Scenario(
                    name=token.value,
                    requirement_ref=requirement,
                )
                last_step_type = None

            elif token.type == TokenType.STEP and current_scenario is not None:
                text    = token.value
                kw_str  = text.split()[0]
                s_type  = _resolve_step_type(kw_str, last_step_type)
                last_step_type = s_type

                step = SemanticStep(
                    keyword=_keyword_from_text(text),
                    step_type=s_type,
                    text=text,
                    parameters=_extract_parameters(text),
                    raw_line=token.raw,
                )
                current_scenario.steps.append(step)

            elif token.type == TokenType.TAG and current_scenario is not None:
                tag = token.value
                if tag not in ("flow", "scenario"):
                    current_scenario.tags.append(tag)

        if current_scenario:
            scenarios.append(current_scenario)

        return Flow(
            name=flow_name,
            requirement_ref=requirement,
            adapter=adapter,
            priority=priority,
            scenarios=scenarios,
            metadata=meta,
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DSLParseError(Exception):
    """Raised when the DSL fails validation or parsing."""
