"""
ai_engine/knowledge/ontology/registry.py
AQuA-QE LKDF v1.4 — Domain Ontology Registry

Catálogo de conceitos de domínio com relacionamentos semânticos.
Permite que o sistema:
  - Reconheça entidades em requisitos sem treinamento explícito
  - Enriqueça análises com contexto de domínio
  - Sugira conceitos relacionados ao analisar um requisito
  - Construa grafo de conhecimento semântico progressivamente
"""
from __future__ import annotations


from ai_engine.knowledge.models import OntologyNode


# ---------------------------------------------------------------------------
# Ontology Registry
# ---------------------------------------------------------------------------

class OntologyRegistry:
    """
    Registro de conceitos de domínio com busca semântica.
    Alimentado por seeds de domínio e enriquecido via aprendizado.
    """

    def __init__(self) -> None:
        self._concepts: dict[str, OntologyNode] = {}
        self._seed_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, node: OntologyNode) -> None:
        key = node.concept.lower()
        self._concepts[key] = node
        for alias in node.aliases:
            self._concepts[alias.lower()] = node

    def register_many(self, nodes: list[OntologyNode]) -> None:
        for node in nodes:
            self.register(node)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def find(self, query: str) -> OntologyNode | None:
        return self._concepts.get(query.lower())

    def match_in_text(self, text: str) -> list[OntologyNode]:
        """Encontra todos os conceitos mencionados em um texto."""
        found: list[OntologyNode] = []
        seen:  set[str]           = set()
        text_lower = text.lower()

        for concept, node in self._concepts.items():
            if concept in text_lower and node.concept not in seen:
                found.append(node)
                seen.add(node.concept)

        return found

    def related_to(self, concept: str) -> list[OntologyNode]:
        """Retorna conceitos relacionados."""
        node = self.find(concept)
        if not node:
            return []
        return [
            self._concepts[r.lower()]
            for r in node.related_to
            if r.lower() in self._concepts
        ]

    def domain_concepts(self, domain: str) -> list[OntologyNode]:
        seen: set[str] = set()
        result: list[OntologyNode] = []
        for node in self._concepts.values():
            if node.domain == domain and node.concept not in seen:
                result.append(node)
                seen.add(node.concept)
        return result

    def infer_domain(self, text: str) -> str:
        """Infere o domínio principal de um texto pelo matching de conceitos."""
        matches = self.match_in_text(text)
        if not matches:
            return "general"
        domain_freq: dict[str, int] = {}
        for m in matches:
            if m.domain:
                domain_freq[m.domain] = domain_freq.get(m.domain, 0) + 1
        return max(domain_freq, key=lambda d: domain_freq[d]) if domain_freq else "general"

    def all_concepts(self) -> list[OntologyNode]:
        seen: set[str] = set()
        result: list[OntologyNode] = []
        for node in self._concepts.values():
            if node.concept not in seen:
                result.append(node)
                seen.add(node.concept)
        return result

    # ------------------------------------------------------------------
    # Seed — conceitos padrão por domínio
    # ------------------------------------------------------------------

    def _seed_defaults(self) -> None:
        nodes = [
            # ── Authentication ────────────────────────────────────────
            OntologyNode(concept="Autenticação",
                aliases=["authentication", "login", "autenticar", "sign in"],
                domain="authentication",
                description="Processo de verificação de identidade do usuário.",
                related_to=["Sessão", "Token", "Credenciais", "Autorização"]),
            OntologyNode(concept="Credenciais",
                aliases=["credentials", "usuário e senha", "login e senha"],
                domain="authentication",
                related_to=["Autenticação", "Senha"]),
            OntologyNode(concept="Token",
                aliases=["jwt", "access token", "refresh token", "bearer"],
                domain="authentication",
                description="Token de acesso para autenticação stateless.",
                related_to=["Autenticação", "Sessão", "Expiração"]),
            OntologyNode(concept="Sessão",
                aliases=["session", "sessão ativa", "logged in"],
                domain="authentication",
                related_to=["Token", "Autenticação", "Logout"]),
            OntologyNode(concept="Logout",
                aliases=["sair", "sign out", "encerrar sessão"],
                domain="authentication",
                related_to=["Sessão", "Token"]),

            # ── Authorization ─────────────────────────────────────────
            OntologyNode(concept="Autorização",
                aliases=["authorization", "permissão", "acesso", "rbac"],
                domain="authorization",
                description="Controle do que um usuário autenticado pode fazer.",
                related_to=["Papel", "Recurso", "Autenticação"]),
            OntologyNode(concept="Papel",
                aliases=["role", "perfil", "admin", "viewer", "editor"],
                domain="authorization",
                related_to=["Autorização", "Permissão"]),
            OntologyNode(concept="Permissão",
                aliases=["permission", "direito", "acl"],
                domain="authorization",
                related_to=["Papel", "Autorização"]),

            # ── Payments ──────────────────────────────────────────────
            OntologyNode(concept="Pagamento",
                aliases=["payment", "pagar", "cobrança", "charge"],
                domain="payments",
                description="Transação financeira de cobrança.",
                related_to=["Gateway", "Cartão", "PIX", "Boleto", "Estorno"]),
            OntologyNode(concept="Gateway",
                aliases=["payment gateway", "adquirente", "stripe", "cielo"],
                domain="payments",
                related_to=["Pagamento", "Timeout"]),
            OntologyNode(concept="Estorno",
                aliases=["refund", "reembolso", "chargeback", "cancelamento"],
                domain="payments",
                related_to=["Pagamento", "Gateway"]),
            OntologyNode(concept="Checkout",
                aliases=["finalizar compra", "finalização", "carrinho"],
                domain="payments",
                related_to=["Pagamento", "Pedido"]),

            # ── Forms & Validation ────────────────────────────────────
            OntologyNode(concept="Formulário",
                aliases=["form", "form de cadastro", "formulário de"],
                domain="forms",
                description="Componente de coleta de dados do usuário.",
                related_to=["Validação", "Campo", "Submit"]),
            OntologyNode(concept="Validação",
                aliases=["validation", "validar", "verificar", "checar"],
                domain="forms",
                related_to=["Formulário", "Campo", "Erro"]),
            OntologyNode(concept="Campo",
                aliases=["field", "input", "campo de texto", "campo obrigatório"],
                domain="forms",
                related_to=["Formulário", "Validação"]),

            # ── Notifications ─────────────────────────────────────────
            OntologyNode(concept="Notificação",
                aliases=["notification", "alerta", "aviso", "push", "email"],
                domain="notifications",
                description="Comunicação assíncrona ao usuário.",
                related_to=["Email", "SMS", "Push"]),
            OntologyNode(concept="Email",
                aliases=["e-mail", "correio eletrônico", "smtp"],
                domain="notifications",
                related_to=["Notificação"]),

            # ── Data ──────────────────────────────────────────────────
            OntologyNode(concept="Banco de Dados",
                aliases=["database", "db", "banco", "sqlite", "postgres"],
                domain="data",
                related_to=["Query", "Migração", "Transação"]),
            OntologyNode(concept="Migração",
                aliases=["migration", "alembic", "schema change"],
                domain="data",
                related_to=["Banco de Dados"]),

            # ── API ───────────────────────────────────────────────────
            OntologyNode(concept="API",
                aliases=["rest api", "graphql", "endpoint", "serviço"],
                domain="api",
                description="Interface de programação para comunicação entre sistemas.",
                related_to=["Endpoint", "Payload", "Autenticação"]),
            OntologyNode(concept="Endpoint",
                aliases=["rota", "route", "path", "url da api"],
                domain="api",
                related_to=["API", "Método HTTP"]),

            # ── Accessibility ─────────────────────────────────────────
            OntologyNode(concept="Acessibilidade",
                aliases=["accessibility", "wcag", "a11y", "screen reader"],
                domain="accessibility",
                description="Conformidade WCAG e usabilidade para todos os usuários.",
                related_to=["WCAG", "Leitor de Tela", "Contraste"]),
            OntologyNode(concept="WCAG",
                aliases=["wcag 2.1", "wcag 2.2", "web content accessibility"],
                domain="accessibility",
                related_to=["Acessibilidade"]),
        ]

        for node in nodes:
            self.register(node)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_global_registry: OntologyRegistry | None = None


def get_ontology() -> OntologyRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = OntologyRegistry()
    return _global_registry
