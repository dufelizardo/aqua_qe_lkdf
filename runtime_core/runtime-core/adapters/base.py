"""
runtime_core/adapters/base.py
AQuA-QE LKDF — Base Adapter Contract

Define a interface universal que todos os adapters devem implementar.
Garante independência de framework conforme diretriz arquitetural.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from shared.models import AdapterType, RuntimeContext


class BaseAdapter(ABC):
    """
    Contrato universal do Adapter Layer.
    Qualquer framework (Robot, Playwright, Cypress, API) deve implementar esta interface.
    Nenhuma lógica de negócio pode depender de um adapter específico.
    """

    adapter_type: AdapterType

    @abstractmethod
    async def setup(self, context: RuntimeContext) -> None:
        """Inicializa o adapter para uma sessão de execução."""

    @abstractmethod
    async def teardown(self, context: RuntimeContext) -> None:
        """Finaliza e limpa recursos do adapter."""

    @abstractmethod
    async def execute_action(
        self,
        action: str,
        parameters: dict[str, Any],
        context: RuntimeContext,
    ) -> Any:
        """
        Executa uma action mapeada pelo Intent Resolver.
        Deve lançar AssertionError em falhas de assertion.
        Deve lançar AdapterError em falhas técnicas.
        """

    @abstractmethod
    async def collect_evidence(self, context: RuntimeContext) -> list[str]:
        """Coleta evidências (screenshots, logs) e retorna caminhos dos artefatos."""

    @abstractmethod
    async def take_screenshot(self, context: RuntimeContext, name: str) -> str:
        """Captura screenshot e retorna o caminho do arquivo."""

    def supports_action(self, action: str) -> bool:
        """Verifica se o adapter suporta uma action específica."""
        return action in self._action_registry()

    def _action_registry(self) -> set[str]:
        """Retorna o conjunto de actions suportadas. Override nos adapters."""
        return set()


class AdapterError(Exception):
    """Raised when an adapter fails to execute an action."""

    def __init__(self, action: str, message: str) -> None:
        self.action = action
        super().__init__(f"[{action}] {message}")
