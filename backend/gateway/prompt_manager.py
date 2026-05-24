"""
AQuA-QE LKDF — Fase 2
Prompt Management System: versionamento, templates, auditoria, 10 tipos §27
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid, hashlib, json


# ──────────────────────────────────────────────
# Tipos de Prompt (§27 — 10 tipos)
# ──────────────────────────────────────────────

class PromptType(str, Enum):
    ELICITATION       = "elicitation"
    REQUIREMENT_ENG   = "requirement_engineering"
    RTM               = "rtm"
    LKDF_GENERATION   = "lkdf_generation"
    WCAG              = "wcag"
    COVERAGE          = "coverage"
    INFERENCE         = "inference"
    RISK_ANALYSIS     = "risk_analysis"
    ARTIFACT_GEN      = "artifact_generation"
    COMPLIANCE        = "compliance"


# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────

class PromptVersion(BaseModel):
    version: int
    content: str
    system: Optional[str] = None
    variables: dict[str, str] = {}         # {name: description}
    changelog: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "system"
    hash: str = ""

    def model_post_init(self, __context: Any):
        if not self.hash:
            self.hash = hashlib.sha256(self.content.encode()).hexdigest()[:12]


class PromptTemplate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    prompt_type: PromptType
    description: str
    tags: list[str] = []
    versions: list[PromptVersion] = []
    active_version: int = 1
    usage_count: int = 0
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def current(self) -> Optional[PromptVersion]:
        for v in self.versions:
            if v.version == self.active_version:
                return v
        return self.versions[-1] if self.versions else None

    def render(self, variables: dict[str, str] = {}) -> str:
        """Renderiza o prompt ativo substituindo variáveis."""
        if not self.current:
            return ""
        content = self.current.content
        for k, v in variables.items():
            content = content.replace("{{" + k + "}}", v)
        return content

    def add_version(self, content: str, system: str = "", changelog: str = "", variables: dict = {}) -> PromptVersion:
        next_v = max((v.version for v in self.versions), default=0) + 1
        pv = PromptVersion(version=next_v, content=content, system=system,
                           variables=variables, changelog=changelog)
        self.versions.append(pv)
        self.active_version = next_v
        self.updated_at = datetime.utcnow()
        return pv


class PromptExecutionLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    template_id: str
    template_name: str
    prompt_type: PromptType
    version_used: int
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    success: bool = True
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────
# Prompt Library — Templates padrão AQuA-QE
# ──────────────────────────────────────────────

SYSTEM_BASE = """Você é o AQuA-QE LKDF — plataforma cognitiva de engenharia de qualidade.
Responda sempre em português brasileiro. Seja técnico, preciso e estruturado.
Siga rigorosamente o padrão: RN-XX para regras de negócio e CA-XX para critérios de aceite."""

PROMPT_LIBRARY: list[PromptTemplate] = []

def _add(name, ptype, desc, content, system=SYSTEM_BASE, tags=None, variables=None):
    t = PromptTemplate(name=name, prompt_type=ptype, description=desc, tags=tags or [])
    t.add_version(content=content, system=system, variables=variables or {})
    PROMPT_LIBRARY.append(t)

# 1. ELICITATION
_add(
    name="Elicitação Guiada de Requisitos",
    ptype=PromptType.ELICITATION,
    desc="Elicita requisitos de forma estruturada através de perguntas guiadas",
    tags=["elicitação", "requisitos", "guiado"],
    variables={"input": "história ou contexto a elicitar", "domain": "domínio do sistema"},
    content="""## 🎯 Elicitation Engine — AQuA-QE

Analise o seguinte input e execute elicitação estruturada:

**Input:** {{input}}
**Domínio:** {{domain}}

Realize as seguintes etapas:

### 1. Contextualização
Identifique: atores, sistema, domínio, objetivo de negócio.

### 2. Perguntas de Elicitação
Gere perguntas nas categorias:
- **Contexto**: Qual o ambiente de uso? Quem são os usuários?
- **Regras**: Quais restrições existem? Quais políticas se aplicam?
- **Integrações**: Com quais sistemas se integra?
- **Riscos**: O que pode dar errado? Quais são os cenários críticos?
- **Critérios de Aceite**: Como sabemos que está pronto?
- **Requisitos Não Funcionais**: Performance, segurança, disponibilidade?

### 3. Hipóteses Identificadas
Liste as hipóteses que precisam de validação.

### 4. Gaps Identificados
O que não foi informado e precisa ser esclarecido?

Ao final, pergunte: **"Deseja continuar o refinamento ou avançar para análise final?"**"""
)

# 2. REQUIREMENT ENGINEERING
_add(
    name="Engenharia de Requisitos — História Completa",
    ptype=PromptType.REQUIREMENT_ENG,
    desc="Analisa história de usuário e extrai RN, CA, riscos e cenários",
    tags=["requisitos", "história", "RN", "CA"],
    variables={"user_story": "história de usuário completa", "context": "contexto adicional"},
    content="""## 🧠 Requirement Intelligence Engine

**História de Usuário:**
{{user_story}}

**Contexto adicional:** {{context}}

Execute análise completa seguindo a arquitetura LKDF:

### 📋 Regras de Negócio (RN)
Liste todas as regras identificadas:
- RN-01: [descrição]
- RN-02: [descrição]
(continue conforme necessário)

### ✅ Critérios de Aceite (CA)
Para cada RN, defina critérios verificáveis:
- CA-01 (RN-01): [critério em formato: Dado/Quando/Então]
- CA-02 (RN-01): [critério adicional]

### ⚠️ Ambiguidades Detectadas
Liste termos vagos, inconsistências ou informações conflitantes.

### 🔗 Fluxo LKDF (Gherkin)
```gherkin
Funcionalidade: [nome]
  Como [ator]
  Quero [ação]
  Para [benefício]

  Cenário: [nome do cenário principal]
    Dado que [precondição]
    Quando [ação do usuário]
    Então [resultado esperado]
    E [resultado adicional]
```

### 📊 Casos de Teste (CT)
Padrão obrigatório: CT-XXX - RN-XX | CA-XX: Descrição
```rtm
CT-001|RN-01|CA-01|[descrição]|Alto|Nenhum|Alta|Sim
CT-002|RN-01|CA-02|[descrição]|Médio|[gap se houver]|Média|Sim
```

### 📈 Quality Score
Estimativa de cobertura: [X]%
Gaps identificados: [lista]"""
)

# 3. RTM
_add(
    name="Geração RTM Completa",
    ptype=PromptType.RTM,
    desc="Gera Requirement Traceability Matrix completa a partir de análise",
    tags=["RTM", "rastreabilidade", "LKDF"],
    variables={"analysis": "análise prévia de requisitos", "scope": "escopo do sistema"},
    content="""## 📊 Traceability Engine — RTM Vivo

**Análise Base:**
{{analysis}}

**Escopo:** {{scope}}

Gere a RTM completa seguindo o fluxo LKDF:
`RN → CA → Flow → Scenario → CT → Execução`

### Estrutura RTM
Para cada requisito identificado, gere linha no formato:
```rtm
[ID]|[RN]|[CA]|[Descrição do Caso]|[Risco: Alto/Médio/Baixo]|[Gap ou Nenhum]|[Prioridade: Alta/Média/Baixa]|[Automatizável: Sim/Não]
```

### Análise de Cobertura
- **Cobertura funcional**: [%]
- **Cobertura de risco**: [%]
- **Automatizável**: [%]
- **Gaps críticos**: [lista]

### Impacto e Dependências
Mapeie dependências entre casos de teste e identifique cadeia de impacto."""
)

# 4. LKDF GENERATION
_add(
    name="Geração LKDF — POM → FLOW → SCENARIO → TEST",
    ptype=PromptType.LKDF_GENERATION,
    desc="Gera artefatos na arquitetura LKDF completa",
    tags=["LKDF", "POM", "flow", "scenario", "robot"],
    variables={"requirements": "requisitos analisados", "framework": "framework alvo (robot/playwright/cypress)"},
    content="""## ⚙️ LKDF Artifact Generation Engine

**Requisitos:** {{requirements}}
**Framework:** {{framework}}

Gere os artefatos seguindo a arquitetura em camadas:

### 🏗️ POM Layer (Page Object Model)
```
Elementos, locators e abstrações técnicas necessárias.
Adapters para o framework {{framework}}.
```

### 🔄 Flow Layer (DSL Semântica)
```gherkin
# Flows reutilizáveis em Gherkin executável
Dado que [precondição de flow]
Quando [ação de flow]
Então [resultado de flow]
```

### 🎭 Scenario Layer (Orquestração)
```
Composição de flows.
Parametrização com datasets.
Comportamento orientado a dados.
```

### 🧪 Test Layer (Execução)
Gere código executável para {{framework}} com:
- Parametrização de datasets
- Integração CI/CD ready
- Tags para organização (smoke, regression, e2e)"""
)

# 5. WCAG
_add(
    name="Análise WCAG 2.1 AA",
    ptype=PromptType.WCAG,
    desc="Analisa conformidade WCAG 2.1 nível AA para interfaces",
    tags=["WCAG", "acessibilidade", "compliance", "a11y"],
    variables={"component": "componente ou tela a analisar", "level": "nível WCAG (A/AA/AAA)"},
    content="""## ♿ WCAG Compliance Engine

**Componente/Tela:** {{component}}
**Nível alvo:** {{level}}

Analise conformidade WCAG 2.1 nos 4 princípios POUR:

### 1. Perceptível (Perceivable)
- Alternativas de texto para conteúdo não-textual
- Legendas e alternativas para multimídia
- Adaptabilidade de apresentação
- Distinguibilidade (contraste, tamanho, espaçamento)

### 2. Operável (Operable)
- Acessibilidade por teclado (sem armadilhas)
- Tempo suficiente para interação
- Navegação e foco visível
- Modalidades de entrada alternativas

### 3. Compreensível (Understandable)
- Legibilidade do conteúdo
- Previsibilidade de comportamento
- Assistência para erros de entrada

### 4. Robusto (Robust)
- Compatibilidade com tecnologias assistivas
- ARIA roles e atributos corretos
- Semântica HTML adequada

### 📊 Resultado
Para cada critério violado:
- **Critério**: [número WCAG]
- **Nível**: A / AA / AAA
- **Problema**: [descrição]
- **Solução**: [como corrigir]
- **Impacto**: Alto / Médio / Baixo

### Casos de Teste WCAG
```rtm
CT-W01|WCAG-1.1.1|CA-W01|[descrição do teste]|Alto|Nenhum|Alta|Sim
```"""
)

# 6. COVERAGE
_add(
    name="Análise de Cobertura Multidimensional",
    ptype=PromptType.COVERAGE,
    desc="Valida cobertura funcional, técnica, de risco e compliance",
    tags=["cobertura", "coverage", "caixa-preta", "caixa-branca"],
    variables={"feature": "funcionalidade a analisar", "existing_tests": "testes existentes"},
    content="""## 🎯 Coverage Validation Engine

**Funcionalidade:** {{feature}}
**Testes existentes:** {{existing_tests}}

Analise cobertura nas dimensões:

### ⬛ Caixa Preta (Black Box)
- Particionamento de equivalência
- Análise de valor limite
- Tabela de decisão
- Transição de estados
- Casos de uso

### ⬜ Caixa Branca (White Box)
- Cobertura de statements
- Cobertura de branches
- Cobertura de caminhos
- Cobertura de condições

### 🔲 Caixa Cinza (Gray Box)
- Integração de componentes
- Fluxos de dados entre camadas
- Contratos de API

### 🌐 Dimensões Especiais
- **Responsividade**: mobile, tablet, desktop
- **Performance**: tempo de resposta, carga
- **Segurança**: OWASP Top 10 aplicáveis
- **WCAG**: acessibilidade

### 📊 Relatório de Cobertura
| Dimensão | Cobertura | Gaps | Ação |
|----------|-----------|------|------|
| Funcional | [%] | [gaps] | [ação] |
| Risco | [%] | [gaps] | [ação] |
| Compliance | [%] | [gaps] | [ação] |"""
)

# 7. INFERENCE
_add(
    name="Inferência de Cenários Ocultos",
    ptype=PromptType.INFERENCE,
    desc="Infere cenários implícitos, fluxos alternativos e testes ocultos",
    tags=["inferência", "cenários ocultos", "fluxos alternativos"],
    variables={"context": "contexto e requisitos analisados"},
    content="""## 🔍 Inference Engine

**Contexto:** {{context}}

Infira cenários não explicitados:

### 🌊 Fluxos Alternativos
Identifique todos os caminhos alternativos ao fluxo principal:
- O que acontece se [condição alternativa]?
- Quais são os pontos de decisão não documentados?

### ❌ Cenários de Exceção
- Dados inválidos / nulos / vazios
- Timeout / lentidão / falha de rede
- Usuário sem permissão
- Sessão expirada
- Concorrência (dois usuários simultâneos)
- Limite de capacidade atingido

### 🔗 Dependências Implícitas
- Pré-condições não documentadas
- Dados necessários não especificados
- Integrações assumidas mas não descritas

### 🧪 Testes Implícitos Sugeridos
Para cada cenário inferido:
```rtm
CT-I01|RN-inf|CA-inf|[cenário inferido]|[risco]|[origem da inferência]|Alta|Sim
```

### 💡 Insights de Qualidade
O que o analista provavelmente esqueceu ou assumiu?"""
)

# 8. RISK ANALYSIS
_add(
    name="Análise e Classificação de Riscos",
    ptype=PromptType.RISK_ANALYSIS,
    desc="Classifica riscos por criticidade, impacto e probabilidade",
    tags=["risco", "criticidade", "impacto", "priorização"],
    variables={"feature": "funcionalidade a analisar", "domain": "domínio (financeiro/saúde/etc)"},
    content="""## ⚠️ Risk Engine — Análise de Riscos

**Funcionalidade:** {{feature}}
**Domínio:** {{domain}}

### Matriz de Risco
Para cada risco identificado:

| ID | Risco | Probabilidade | Impacto | Criticidade | Mitigação |
|----|-------|--------------|---------|-------------|-----------|
| R-01 | [descrição] | Alta/Média/Baixa | Alto/Médio/Baixo | 🔴/🟡/🟢 | [ação] |

### Categorias de Risco

**🔴 Riscos Críticos (Alto × Alto)**
- Riscos que podem causar falha catastrófica
- Requerem teste obrigatório

**🟡 Riscos Relevantes (Médio)**
- Riscos que podem degradar experiência
- Requerem teste prioritário

**🟢 Riscos Baixos**
- Riscos com impacto controlável
- Teste recomendado

### Casos de Teste por Risco
```rtm
CT-R01|RN-01|CA-01|[teste cobrindo risco R-01]|Alto|Nenhum|Alta|Sim
```

### Recomendações de Priorização
Ordene os casos de teste por criticidade × cobertura de risco."""
)

# 9. ARTIFACT GENERATION
_add(
    name="Geração de Artefatos Multi-Framework",
    ptype=PromptType.ARTIFACT_GEN,
    desc="Gera artefatos executáveis para Robot, Playwright, Cypress, Postman",
    tags=["artefato", "robot", "playwright", "cypress", "postman"],
    variables={"test_cases": "casos de teste RTM", "framework": "framework alvo", "gherkin": "cenários Gherkin"},
    content="""## ⚙️ Artifact Generation Engine

**Casos de Teste:** {{test_cases}}
**Framework:** {{framework}}
**Gherkin:** {{gherkin}}

Gere código executável e production-ready para {{framework}}:

### Estrutura de Arquivo
- Header com metadados AQuA-QE
- Imports e configurações
- Setup / Teardown
- Casos de teste com tags
- Keywords/funções reutilizáveis
- Parametrização com datasets

### Padrões Obrigatórios
- Comentários rastreando CT-XXX
- Tags: @smoke, @regression, @e2e
- data-testid para seletores (não XPath)
- Assertions descritivas
- Tratamento de erros

### CI/CD Integration
- Configuração para GitHub Actions / Jenkins
- Reports HTML
- Threshold de cobertura: 80%

Gere código limpo, idiomático e com boas práticas do {{framework}}."""
)

# 10. COMPLIANCE
_add(
    name="Compliance Engine — LGPD / OWASP / ISO",
    ptype=PromptType.COMPLIANCE,
    desc="Analisa conformidade com LGPD, OWASP Top 10, ISO 27001 e compliance corporativo",
    tags=["compliance", "LGPD", "OWASP", "ISO", "segurança"],
    variables={"feature": "funcionalidade a analisar", "data_types": "tipos de dados tratados"},
    content="""## 🔒 Compliance Engine

**Funcionalidade:** {{feature}}
**Dados tratados:** {{data_types}}

### 🇧🇷 LGPD (Lei 13.709/2018)
Analise:
- Base legal para tratamento dos dados
- Finalidade, necessidade e adequação
- Direitos dos titulares (acesso, correção, exclusão, portabilidade)
- Medidas de segurança e sigilo
- Transferência internacional de dados
- DPO e relatório de impacto (DPIA)

**Itens não conformes:**
| Artigo LGPD | Descrição | Criticidade | Ação |
|-------------|-----------|-------------|------|

### 🛡️ OWASP Top 10
Verifique exposição para:
- A01: Broken Access Control
- A02: Cryptographic Failures
- A03: Injection
- A04: Insecure Design
- A05: Security Misconfiguration
- A06: Vulnerable Components
- A07: Auth Failures
- A08: Software Integrity Failures
- A09: Logging Failures
- A10: SSRF

### 📋 ISO 27001 (controles aplicáveis)
Controles relevantes para o contexto.

### 🧪 Casos de Teste de Compliance
```rtm
CT-C01|LGPD-Art7|CA-C01|[teste de conformidade]|Alto|Nenhum|Alta|Sim
```"""
)


# ──────────────────────────────────────────────
# Prompt Manager
# ──────────────────────────────────────────────

class PromptManager:
    """Gerenciador centralizado de prompts do AQuA-QE."""

    def __init__(self):
        self.templates: dict[str, PromptTemplate] = {}
        self.execution_logs: list[PromptExecutionLog] = []
        self._load_library()

    def _load_library(self):
        for t in PROMPT_LIBRARY:
            self.templates[t.id] = t

    # ── CRUD ────────────────────────────────

    def list_templates(self, prompt_type: PromptType | None = None) -> list[PromptTemplate]:
        templates = list(self.templates.values())
        if prompt_type:
            templates = [t for t in templates if t.prompt_type == prompt_type]
        return sorted(templates, key=lambda t: t.prompt_type)

    def get_template(self, template_id: str) -> PromptTemplate | None:
        return self.templates.get(template_id)

    def get_by_type(self, prompt_type: PromptType) -> PromptTemplate | None:
        for t in self.templates.values():
            if t.prompt_type == prompt_type:
                return t
        return None

    def create_template(self, name: str, prompt_type: PromptType, description: str,
                        content: str, system: str = SYSTEM_BASE,
                        tags: list[str] = [], variables: dict = {}) -> PromptTemplate:
        t = PromptTemplate(name=name, prompt_type=prompt_type,
                           description=description, tags=tags)
        t.add_version(content=content, system=system, variables=variables)
        self.templates[t.id] = t
        return t

    def add_version(self, template_id: str, content: str,
                    changelog: str = "", variables: dict = {}) -> PromptVersion | None:
        t = self.templates.get(template_id)
        if not t:
            return None
        return t.add_version(content=content, changelog=changelog, variables=variables)

    def render(self, template_id: str, variables: dict[str, str] = {}) -> tuple[str, str]:
        """Retorna (system_prompt, user_prompt) renderizados."""
        t = self.templates.get(template_id)
        if not t or not t.current:
            return (SYSTEM_BASE, "")
        system = t.current.system or SYSTEM_BASE
        content = t.render(variables)
        t.usage_count += 1
        return (system, content)

    def render_by_type(self, prompt_type: PromptType, variables: dict[str, str] = {}) -> tuple[str, str]:
        t = self.get_by_type(prompt_type)
        if not t:
            return (SYSTEM_BASE, f"Execute análise de {prompt_type.value}: {variables.get('input','')}")
        return self.render(t.id, variables)

    # ── Logging ─────────────────────────────

    def log_execution(self, template_id: str, provider: str, model: str,
                      input_tokens: int, output_tokens: int,
                      latency_ms: float, cost_usd: float, success: bool = True):
        t = self.templates.get(template_id)
        if not t:
            return
        log = PromptExecutionLog(
            template_id=template_id,
            template_name=t.name,
            prompt_type=t.prompt_type,
            version_used=t.active_version,
            provider=provider, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=latency_ms, cost_usd=cost_usd, success=success,
        )
        self.execution_logs.insert(0, log)
        if len(self.execution_logs) > 200:
            self.execution_logs.pop()
        # Update averages
        logs = [l for l in self.execution_logs if l.template_id == template_id]
        t.avg_latency_ms = sum(l.latency_ms for l in logs) / len(logs)
        t.avg_cost_usd   = sum(l.cost_usd for l in logs) / len(logs)

    def get_logs(self, template_id: str | None = None, limit: int = 50) -> list[PromptExecutionLog]:
        logs = self.execution_logs
        if template_id:
            logs = [l for l in logs if l.template_id == template_id]
        return logs[:limit]

    def get_stats(self) -> dict:
        total = len(self.execution_logs)
        by_type: dict[str, int] = {}
        for log in self.execution_logs:
            k = log.prompt_type.value
            by_type[k] = by_type.get(k, 0) + 1
        most_used = sorted(self.templates.values(), key=lambda t: t.usage_count, reverse=True)
        return {
            "total_executions": total,
            "total_templates": len(self.templates),
            "by_type": by_type,
            "most_used": [{"name": t.name, "type": t.prompt_type, "count": t.usage_count}
                          for t in most_used[:5]],
        }


# Singleton
prompt_manager = PromptManager()
