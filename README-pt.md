# AQuA-QE LKDF — Layered Keyword-Driven Framework

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14.2+-black.svg)](https://nextjs.org/)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!-- Badges de visitantes: visitantes únicos & visualizações -->
[![Visitor Count](https://visitor-badge.laobi.icu/badge?page_id=dufelizardo.aqua_qe_lkdf)](https://github.com/dufelizardo/aqua_qe_lkdf)

**AQuA-QE LKDF** é uma plataforma cognitiva de qualidade e testes que combina **Keyword-Driven Testing**, **DSL Semântico**, **IA Generativa** e **Rastreabilidade de Requisitos** em um único ecossistema.

---

## 📋 Visão Geral

AQuA-QE (Adaptive Quality Automation - QE) LKDF oferece uma abordagem revolucionária para testes de automação:

- **🔑 Keyword-Driven Framework**: DSL semântico inspirado em Gherkin, 100% legível para stakeholders não-técnicos
- **🧠 Cognitive Engine**: IA generativa que analisa requisitos, gera cenários de teste e detecta ambiguidades
- **🔄 Multi-Adapter**: Suporta Selenium, Playwright, Cypress, Robot Framework e APIs (REST/GraphQL)
- **📊 Rastreabilidade Completa**: RTM (Requirement Traceability Matrix) automática, linkagem bidirecional entre requisitos e testes
- **♿ Acessibilidade & WCAG**: Validações automáticas de acessibilidade (WCAG 2.1, Axe-core, Nielsen)
- **🚀 Execution Pipeline**: Streaming em tempo real, dry-run, retry automático
- **📦 Modular & Extensível**: Arquitetura em camadas com plugins customizáveis

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        LKDF Frontend (Next.js)                  │
│                    UI para DSL, Flows, RTM, etc                │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST/WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                  FastAPI Runtime Core (Python)                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  DSL Parser │  │ Execution    │  │ Evidence Engine        │ │
│  │  & Validator│  │ Engine       │  │ & Traceability (RTM)   │ │
│  └─────────────┘  └──────────────┘  └────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │           AI Engine (Cognitive Layer)                   │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ • RequirementAgent (Claude)      — Análise de Requisitos│   │
│  │ • ScenarioAgent (Claude)         — Geração de Cenários  │   │
│  │ • AmbiguityEngine (NLP)          — Detecção de Ambig.   │   │
│  │ • KnowledgeLayer (Qdrant+LLM)    — Context Aware        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Adapter Layer (Multi-Framework Support)         │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ • Robot Framework   • Selenium   • Playwright           │   │
│  │ • Cypress          • REST API   • GraphQL               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │    Accessibility Engine (WCAG, Axe, Nielsen)            │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    Selenium/       Playwright/Robot      API Contracts
    Chromium       Browser Automation
```

### Componentes Principais

#### 1. **Parser Engine** (`runtime-core/parser`)
- Tokenizador e validador de DSL baseado em Gherkin semântico
- Extração de metadados (requirements, adapters, tags, prioridades)
- Geração de Abstract Syntax Tree (AST) para execução

#### 2. **Execution Engine** (`runtime-core/execution_engine`)
- Orquestrador de testes paralelos/sequenciais
- Streaming de resultados em tempo real (Server-Sent Events)
- Retry automático, timeouts, e rollback de estado
- Suporte a dry-run

#### 3. **AI Engine** (`ai_engine`)
- **RequirementAgent**: Analisa requisitos em linguagem natural, gera cenários de teste e identifica gaps
- **ScenarioAgent**: Extensão automática com edge cases, segurança, concorrência
- **AmbiguityEngine**: Detecção e resolução de ambiguidades utilizando NLP
- **KnowledgeLayer**: Armazenamento semântico com Qdrant + embeddings

#### 4. **Adapters** (`runtime-core/adapters`)
- **Selenium/Playwright/Cypress**: Automação de UI
- **Robot Framework**: Integração com suites Robot existentes
- **REST/GraphQL APIs**: Testes de backend

#### 5. **Evidence & RTM** (`runtime-core/evidence_engine`)
- Coleta automática de evidência (screenshots, logs, requests)
- Requirement Traceability Matrix (RTM) bidirecional
- Rastreamento de cobertura de requisitos

#### 6. **Accessibility Suite** (`runtime-core/accessibility`)
- Validação WCAG 2.1 (níveis A, AA, AAA)
- Axe-core integration para análises de acessibilidade
- Nielsen heuristics para UX

---

## 🚀 Quick Start

### Requisitos

- **Python 3.12+**
- **Node.js 18+** (para o frontend)
- **Docker** (opcional, para infrastructure)

### Instalação - Backend

```bash
# Clone o repositório
git clone https://github.com/dufelizardo/aqua_qe_lkdf.git
cd aqua_qe_lkdf

# Criar virtual environment
python -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate

# Instalar dependências
pip install -e ".[ai]"  # Instala com IA (Claude, Qdrant)
# ou
pip install -e .        # Apenas core

# Rodar o servidor
python -m runtime_core.api
# ou
uvicorn runtime_core.api:app --reload --host 0.0.0.0 --port 8080
```

**Servidor rodando em**: `http://localhost:8080`

**Swagger Docs**: `http://localhost:8080/docs`

### Instalação - Frontend

```bash
cd frontend

# Instalar dependências
npm install

# Rodar em desenvolvimento
npm run dev
```

**Frontend rodando em**: `http://localhost:3000`

---

## 📖 Guia de Uso

### 1. Criar um Flow na DSL

```gherkin
@flow Compra Produto
@adapter playwright
@requirement REQ-USER-001

@scenario Usuário compra produto com sucesso
@priority high
@tags Smoke, E2E

# Setup
Dado o usuário está logado como "customer@example.com"
Dado o produto "MacBook Pro" está em estoque com preço "2499.99"

# Ação
Quando o usuário busca por "MacBook Pro"
E clica em "Adicionar ao carrinho"
E procede para checkout

# Validação
Então o pedido é confirmado com sucesso
E a ordem aparece no histórico de pedidos
E um email de confirmação é enviado
E a acessibilidade da página de confirmação atende WCAG AA
```

### 2. Parse & Validação (API REST)

```bash
curl -X POST http://localhost:8080/flows/parse \
  -H "Content-Type: application/json" \
  -d '{
    "source": "@flow Compra Produto\n...",
    "validate_only": false
  }'
```

**Resposta**:
```json
{
  "valid": true,
  "flow_name": "Compra Produto",
  "scenarios": 1,
  "steps": 6,
  "warnings": [],
  "flow": { /* AST */ }
}
```

### 3. Executar um Flow

```bash
curl -X POST http://localhost:8080/flows/execute \
  -H "Content-Type: application/json" \
  -d '{
    "source": "@flow Compra Produto\n...",
    "context": {
      "base_url": "https://ecommerce.example.com",
      "adapter": "playwright"
    }
  }'
```

**Resposta**:
```json
{
  "execution_id": "exec-uuid-12345",
  "status": "running",
  "message": "Execução iniciada para 'Compra Produto' — 1 scenarios."
}
```

### 4. Obter Resultado de Execução

```bash
curl http://localhost:8080/flows/execute/exec-uuid-12345
```

**Resposta**:
```json
{
  "execution_id": "exec-uuid-12345",
  "status": "passed",
  "flow_name": "Compra Produto",
  "scenarios": [
    {
      "name": "Usuário compra produto com sucesso",
      "status": "passed",
      "duration_ms": 4523,
      "steps": [ /* step results */ ],
      "evidence": [ /* screenshots, logs */ ]
    }
  ],
  "total_duration_ms": 4523,
  "passed": 1,
  "failed": 0
}
```

### 5. Analisar Requisito com IA

```bash
curl -X POST http://localhost:8080/requirements/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "requirement_text": "O sistema deve permitir que usuários façam login com email e senha, com validação de 2FA.",
    "requirement_id": "REQ-AUTH-001"
  }'
```

**Resposta**:
```json
{
  "requirement_id": "REQ-AUTH-001",
  "interpreted_intent": "Autenticação segura com suporte a 2FA",
  "business_rules": [
    {
      "description": "Validação de credenciais",
      "entities": ["User", "Email", "Password"],
      "conditions": ["Email válido", "Password > 8 chars"],
      "outcomes": ["Token gerado", "Sessão iniciada"]
    }
  ],
  "ambiguities": [
    "Tipo de 2FA (SMS, Email, Authenticator App)?"
  ],
  "gaps": [
    "Tratamento de falha de login (limite de tentativas)?",
    "Recuperação de conta?"
  ],
  "suggested_scenarios": [
    "Login com email e senha válidos",
    "Login com 2FA via SMS",
    "Login com email invalido (deve rejeitar)",
    "Limite de 5 tentativas falhadas"
  ],
  "risk_level": "high",
  "generated_flow_dsl": "@flow Autenticação com 2FA\n..."
}
```

### 6. Acessar a Requirement Traceability Matrix

```bash
curl http://localhost:8080/rtm
```

---

## 🔌 API Endpoints

### Health & Status
- `GET /health` - Server health check

### DSL Parser
- `POST /flows/parse` - Parse e valida DSL
- `GET /flows/{id}` - Retorna Flow pelo ID

### Execution
- `POST /flows/execute` - Inicia execução (async)
- `GET /flows/execute/{execution_id}` - Obtém relatório de execução
- `POST /flows/execute/stream` - Execução com streaming SSE

### Cognitive Engine
- `POST /requirements/analyze` - Análise de requisito com IA
- `POST /scenarios/generate` - Geração automática de cenários

### Traceability
- `GET /rtm` - Requirement Traceability Matrix
- `GET /rtm/coverage` - Relatório de cobertura

### Configuration
- `GET /config` - Obter configuração do runtime
- `POST /config` - Atualizar configuração

---

## 📁 Estrutura do Projeto

```
aqua_qe_lkdf/
├── ai_engine/                          # Motor cognitivo
│   ├── requirement_agent/              # Análise de requisitos (Claude)
│   ├── scenario_agent/                 # Geração de cenários (Claude)
│   ├── ambiguity_engine/               # Detecção de ambiguidades (NLP)
│   ├── knowledge/                      # Knowledge Layer (Qdrant)
│   │   ├── facade.py
│   │   ├── memory/                     # Memory store
│   │   ├── learning/                   # Learning engine
│   │   ├── ontology/                   # Domain ontologies
│   │   └── suggestions/                # Suggestion engine
│   └── gateway/                        # Gateway para IA (Claude API)
│
├── runtime-core/                       # Core de execução
│   ├── parser/                         # DSL Parser & Validator
│   ├── execution_engine/               # Orquestrador de execução
│   ├── scenario_engine/                # Composição de cenários
│   ├── semantic_engine/                # Resolução semântica
│   ├── context_engine/                 # Contexto de execução
│   ├── assertion_engine/               # Validações
│   ├── evidence_engine/                # Coleta de evidência & RTM
│   ├── adapters/                       # Multi-framework support
│   │   ├── selenium/
│   │   ├── playwright/
│   │   ├── cypress/
│   │   ├── robot/
│   │   ├── api/
│   │   └── factory.py
│   ├── accessibility/                  # WCAG, Axe, Nielsen
│   ├── quality_policy/                 # Quality gates & policies
│   ├── persistence/                    # Database adapters
│   ├── pom_layer/                      # POM registry
│   ├── story_lifecycle/                # Story versioning & diffs
│   ├── pipeline/                       # Fanout pipeline
│   ├── api.py                          # FastAPI app
│   ├── cli.py                          # CLI entrypoint
│   └── execution_engine.py
│
├── frontend/                           # Next.js Frontend
│   ├── src/
│   │   ├── app/                        # Pages
│   │   │   ├── page.tsx                # Dashboard
│   │   │   ├── flows/                  # Flow management
│   │   │   ├── executions/             # Execution history
│   │   │   ├── rtm/                    # Requirement Traceability
│   │   │   ├── accessibility/          # Accessibility reports
│   │   │   ├── knowledge/              # Knowledge base
│   │   │   └── settings/               # Configuration
│   │   └── components/                 # Reusable components
│   ├── package.json
│   └── tsconfig.json
│
├── shared/                             # Modelos compartilhados
│   └── models.py                       # Pydantic models
│
├── infrastructure/                     # Docker & deployment
│   ├── Dockerfile.runtime
│   └── docker-compose.yml
│
├── tests/                              # Test suite
│   ├── unit/                           # Unit tests
│   └── integration/                    # Integration tests
│
├── pyproject.toml                      # Python dependencies
└── README.md                           # You are here!
```

---

## 🔧 Configuração

### Variáveis de Ambiente

Criar arquivo `.env`:

```env
# FastAPI
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=8080
FASTAPI_LOG_LEVEL=INFO

# AI Engine (Claude)
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-3-sonnet-20240229

# Vector Database (Qdrant)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your-qdrant-key

# Persistence (PostgreSQL)
DATABASE_URL=postgresql://user:pass@localhost/lkdf

# Adapters
SELENIUM_GRID_URL=http://localhost:4444
PLAYWRIGHT_HEADLESS=true
ROBOT_RUNNER=robot

# Accessibility
WCAG_LEVEL=AA
AXE_RUNNER_URL=http://localhost:8000

# Logging & Monitoring
LOG_FORMAT=json
SENTRY_DSN=https://...
```

---

## 🧪 Testes

```bash
# Executar todos os testes
pytest

# Somente unit tests
pytest tests/unit/

# Somente integration tests
pytest tests/integration/

# Com coverage
pytest --cov=runtime_core --cov=ai_engine --cov-report=html

# Testes específicos
pytest tests/unit/test_dsl_parser.py -v
```

---

## 🚢 Deployment

### Docker

```bash
# Build image
docker build -f infrastructure/Dockerfile.runtime -t aqua-qe-lkdf:latest .

# Run container
docker run -p 8080:8080 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e QDRANT_URL=http://qdrant:6333 \
  aqua-qe-lkdf:latest
```

### Docker Compose (com Qdrant)

```bash
docker-compose -f infrastructure/docker-compose.yml up -d
```

---

## 📚 Exemplos Completos

### Exemplo 1: Login de Usuário

```gherkin
@flow Autenticação de Usuário
@adapter playwright
@requirement REQ-AUTH-001
@tags smoke, authentication

@scenario Login com credenciais válidas
@priority high

Dado o usuário acessa a página de login
E o formulário está visível e acessível (WCAG AA)

Quando insere email "user@example.com"
E insere senha "SecurePassword123"
E clica em "Entrar"

Então a página inicial é exibida
E o nome do usuário aparece no menu
E a sessão é persistida em localStorage
E todas as validações de acessibilidade passam

@scenario Limite de tentativas de login
@priority medium

Dado o usuário está na página de login

Quando tenta fazer login com senha errada 5 vezes
E aguarda 1 segundo entre tentativas

Então a conta é bloqueada temporariamente
E uma mensagem de aviso é exibida
```

### Exemplo 2: Fluxo E2E com Dados Dinâmicos

```gherkin
@flow Carrinho de Compras
@adapter playwright
@requirement REQ-CART-001, REQ-CART-002
@tags critical, e2e

@scenario Adicionar múltiplos produtos e proceder ao pagamento
@priority high
@data-source inventory-api

Dado o usuário está logado como premium
E tem um endereço de entrega cadastrado

Quando itera sobre [3] produtos em estoque
  E clica em "Adicionar ao Carrinho" para cada
  E valida que o produto aparece no carrinho

Então o subtotal está correto
E o frete é calculado automaticamente
E a página de checkout está acessível
E clica em "Finalizar Compra"

Então o pagamento é processado
E um email de confirmação é enviado
E o pedido aparece no histórico
```

---

## 🤝 Contribuindo

```bash
# 1. Fork o repositório
# 2. Crie uma branch feature
git checkout -b feature/minha-feature

# 3. Commit suas mudanças
git commit -m "feat: descrição clara da mudança"

# 4. Push para a branch
git push origin feature/minha-feature

# 5. Abra um Pull Request
```

### Padrões de Código

- Python: PEP 8 + type hints (validado com `mypy`)
- Ruff para linting: `ruff check .`
- Formatação: Ruff + Black
- TypeScript: ESLint + Prettier

```bash
# Validar e formatar código
ruff check . --fix
mypy runtime_core ai_engine
```

---

## 📊 Roadmap

- [ ] v1.2: Persistent database (PostgreSQL)
- [ ] v1.3: Advanced analytics dashboard
- [ ] v1.4: Mobile automation support (Appium)
- [ ] v2.0: Multi-LLM support (GPT-4, Llama, etc.)
- [ ] v2.1: CI/CD integrations (GitHub Actions, Jenkins)
- [ ] v2.2: Performance testing engine
- [ ] v3.0: Distributed execution (Kubernetes)

---

## 📞 Suporte & Comunidade

- **Issues**: [GitHub Issues](https://github.com/dufelizardo/aqua_qe_lkdf/issues)
- **Discussions**: [GitHub Discussions](https://github.com/dufelizardo/aqua_qe_lkdf/discussions)
- **Email**: support@aqua-qe.com

---

## 📜 Licença

MIT License - veja [LICENSE](LICENSE) para detalhes.

---

## 🙏 Agradecimentos

- Claude AI por poder análise cognitiva
- FastAPI pela excelente framework
- Next.js pela UI moderna
- Qdrant pelo armazenamento vetorial
- Comunidade open-source de testes

---

**Feito com ❤️ para QA Engineers que querem trabalhar de forma inteligente.**

*AQuA-QE LKDF © 2024-2026 | Adaptive Quality Automation*

