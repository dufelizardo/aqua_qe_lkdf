"""
runtime_core/assertion_engine/assertions.py
AQuA-QE LKDF — Assertion Engine

Motor de validação condicional com suporte a:
  - Assertions de texto, URL, título, visibilidade
  - Assertions condicionais (soft assertions)
  - Assertion chains
  - Relatório de falhas com contexto semântico
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Assertion Result
# ---------------------------------------------------------------------------

@dataclass
class AssertionResult:
    passed: bool
    assertion_type: str
    expected: Any
    actual: Any = None
    message: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.passed


# ---------------------------------------------------------------------------
# Assertion Engine
# ---------------------------------------------------------------------------

class AssertionEngine:
    """
    Motor de assertions do LKDF.
    Suporta hard assertions (lançam exceção) e soft assertions (acumulam falhas).
    """

    def __init__(self, soft: bool = False) -> None:
        self.soft    = soft
        self._errors: list[AssertionResult] = []

    # ------------------------------------------------------------------
    # Core assertions
    # ------------------------------------------------------------------

    def assert_text_contains(self, page_content: str, expected: str) -> AssertionResult:
        passed = expected.lower() in page_content.lower()
        return self._emit(AssertionResult(
            passed=passed,
            assertion_type="text_contains",
            expected=expected,
            actual=page_content[:100],
            message=f"Texto '{expected}' {'encontrado' if passed else 'NÃO encontrado'} na página.",
        ))

    def assert_url_equals(self, actual_url: str, expected_url: str) -> AssertionResult:
        # Normalize trailing slashes
        passed = actual_url.rstrip("/") == expected_url.rstrip("/")
        return self._emit(AssertionResult(
            passed=passed,
            assertion_type="url_equals",
            expected=expected_url,
            actual=actual_url,
            message=f"URL {'correta' if passed else 'incorreta'}: esperado '{expected_url}', atual '{actual_url}'.",
        ))

    def assert_title(self, actual_title: str, expected_title: str) -> AssertionResult:
        passed = expected_title.lower() in actual_title.lower()
        return self._emit(AssertionResult(
            passed=passed,
            assertion_type="title",
            expected=expected_title,
            actual=actual_title,
            message=f"Título {'correto' if passed else 'incorreto'}.",
        ))

    def assert_element_visible(self, element_exists: bool, locator: str) -> AssertionResult:
        return self._emit(AssertionResult(
            passed=element_exists,
            assertion_type="element_visible",
            expected=True,
            actual=element_exists,
            message=f"Elemento '{locator}' {'visível' if element_exists else 'NÃO visível'}.",
        ))

    def assert_status_code(self, actual: int, expected: int = 200) -> AssertionResult:
        passed = actual == expected
        return self._emit(AssertionResult(
            passed=passed,
            assertion_type="status_code",
            expected=expected,
            actual=actual,
            message=f"Status code: esperado {expected}, recebido {actual}.",
        ))

    def assert_custom(
        self,
        predicate: Callable[[], bool],
        description: str,
        expected: Any = True,
    ) -> AssertionResult:
        try:
            passed = predicate()
        except Exception as exc:
            passed = False
            description = f"{description} (exception: {exc})"
        return self._emit(AssertionResult(
            passed=passed,
            assertion_type="custom",
            expected=expected,
            message=description,
        ))

    # ------------------------------------------------------------------
    # Soft assertion management
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Em modo soft: lança AssertionError com todos os erros acumulados."""
        if self._errors:
            msgs = "\n".join(f"  [{i+1}] {e.message}" for i, e in enumerate(self._errors))
            self._errors.clear()
            raise AssertionError(f"Múltiplas assertions falharam:\n{msgs}")

    @property
    def has_failures(self) -> bool:
        return bool(self._errors)

    @property
    def failure_count(self) -> int:
        return len(self._errors)

    # ------------------------------------------------------------------
    def _emit(self, result: AssertionResult) -> AssertionResult:
        if not result.passed:
            if self.soft:
                self._errors.append(result)
            else:
                raise AssertionError(result.message)
        return result
