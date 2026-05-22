# AQuA-QE LKDF — Layered Keyword-Driven Framework

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14.2+-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**AQuA-QE LKDF** is a cognitive quality and testing platform that combines **Keyword-Driven Testing**, **Semantic DSL**, **Generative AI**, and **Requirements Traceability** in a single ecosystem.

> 🇵🇹 **Available in Portuguese**: [README-pt.md](README-pt.md)

---

## 📋 Overview

AQuA-QE (Adaptive Quality Automation - QE) LKDF offers a revolutionary approach to test automation:

- **🔑 Keyword-Driven Framework**: Semantic DSL inspired by Gherkin, 100% readable for non-technical stakeholders
- **🧠 Cognitive Engine**: Generative AI that analyzes requirements, generates test scenarios, and detects ambiguities
- **🔄 Multi-Adapter**: Supports Selenium, Playwright, Cypress, Robot Framework, and APIs (REST/GraphQL)
- **📊 Complete Traceability**: Automatic RTM (Requirement Traceability Matrix), bidirectional linkage between requirements and tests
- **♿ Accessibility & WCAG**: Automatic validation (WCAG 2.1, Axe-core, Nielsen)
- **🚀 Execution Pipeline**: Real-time streaming, dry-run, automatic retry
- **📦 Modular & Extensible**: Layered architecture with customizable plugins

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LKDF Frontend (Next.js)                  │
│                    UI for DSL, Flows, RTM, etc                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST/WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                  FastAPI Runtime Core (Python)                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  DSL Parser │  │ Execution    │  │ Evidence Engine        │  │
│  │  & Validator│  │ Engine       │  │ & Traceability (RTM)   │  │
│  └─────────────┘  └──────────────┘  └────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │           AI Engine (Cognitive Layer)                    │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ • RequirementAgent (Claude)      — Requirement Analysis  │   │
│  │ • ScenarioAgent (Claude)         — Scenario Generation   │   │
│  │ • AmbiguityEngine (NLP)          — Ambiguity Detection   │   │
│  │ • KnowledgeLayer (Qdrant+LLM)    — Context Aware         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Adapter Layer (Multi-Framework Support)          │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ • Robot Framework   • Selenium   • Playwright            │   │
│  │ • Cypress          • REST API   • GraphQL                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │    Accessibility Engine (WCAG, Axe, Nielsen)             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    Selenium/       Playwright/Robot      API Contracts
    Chromium       Browser Automation
```

### Key Components

#### 1. **Parser Engine** (`runtime-core/parser`)
- Tokenizer and validator of semantic DSL based on Gherkin
- Extraction of metadata (requirements, adapters, tags, priorities)
- Generation of Abstract Syntax Tree (AST) for execution

#### 2. **Execution Engine** (`runtime-core/execution_engine`)
- Test orchestrator (parallel/sequential)
- Real-time result streaming (Server-Sent Events)
- Automatic retry, timeouts, and state rollback
- Dry-run support

#### 3. **AI Engine** (`ai_engine`)
- **RequirementAgent**: Analyzes requirements in natural language, generates test scenarios, and identifies gaps
- **ScenarioAgent**: Automatic extension with edge cases, security, concurrency scenarios
- **AmbiguityEngine**: Detection and resolution of ambiguities using NLP
- **KnowledgeLayer**: Semantic storage with Qdrant + embeddings

#### 4. **Adapters** (`runtime-core/adapters`)
- **Selenium/Playwright/Cypress**: UI automation
- **Robot Framework**: Integration with existing Robot suites
- **REST/GraphQL APIs**: Backend testing

#### 5. **Evidence & RTM** (`runtime-core/evidence_engine`)
- Automatic evidence collection (screenshots, logs, requests)
- Requirement Traceability Matrix (RTM) bidirectional
- Requirements coverage tracking

#### 6. **Accessibility Suite** (`runtime-core/accessibility`)
- WCAG 2.1 validation (levels A, AA, AAA)
- Axe-core integration for accessibility analysis
- Nielsen heuristics for UX

---

## 🚀 Quick Start

### Requirements

- **Python 3.12+**
- **Node.js 18+** (for frontend)
- **Docker** (optional, for infrastructure)

### Backend Installation

```bash
# Clone the repository
git clone https://github.com/dufelizardo/aqua_qe_lkdf.git
cd aqua_qe_lkdf

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[ai]"  # Install with AI (Claude, Qdrant)
# or
pip install -e .        # Core only

# Run the server
python -m runtime_core.api
# or
uvicorn runtime_core.api:app --reload --host 0.0.0.0 --port 8080
```

**Server running at**: `http://localhost:8080`

**Swagger Docs**: `http://localhost:8080/docs`

### Frontend Installation

```bash
cd frontend

# Install dependencies
npm install

# Run in development
npm run dev
```

**Frontend running at**: `http://localhost:3000`

---

## 📖 Usage Guide

### 1. Create a Flow in DSL

```gherkin
@flow Buy Product
@adapter playwright
@requirement REQ-USER-001

@scenario User successfully buys product
@priority high
@tags Smoke, E2E

# Setup
Given user is logged in as "customer@example.com"
Given product "MacBook Pro" is in stock with price "2499.99"

# Action
When user searches for "MacBook Pro"
And clicks "Add to Cart"
And proceeds to checkout

# Validation
Then order is confirmed successfully
And order appears in order history
And confirmation email is sent
And checkout page meets WCAG AA accessibility
```

### 2. Parse & Validation (REST API)

```bash
curl -X POST http://localhost:8080/flows/parse \
  -H "Content-Type: application/json" \
  -d '{
    "source": "@flow Buy Product\n...",
    "validate_only": false
  }'
```

**Response**:
```json
{
  "valid": true,
  "flow_name": "Buy Product",
  "scenarios": 1,
  "steps": 6,
  "warnings": [],
  "flow": { /* AST */ }
}
```

### 3. Execute a Flow

```bash
curl -X POST http://localhost:8080/flows/execute \
  -H "Content-Type: application/json" \
  -d '{
    "source": "@flow Buy Product\n...",
    "context": {
      "base_url": "https://ecommerce.example.com",
      "adapter": "playwright"
    }
  }'
```

**Response**:
```json
{
  "execution_id": "exec-uuid-12345",
  "status": "running",
  "message": "Execution started for 'Buy Product' — 1 scenarios."
}
```

### 4. Get Execution Result

```bash
curl http://localhost:8080/flows/execute/exec-uuid-12345
```

**Response**:
```json
{
  "execution_id": "exec-uuid-12345",
  "status": "passed",
  "flow_name": "Buy Product",
  "scenarios": [
    {
      "name": "User successfully buys product",
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

### 5. Analyze Requirement with AI

```bash
curl -X POST http://localhost:8080/requirements/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "requirement_text": "The system must allow users to login with email and password, with 2FA validation.",
    "requirement_id": "REQ-AUTH-001"
  }'
```

**Response**:
```json
{
  "requirement_id": "REQ-AUTH-001",
  "interpreted_intent": "Secure authentication with 2FA support",
  "business_rules": [
    {
      "description": "Credential validation",
      "entities": ["User", "Email", "Password"],
      "conditions": ["Valid email", "Password > 8 chars"],
      "outcomes": ["Token generated", "Session started"]
    }
  ],
  "ambiguities": [
    "Type of 2FA (SMS, Email, Authenticator App)?"
  ],
  "gaps": [
    "Failed login handling (attempt limit)?",
    "Account recovery?"
  ],
  "suggested_scenarios": [
    "Login with valid email and password",
    "Login with 2FA via SMS",
    "Login with invalid email (should reject)",
    "5 failed attempts limit"
  ],
  "risk_level": "high",
  "generated_flow_dsl": "@flow Authentication with 2FA\n..."
}
```

### 6. Access Requirements Traceability Matrix

```bash
curl http://localhost:8080/rtm
```

---

## 🔌 API Endpoints

### Health & Status
- `GET /health` - Server health check

### DSL Parser
- `POST /flows/parse` - Parse and validate DSL
- `GET /flows/{id}` - Get Flow by ID

### Execution
- `POST /flows/execute` - Start execution (async)
- `GET /flows/execute/{execution_id}` - Get execution report
- `POST /flows/execute/stream` - Execution with SSE streaming

### Cognitive Engine
- `POST /requirements/analyze` - Requirement analysis with AI
- `POST /scenarios/generate` - Automatic scenario generation

### Traceability
- `GET /rtm` - Requirement Traceability Matrix
- `GET /rtm/coverage` - Coverage report

### Configuration
- `GET /config` - Get runtime configuration
- `POST /config` - Update configuration

---

## 📁 Project Structure

```
aqua_qe_lkdf/
├── ai_engine/                          # Cognitive engine
│   ├── requirement_agent/              # Requirement analysis (Claude)
│   ├── scenario_agent/                 # Scenario generation (Claude)
│   ├── ambiguity_engine/               # Ambiguity detection (NLP)
│   ├── knowledge/                      # Knowledge Layer (Qdrant)
│   │   ├── facade.py
│   │   ├── memory/                     # Memory store
│   │   ├── learning/                   # Learning engine
│   │   ├── ontology/                   # Domain ontologies
│   │   └── suggestions/                # Suggestion engine
│   └── gateway/                        # AI gateway (Claude API)
│
├── runtime-core/                       # Execution core
│   ├── parser/                         # DSL Parser & Validator
│   ├── execution_engine/               # Execution orchestrator
│   ├── scenario_engine/                # Scenario composition
│   ├── semantic_engine/                # Semantic resolution
│   ├── context_engine/                 # Execution context
│   ├── assertion_engine/               # Validations
│   ├── evidence_engine/                # Evidence collection & RTM
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
│   │   │   ├── rtm/                    # Requirements Traceability
│   │   │   ├── accessibility/          # Accessibility reports
│   │   │   ├── knowledge/              # Knowledge base
│   │   │   └── settings/               # Configuration
│   │   └── components/                 # Reusable components
│   ├── package.json
│   └── tsconfig.json
│
├── shared/                             # Shared models
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

## 🔧 Configuration

### Environment Variables

Create `.env` file:

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

## 🧪 Testing

```bash
# Run all tests
pytest

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# With coverage
pytest --cov=runtime_core --cov=ai_engine --cov-report=html

# Specific tests
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

### Docker Compose (with Qdrant)

```bash
docker-compose -f infrastructure/docker-compose.yml up -d
```

---

## 📚 Complete Examples

### Example 1: User Login

```gherkin
@flow User Authentication
@adapter playwright
@requirement REQ-AUTH-001
@tags smoke, authentication

@scenario Login with valid credentials
@priority high

Given user accesses login page
And form is visible and accessible (WCAG AA)

When enters email "user@example.com"
And enters password "SecurePassword123"
And clicks "Sign In"

Then home page is displayed
And user name appears in menu
And session is persisted in localStorage
And all accessibility validations pass

@scenario Login attempt limit
@priority medium

Given user is on login page

When tries to login with wrong password 5 times
And waits 1 second between attempts

Then account is temporarily blocked
And warning message is displayed
```

### Example 2: E2E Flow with Dynamic Data

```gherkin
@flow Shopping Cart
@adapter playwright
@requirement REQ-CART-001, REQ-CART-002
@tags critical, e2e

@scenario Add multiple products and proceed to payment
@priority high
@data-source inventory-api

Given user is logged in as premium
And has a delivery address registered

When iterates over [3] products in stock
  And clicks "Add to Cart" for each
  And validates product appears in cart

Then subtotal is correct
And shipping is automatically calculated
And checkout page is accessible
And clicks "Complete Purchase"

Then payment is processed
And confirmation email is sent
And order appears in history
```

---

## 🤝 Contributing

```bash
# 1. Fork the repository
# 2. Create a feature branch
git checkout -b feature/my-feature

# 3. Commit your changes
git commit -m "feat: clear description of the change"

# 4. Push to branch
git push origin feature/my-feature

# 5. Open a Pull Request
```

### Code Standards

- Python: PEP 8 + type hints (validated with `mypy`)
- Ruff for linting: `ruff check .`
- Formatting: Ruff + Black
- TypeScript: ESLint + Prettier

```bash
# Validate and format code
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

## 📞 Support & Community

- **Issues**: [GitHub Issues](https://github.com/dufelizardo/aqua_qe_lkdf/issues)
- **Discussions**: [GitHub Discussions](https://github.com/dufelizardo/aqua_qe_lkdf/discussions)
- **Email**: support@aqua-qe.com

---

## 📜 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- Claude AI for cognitive analysis capability
- FastAPI for excellent framework
- Next.js for modern UI
- Qdrant for vector storage
- Open-source testing community

---

**Made with ❤️ for QA Engineers who want to work smarter.**

*AQuA-QE LKDF © 2024-2026 | Adaptive Quality Automation*

