# AQuA-QE LKDF v1.4

> **Layered Keyword-Driven Framework** — Plataforma cognitiva de Quality Engineering ponta-a-ponta.

[![CI](https://github.com/dufelizardo/aqua_qe_lkdf/actions/workflows/ci.yml/badge.svg)](https://github.com/dufelizardo/aqua_qe_lkdf/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Tests](https://img.shields.io/badge/tests-581%20passing-brightgreen)
![Lint](https://img.shields.io/badge/ruff-passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-lightgrey)


<!-- Visitor badges: unique visitors & page views -->
![](https://komarev.com/ghpvc/?username=dufelizardo&repo=aqua_qe_lkdf&color=blue)
[![](https://komarev.com/ghpvc/?username=dufelizardo&repo=aqua_qe_lkdf&label=Visitors&color=0e75b6&style=flat)](https://github.com/dufelizardo/aqua_qe_lkdf)

---

## O que é

O LKDF transforma requisitos em linguagem natural em testes executáveis, com rastreabilidade bidirecional e conformidade WCAG — sem configuração manual de locators, sem scripts frágeis.

```
Requisito → Cognitive Engine → Flow DSL → Execution → Evidências → RTM → Quality Gates
```

---

## Instalação rápida

```bash
git clone https://github.com/dufelizardo/aqua_qe_lkdf.git
cd aqua_qe_lkdf
pip install -e ".[dev]"
playwright install chromium
pytest tests/unit/        # 581 testes passando
uvicorn runtime_core.api:app --port 8080 --reload
```

**Variáveis de ambiente** (`.env`):
```
ANTHROPIC_API_KEY=sk-ant-...     # Obrigatório para IA cognitiva
LKDF_DB_URL=sqlite+aiosqlite:///./data/lkdf.db
```

---

## Primeiro Flow

Crie um arquivo `.lkdf` com DSL semântico em português:

```
# Flow: LoginFlow
# Requirement: REQ-001
# Adapter: playwright

@flow LoginFlow
  @scenario ValidLogin
    Dado que o usuário está na página de login
    Quando o usuário insere "user@empresa.com" no campo email
    E o usuário insere "senha123" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que seja redirecionado para o dashboard
```

Execute:
```bash
lkdf run --dsl flows/login.lkdf --adapter playwright
```

---

## Arquitetura

```
aqua_qe_lkdf/
├── runtime_core/          # Runtime — DSL, Execution, Adapters, Persistence
│   ├── parser/            # DSL Parser (Tokenizer → AST → Validator)
│   ├── semantic_engine/   # Intent Resolver (30 padrões semânticos)
│   ├── execution_engine/  # State Machine + Fan-Out Pipeline async
│   ├── adapters/          # Playwright · Selenium · Cypress · API · Robot
│   ├── persistence/       # GraphRepository (SQLite → Neo4j plug-in)
│   ├── story_lifecycle/   # Versionamento DEF/IMP/REG · Diff · P0/P1/P2
│   ├── quality_policy/    # 12 Quality Gates configuráveis
│   ├── accessibility/     # WCAG 2.1/2.2 · axe-core · Nielsen
│   ├── evidence_engine/   # RTM · Traceability · Screenshots
│   └── api.py             # FastAPI gateway
├── ai_engine/             # Camada cognitiva
│   ├── gateway/           # AI Gateway: Claude · OpenAI · Gemini · Ollama
│   ├── requirement_agent/ # Análise semântica de requisitos
│   ├── scenario_agent/    # Geração cognitiva de cenários
│   ├── ambiguity_engine/  # Detecção de ambiguidades (6 tipos)
│   └── knowledge/         # Memória organizacional · Aprendizado
├── shared/                # Contratos de domínio
├── frontend/              # React/Next.js 14 · Dashboard · DSL Editor · RTM
└── tests/                 # 581 testes unitários + integração + acceptance
```

### Camadas e responsabilidades

| Camada | Responsabilidade | Tecnologia |
|--------|-----------------|------------|
| **DSL Layer** | Parseia texto semântico em Flow Python | Tokenizer próprio |
| **Semantic Layer** | Mapeia steps para intent + action | IntentResolver |
| **Execution Layer** | Orquestra execução via State Machine | Python async |
| **Adapter Layer** | Traduz actions para browser/API/CLI | playwright-python, httpx |
| **Persistence Layer** | Grafo de conhecimento (Node/Edge) | SQLAlchemy async |
| **Cognitive Layer** | IA para análise, geração e aprendizado | Claude / AI Gateway |
| **Quality Layer** | Gates P0/P1/P2, WCAG, RTM | Python puro |

---

## Adapters disponíveis

| Adapter | Quando usar |
|---------|-------------|
| `playwright` | Testes E2E de UI — recomendado (auto-wait, trace, multi-browser) |
| `selenium` | Selenium Grid, ambientes corporativos, browsers legacy |
| `cypress` | Times que já usam Cypress — gera `.cy.ts` e executa via Node |
| `api` | Testes REST/GraphQL sem browser — httpx + 18 assertion operators |
| `robot-framework` | Compatibilidade com suítes Robot Framework existentes |

---

## AI Engine

```python
# Pipeline cognitivo completo
pipeline = CognitivePipeline()
result = await pipeline.run(
    "Usuário bloqueado não deve acessar sistema",
    requirement_id="REQ-007",
)
# result.flow           → Flow pronto para ExecutionEngine
# result.all_scenarios  → original + IA + segurança
# result.coverage_score → estimativa de cobertura

# Detecção de ambiguidades
analyzer = AmbiguityAnalyzer()
report = await analyzer.analyze("O usuário deve ser redirecionado para o dashboard")
# report.critical_count   → ambiguidades que bloqueiam implementação correta
# report.business_rules   → regras extraídas implicitamente
```

---

## Quality Gates

O Quality Policy Engine avalia 12 gates configuráveis por módulo. Gates mandatórios incluem:

- **WCAG AA** — 100% de conformidade (bloqueia release)
- **No P0 Defects** — zero defects críticos abertos
- **Acceptance Criteria** — toda story com ≥1 critério definido
- **Bidirectional Traceability** — Requirement ↔ Test ↔ Evidence

```python
engine = PolicyEngine(repository)
report = await engine.evaluate_story("BFTG-127", context)
# report.passed           → True/False
# report.blocking_failures → gates que bloquearam
```

---

## CI/CD

Pipeline GitHub Actions com 5 jobs sequenciais:

```
Lint (27s) → Unit Tests (34s) → Integration Tests (24s) → MVP Acceptance (21s) → Docker Build (38s)
```

**Requisitos do CI:**
- `ANTHROPIC_API_KEY` como GitHub Secret (para integration tests)

---

## Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
```

Páginas: Dashboard · Flows Editor (Monaco) · Executions · RTM · Cognitive Engine · Accessibility · Knowledge · Settings

---

## Comandos úteis

```bash
# Testes
pytest tests/unit/ -v
pytest tests/unit/ --cov=runtime_core --cov-report=term-missing

# Lint
ruff check runtime_core/ ai_engine/ shared/ tests/
ruff check runtime_core/ ai_engine/ shared/ tests/ --fix

# Type check
mypy -p runtime_core -p ai_engine -p shared --ignore-missing-imports

# CLI
lkdf run --dsl flows/login.lkdf --adapter playwright
lkdf analyze "requisito em linguagem natural"
lkdf validate --dsl flows/login.lkdf
lkdf --help

# Docker
docker build -f infrastructure/Dockerfile.runtime -t lkdf-runtime .
docker run -p 8080:8080 lkdf-runtime
```

---

## Documentação completa

O documento Word `AQuA_QE_LKDF_README.docx` contém a documentação completa de onboarding e arquitetura, incluindo:

- Guia de instalação passo a passo
- Referência completa do DSL semântico
- Arquitetura detalhada de cada módulo
- ADRs (Architecture Decision Records)
- Referência de todos os endpoints FastAPI
- Guia para adicionar novos adapters

---

*AQuA-QE LKDF v1.4 — Cognitive Enterprise Blueprint · Maio 2026*
