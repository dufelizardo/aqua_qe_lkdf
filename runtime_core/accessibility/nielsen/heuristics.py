"""
runtime_core/accessibility/nielsen/heuristics.py
AQuA-QE LKDF v1.4 — Nielsen's 10 Usability Heuristics

Catálogo das 10 heurísticas de Nielsen com:
  - Descrição e critérios de avaliação
  - Modelo de violação com severidade (0-4)
  - Avaliador baseado em checklist
  - Integração com geração de cenários de UX
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HeuristicId(int, Enum):
    VISIBILITY_OF_SYSTEM_STATUS      = 1
    MATCH_BETWEEN_SYSTEM_AND_WORLD   = 2
    USER_CONTROL_AND_FREEDOM         = 3
    CONSISTENCY_AND_STANDARDS        = 4
    ERROR_PREVENTION                 = 5
    RECOGNITION_RATHER_THAN_RECALL   = 6
    FLEXIBILITY_AND_EFFICIENCY       = 7
    AESTHETIC_AND_MINIMALIST_DESIGN  = 8
    HELP_USERS_RECOGNIZE_ERRORS      = 9
    HELP_AND_DOCUMENTATION           = 10


class NielsenSeverity(int, Enum):
    """Escala de severidade de Nielsen (0-4)."""
    NOT_A_PROBLEM    = 0
    COSMETIC         = 1
    MINOR            = 2
    MAJOR            = 3
    USABILITY_CATASTROPHE = 4


# ---------------------------------------------------------------------------
# Heuristic definition
# ---------------------------------------------------------------------------

@dataclass
class Heuristic:
    id:          HeuristicId
    name:        str
    description: str
    examples:    list[str] = field(default_factory=list)
    checklist:   list[str] = field(default_factory=list)
    tags:        list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Heuristics catalog
# ---------------------------------------------------------------------------

HEURISTICS: dict[HeuristicId, Heuristic] = {
    HeuristicId.VISIBILITY_OF_SYSTEM_STATUS: Heuristic(
        id=HeuristicId.VISIBILITY_OF_SYSTEM_STATUS,
        name="Visibility of System Status",
        description="O sistema deve manter os usuários informados sobre o que está acontecendo, "
                    "por meio de feedback apropriado em tempo razoável.",
        examples=[
            "Indicador de carregamento (spinner) durante operações assíncronas",
            "Barra de progresso em uploads",
            "Confirmação visual após salvar",
            "Breadcrumbs indicando localização atual",
        ],
        checklist=[
            "Operações longas têm indicador de progresso?",
            "Feedback confirmado após ações do usuário (salvar, enviar)?",
            "Estado atual do sistema sempre visível?",
            "Mensagens de sucesso e erro claras e imediatas?",
        ],
        tags=["feedback", "loading", "progress", "status"],
    ),
    HeuristicId.MATCH_BETWEEN_SYSTEM_AND_WORLD: Heuristic(
        id=HeuristicId.MATCH_BETWEEN_SYSTEM_AND_WORLD,
        name="Match Between System and the Real World",
        description="O sistema deve usar palavras, frases e conceitos familiares ao usuário, "
                    "não jargão orientado ao sistema.",
        examples=[
            "Ícone de lixeira para deletar",
            "Ícone de casa para página inicial",
            "Linguagem do domínio do usuário, não técnica",
            "Ordenação natural e lógica das informações",
        ],
        checklist=[
            "Linguagem no vocabulário do usuário, não do sistema?",
            "Metáforas do mundo real usadas consistentemente?",
            "Datas e números no formato local?",
            "Terminologia consistente em toda a interface?",
        ],
        tags=["language", "metaphors", "localization"],
    ),
    HeuristicId.USER_CONTROL_AND_FREEDOM: Heuristic(
        id=HeuristicId.USER_CONTROL_AND_FREEDOM,
        name="User Control and Freedom",
        description="Usuários frequentemente escolhem funções por engano. "
                    "Precisam de 'saída de emergência' claramente marcada.",
        examples=[
            "Desfazer e Refazer",
            "Botão Cancelar em modais e formulários",
            "Confirmação antes de ações destrutivas",
            "Navegação para página anterior sempre disponível",
        ],
        checklist=[
            "Ações destrutivas têm confirmação?",
            "Undo/Redo disponível onde aplicável?",
            "Botão Cancelar em todos os formulários e modais?",
            "Saída clara de fluxos multi-etapa?",
        ],
        tags=["undo", "cancel", "freedom", "destructive-actions"],
    ),
    HeuristicId.CONSISTENCY_AND_STANDARDS: Heuristic(
        id=HeuristicId.CONSISTENCY_AND_STANDARDS,
        name="Consistency and Standards",
        description="Usuários não devem se perguntar se palavras, situações ou ações "
                    "diferentes significam a mesma coisa.",
        examples=[
            "Mesmo componente para mesma funcionalidade em todas as páginas",
            "Posição consistente de elementos de navegação",
            "Comportamento de botões primários/secundários consistente",
            "Convenções da plataforma respeitadas",
        ],
        checklist=[
            "Componentes similares têm comportamento idêntico?",
            "Terminologia consistente em toda a aplicação?",
            "Posição de elementos de navegação previsível?",
            "Padrões da plataforma/SO respeitados?",
        ],
        tags=["consistency", "standards", "patterns"],
    ),
    HeuristicId.ERROR_PREVENTION: Heuristic(
        id=HeuristicId.ERROR_PREVENTION,
        name="Error Prevention",
        description="Melhor que mensagens de erro é um design cuidadoso que previne problemas.",
        examples=[
            "Validação em tempo real de campos",
            "Desabilitar botão de submit até formulário válido",
            "Confirmação antes de ações irreversíveis",
            "Sugestões de autocompletar",
        ],
        checklist=[
            "Validação inline nos campos de formulário?",
            "Campos obrigatórios claramente marcados?",
            "Formato esperado indicado (ex: DD/MM/AAAA)?",
            "Ações irreversíveis têm aviso prévio?",
        ],
        tags=["validation", "prevention", "forms"],
    ),
    HeuristicId.RECOGNITION_RATHER_THAN_RECALL: Heuristic(
        id=HeuristicId.RECOGNITION_RATHER_THAN_RECALL,
        name="Recognition Rather Than Recall",
        description="Minimize a carga de memória do usuário tornando objetos, ações "
                    "e opções visíveis.",
        examples=[
            "Histórico de buscas recentes",
            "Sugestões de autocompletar baseadas em uso anterior",
            "Labels visíveis em campos (não apenas placeholder)",
            "Opções relevantes visíveis sem necessidade de memorização",
        ],
        checklist=[
            "Labels sempre visíveis (não apenas placeholder)?",
            "Opções disponíveis visíveis sem precisar memorizar?",
            "Histórico e sugestões onde relevante?",
            "Contexto mantido entre sessões onde apropriado?",
        ],
        tags=["memory", "recognition", "labels", "history"],
    ),
    HeuristicId.FLEXIBILITY_AND_EFFICIENCY: Heuristic(
        id=HeuristicId.FLEXIBILITY_AND_EFFICIENCY,
        name="Flexibility and Efficiency of Use",
        description="Aceleradores — invisíveis para o usuário novato — "
                    "podem acelerar a interação para o usuário expert.",
        examples=[
            "Atalhos de teclado para ações frequentes",
            "Personalização de fluxos de trabalho",
            "Bulk actions para operações repetidas",
            "Busca com filtros avançados",
        ],
        checklist=[
            "Atalhos de teclado disponíveis para ações frequentes?",
            "Usuários avançados têm atalhos que novatos não precisam ver?",
            "Operações repetitivas podem ser automatizadas?",
            "Busca e filtros avançados disponíveis?",
        ],
        tags=["shortcuts", "efficiency", "power-users"],
    ),
    HeuristicId.AESTHETIC_AND_MINIMALIST_DESIGN: Heuristic(
        id=HeuristicId.AESTHETIC_AND_MINIMALIST_DESIGN,
        name="Aesthetic and Minimalist Design",
        description="Diálogos não devem conter informações irrelevantes ou raramente necessárias.",
        examples=[
            "Remover campos desnecessários de formulários",
            "Hierarquia visual clara (primário, secundário, terciário)",
            "Espaço em branco para respiração visual",
            "Sem decoração que não agrega informação",
        ],
        checklist=[
            "Interface livre de informações irrelevantes?",
            "Hierarquia visual clara e consistente?",
            "Formulários têm apenas campos necessários?",
            "Espaço branco usado para organização?",
        ],
        tags=["minimalism", "visual-hierarchy", "clutter"],
    ),
    HeuristicId.HELP_USERS_RECOGNIZE_ERRORS: Heuristic(
        id=HeuristicId.HELP_USERS_RECOGNIZE_ERRORS,
        name="Help Users Recognize, Diagnose and Recover from Errors",
        description="Mensagens de erro em linguagem simples, indicando o problema "
                    "e sugerindo solução.",
        examples=[
            "\"Email inválido\" em vez de \"Erro 400\"",
            "Destacar o campo com erro",
            "Sugerir a correção: \"Você quis dizer usuario@empresa.com?\"",
            "Mensagens de erro próximas ao campo problemático",
        ],
        checklist=[
            "Mensagens de erro em linguagem humana?",
            "Campo problemático claramente identificado?",
            "Sugestão de correção fornecida?",
            "Sem códigos de erro técnicos expostos ao usuário?",
        ],
        tags=["errors", "recovery", "messages"],
    ),
    HeuristicId.HELP_AND_DOCUMENTATION: Heuristic(
        id=HeuristicId.HELP_AND_DOCUMENTATION,
        name="Help and Documentation",
        description="Embora o ideal seja um sistema sem necessidade de documentação, "
                    "pode ser necessário fornecer ajuda contextual.",
        examples=[
            "Tooltips em campos complexos",
            "Guia de primeiros passos",
            "FAQ contextual",
            "Documentação pesquisável",
        ],
        checklist=[
            "Ajuda contextual disponível onde necessário?",
            "Documentação fácil de pesquisar?",
            "Exemplos concretos fornecidos?",
            "Ajuda focada na tarefa do usuário?",
        ],
        tags=["help", "documentation", "onboarding"],
    ),
}


# ---------------------------------------------------------------------------
# Violation model
# ---------------------------------------------------------------------------

@dataclass
class NielsenViolation:
    """Violação de uma heurística de Nielsen detectada em um componente."""
    id:            UUID             = field(default_factory=uuid4)
    heuristic:     HeuristicId      = HeuristicId.VISIBILITY_OF_SYSTEM_STATUS
    severity:      NielsenSeverity  = NielsenSeverity.MAJOR
    component:     str              = ""
    page:          str              = ""
    description:   str              = ""
    recommendation: str             = ""
    checklist_item: str             = ""   # qual item do checklist foi violado
    evidence:      str              = ""   # screenshot path ou descrição
    metadata:      dict[str, Any]   = field(default_factory=dict)

    @property
    def heuristic_name(self) -> str:
        h = HEURISTICS.get(self.heuristic)
        return h.name if h else str(self.heuristic)

    @property
    def is_blocking(self) -> bool:
        return self.severity >= NielsenSeverity.MAJOR


# ---------------------------------------------------------------------------
# Checklist evaluator
# ---------------------------------------------------------------------------

@dataclass
class ChecklistResult:
    """Resultado de avaliação de um item do checklist."""
    heuristic:    HeuristicId
    item:         str
    passed:       bool
    notes:        str = ""


class NielsenEvaluator:
    """
    Avaliador baseado em checklist das heurísticas de Nielsen.
    Usado no Review Layer e na geração de cenários de UX.
    """

    def evaluate_checklist(
        self,
        heuristic_id: HeuristicId,
        answers: dict[str, bool],   # checklist_item → passed
    ) -> list[ChecklistResult]:
        """
        Avalia os itens do checklist de uma heurística.
        answers: mapeamento item → True (passou) / False (falhou)
        """
        heuristic = HEURISTICS.get(heuristic_id)
        if not heuristic:
            return []

        results: list[ChecklistResult] = []
        for item in heuristic.checklist:
            passed = answers.get(item, True)   # default: assume OK
            results.append(ChecklistResult(
                heuristic=heuristic_id,
                item=item,
                passed=passed,
            ))
        return results

    def score(
        self,
        heuristic_id: HeuristicId,
        answers: dict[str, bool],
    ) -> float:
        """Retorna score 0.0–1.0 para uma heurística (1.0 = todos passaram)."""
        results = self.evaluate_checklist(heuristic_id, answers)
        if not results:
            return 1.0
        return sum(1 for r in results if r.passed) / len(results)

    def score_all(self, answers: dict[HeuristicId, dict[str, bool]]) -> dict[str, float]:
        """Scores para todas as heurísticas."""
        return {
            h.id.name: self.score(h.id, answers.get(h.id, {}))
            for h in HEURISTICS.values()
        }

    def overall_score(self, answers: dict[HeuristicId, dict[str, bool]]) -> float:
        scores = self.score_all(answers)
        if not scores:
            return 1.0
        return sum(scores.values()) / len(scores)

    def violations_from_checklist(
        self,
        answers: dict[HeuristicId, dict[str, bool]],
        component: str = "",
        severity_map: dict[str, NielsenSeverity] | None = None,
    ) -> list[NielsenViolation]:
        """Gera violações para todos os itens que falharam."""
        violations: list[NielsenViolation] = []
        for heuristic_id, item_answers in answers.items():
            for item, passed in item_answers.items():
                if not passed:
                    sev = (severity_map or {}).get(item, NielsenSeverity.MAJOR)
                    violations.append(NielsenViolation(
                        heuristic=heuristic_id,
                        severity=sev,
                        component=component,
                        description=f"Checklist falhou: {item}",
                        recommendation=self._recommendation(heuristic_id, item),
                        checklist_item=item,
                    ))
        return violations

    @staticmethod
    def _recommendation(heuristic_id: HeuristicId, item: str) -> str:
        h = HEURISTICS.get(heuristic_id)
        if not h:
            return "Revise a heurística correspondente."
        # Match to example
        for example in h.examples:
            if any(kw in item.lower() for kw in example.lower().split()[:3]):
                return example
        return h.examples[0] if h.examples else "Consulte as diretrizes da heurística."
