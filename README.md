# AQuA-QE LKDF Platform

**Cognitive Quality Engineering Platform powered by AI**

AQuA-QE (AI-powered Quality Assurance) is a full-stack cognitive platform for software quality engineering. It combines a multi-provider AI Gateway, knowledge graph, RAG-based memory, compliance analysis, and rich frontend tooling — all designed around the **LKDF methodology** (Living Knowledge-Driven Framework).

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Backend Modules](#backend-modules)
- [API Reference](#api-reference)
- [Frontend Applications](#frontend-applications)
- [Configuration](#configuration)
- [Roadmap Status](#roadmap-status)

---

## Overview

### What It Does

AQuA-QE turns raw user stories and requirements into structured quality artifacts:

```
User Story → [AI Analysis] → RNs + CAs + RTM + Gherkin + Risk + Compliance Report
```

It maintains a **Living Knowledge Layer** — a continuously growing memory of patterns, requirements, and test cases extracted from every analysis session. This context is automatically injected into future prompts via **RAG** (Retrieval-Augmented Generation), making the AI progressively smarter about your domain.

### Key Features

| Feature | Description |
|---|---|
| **Multi-Provider AI Gateway** | Route prompts across Anthropic, OpenAI, Gemini, Groq, Mistral, Ollama, vLLM, LM Studio |
| **Streaming SSE** | Real-time token streaming from all providers |
| **RAG Architecture** | TF-IDF semantic search injects relevant context before every LLM call |
| **Knowledge Graph** | SQLite-based graph DB with Neo4j-compatible interface — nodes, relationships, BFS traversal |
| **AI Observability** | Latency percentiles (P50/P75/P95/P99), cost tracking, confidence scoring, trace logging |
| **AI Security** | PII detection (CPF, CNPJ, email, credit card, API keys), masking, LGPD-compliant audit log |
| **Compliance Engine** | WCAG 2.1, LGPD, OWASP Top 10, ISO 25010 automated checks |
| **Session History** | Full conversation persistence in SQLite with resume capability |
| **CI/CD Export** | Generate GitHub Actions, GitLab CI, JUnit XML, Robot Framework files from test cases |
| **WebSocket Events** | Real-time gateway stats, log streaming, knowledge updates |
| **Story Engineering** | Monaco Editor with custom language, version history, Gherkin/Robot tabs |
| **Workbench** | Cytoscape.js RTM graph, coverage heatmap, interactive traceability |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend Layer                       │
│  aqua-qe.html  │  gateway-panel  │  workbench           │
│  story-eng     │  observability  │  knowledge-explorer  │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP / SSE / WebSocket
┌────────────────────▼────────────────────────────────────┐
│              FastAPI Gateway (port 8080)                │
│                                                         │
│  /api/v1/analyze          /api/v1/analyze/stream        │
│  /api/v1/providers        /api/v1/routing               │
│  /api/v1/observability    /api/v1/security              │
│  /api/v1/knowledge        /api/v1/rag                   │
│  /api/v1/graph            /api/v1/compliance            │
│  /api/v1/sessions         /api/v1/cicd                  │
│  /ws/events               /ws/logs                      │
└───────┬──────────┬──────────┬──────────┬──────────┬─────┘
        │          │          │          │          │
     ┌──▼──┐   ┌───▼──┐  ┌────▼──┐   ┌───▼──┐   ┌───▼──┐
     │ AI  │   │ RAG  │  │Graph  │   │Secur │   │Comp  │
     │Gate │   │Engine│  │  DB   │   │  ity │   │liance│
     │ way │   │TF-IDF│  │SQLite │   │ PII  │   │Engine│
     └──┬──┘   └───┬──┘  └────┬──┘   └───┬──┘   └──────┘
        │          │          │          │
┌───────▼──────────▼──────────▼──────────▼────────────────┐
│                 SQLite Databases                        │
│  config/sessions.db   config/knowledge.db               │
│  config/graph.db      config/gateway.json               │
│  config/.env          (API keys — never committed)      │
└─────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│              AI Providers                               │
│  Cloud: Anthropic · OpenAI · Gemini · Groq · Mistral    │
│  Local: Ollama · vLLM · LM Studio · llama.cpp           │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Installation

```bash
# Clone the repo
git clone https://github.com/your-org/aqua-qe-lkdf.git
cd aqua-qe-lkdf/aqua-gateway

# Install dependencies
pip install -r requirements.txt

# Start the gateway
python main.py
```

The server starts at `http://localhost:8080`.

### Configure Your First Provider

```bash
# Option 1: via API
curl -X POST http://localhost:8080/api/v1/config/api-key \
  -H "Content-Type: application/json" \
  -d '{"provider": "anthropic", "api_key": "sk-ant-..."}'

# Option 2: via gateway-panel.html → Providers tab → enter key → Save
```

### Open the Chat

Open `frontend/aqua-qe.html` in your browser. Click **⚙️ Gateway** to verify connection.

---

## Backend Modules

### `backend/gateway/`

| Module | Description |
|---|---|
| `core.py` | `AIGateway` — main orchestrator, router, fallback logic |
| `config_manager.py` | Persists API keys (`.env`) and settings (`gateway.json`) across restarts |
| `session_manager.py` | SQLite CRUD for chat session history |
| `observability.py` | `ObservabilityManager` — P50/P95/P99 latency, cost aggregation, trace logging |
| `security.py` | `SecurityGateway` — PII detection/masking, audit log, policy engine |
| `knowledge.py` | `KnowledgeManager` — extracts and stores RNs, CAs, patterns from LLM responses |
| `rag.py` | `RAGEngine` — TF-IDF vector store, semantic search, prompt augmentation |
| `graph_db.py` | `GraphDB` — SQLite graph database, BFS traversal, Cytoscape/D3 export |
| `cicd.py` | `CICDExporter` — GitHub Actions, GitLab CI, JUnit XML, Robot Framework |
| `prompt_manager.py` | Versioned prompt templates for each cognitive engine |

### `backend/providers/`

| Module | Description |
|---|---|
| `registry.py` | Default config for all 10 providers (models, costs, context limits) |
| `adapters.py` | `AnthropicAdapter`, `OpenAICompatAdapter`, `OllamaAdapter`, `GeminiAdapter` — all with real SSE streaming |

### `backend/engines/`

| Module | Description |
|---|---|
| `advanced.py` | 7 cognitive engines: Risk, Coverage, Inference, Synthesis, Consistency, Impact, Compliance |
| `compliance_engine.py` | 20 rules across WCAG 2.1, LGPD, OWASP Top 10, ISO 25010 |

---

## API Reference

**Base URL:** `http://localhost:8080`

### Core Analysis

```
POST /api/v1/analyze              # Execute cognitive analysis
POST /api/v1/analyze/stream       # SSE streaming analysis
POST /api/v1/proxy/chat           # Direct provider proxy (avoids browser CORS)
```

### Providers & Routing

```
GET    /api/v1/providers                    # List all providers
PATCH  /api/v1/providers/{name}            # Update provider config/API key
POST   /api/v1/providers/{name}/health     # Health check
GET    /api/v1/routing                     # Get routing table
PUT    /api/v1/routing/{engine}            # Update engine routing
```

### Persistence

```
GET    /api/v1/config/status        # Config file status
POST   /api/v1/config/api-key       # Save API key to .env
GET    /api/v1/config/keys          # List configured providers
POST   /api/v1/config/snapshot      # Save full gateway state
```

### Sessions

```
GET    /api/v1/sessions             # List sessions (pagination + search)
POST   /api/v1/sessions             # Create session
GET    /api/v1/sessions/{id}        # Get full session (messages + RTM)
PATCH  /api/v1/sessions/{id}        # Update session (auto-save)
DELETE /api/v1/sessions/{id}        # Delete session
GET    /api/v1/sessions/stats/summary
```

### Observability

```
GET /api/v1/observability/summary
GET /api/v1/observability/by-provider
GET /api/v1/observability/by-engine
GET /api/v1/observability/hourly-trend
GET /api/v1/observability/traces
GET /api/v1/observability/latency-heatmap
GET /api/v1/observability/cost-breakdown
GET /api/v1/observability/confidence
```

### Security & Governance

```
GET    /api/v1/security/summary
POST   /api/v1/security/inspect        # PII detection + policy check
GET    /api/v1/security/audit          # Audit log (filterable)
GET    /api/v1/security/policy
PATCH  /api/v1/security/policy
POST   /api/v1/security/scan           # Dry-run PII scan
POST   /api/v1/security/mask           # Apply PII masking
```

### Knowledge Layer

```
GET    /api/v1/knowledge               # List/search items
POST   /api/v1/knowledge               # Add item
GET    /api/v1/knowledge/stats
POST   /api/v1/knowledge/extract       # Extract from LLM response
GET    /api/v1/knowledge/{id}
DELETE /api/v1/knowledge/{id}
PATCH  /api/v1/knowledge/{id}/tags
POST   /api/v1/knowledge/{a}/relate/{b}
```

### RAG

```
POST /api/v1/rag/search             # Semantic search
POST /api/v1/rag/search-all         # Search all indices
POST /api/v1/rag/augment            # Build augmented system prompt
POST /api/v1/rag/index              # Add document to index
POST /api/v1/rag/reindex            # Rebuild index from Knowledge Layer
GET  /api/v1/rag/stats
```

### Graph Database

```
POST   /api/v1/graph/nodes
GET    /api/v1/graph/nodes
GET    /api/v1/graph/nodes/{id}
DELETE /api/v1/graph/nodes/{id}
POST   /api/v1/graph/relationships
GET    /api/v1/graph/relationships
DELETE /api/v1/graph/relationships/{id}
POST   /api/v1/graph/traverse            # BFS traversal
GET    /api/v1/graph/path/{a}/{b}        # Shortest path
GET    /api/v1/graph/reachable/{id}
POST   /api/v1/graph/subgraph
GET    /api/v1/graph/stats
GET    /api/v1/graph/centrality
POST   /api/v1/graph/import/knowledge
GET    /api/v1/graph/export/cytoscape
GET    /api/v1/graph/export/d3
```

### Compliance

```
POST /api/v1/compliance/analyze        # Full compliance report
POST /api/v1/compliance/quick-scan
GET  /api/v1/compliance/rules
GET  /api/v1/compliance/standards
```

### CI/CD Export

```
POST /api/v1/cicd/export    # format: github | gitlab | junit | robot | json
GET  /api/v1/cicd/formats   # list available formats
```

### WebSocket

```
WS /ws/events    # Real-time gateway stats, RAG search, knowledge updates
WS /ws/logs      # Live execution log stream
```

---

## Frontend Applications

| File | Description |
|---|---|
| `aqua-qe.html` | Main chat interface — multi-provider selector, streaming, RTM Vivo, session save |
| `gateway-panel.html` | AI Gateway control panel — providers, routing, logs, observability, security, config |
| `workbench.html` | RTM Graph (Cytoscape.js) + Coverage Heatmap + traceability table |
| `story-engineering.html` | Monaco Editor with custom language, Gherkin/Robot tabs, compliance panel, versioning |
| `observability.html` | AI Observability dashboard — latency, cost, traces, heatmap, confidence |
| `knowledge-explorer.html` | Knowledge Layer Explorer — graph visualization, RAG search, stats |
| `engines-panel.html` | Engine Studio — pipeline builder, prompt manager |

All frontends are **standalone HTML files** — no build step, no npm, no framework install. Open directly in the browser.

---

## Configuration

### `config/gateway.json` — Settings

```json
{
  "deployment_mode": "cloud",
  "providers": {
    "anthropic": { "enabled": true, "default_model": "claude-sonnet-4-5" }
  },
  "routing": {
    "requirement": {
      "primary": "anthropic",
      "model": "claude-sonnet-4-5",
      "fallbacks": ["openai", "google_gemini"],
      "strategy": "capability_match"
    }
  }
}
```

### `config/.env` — API Keys (never committed)

```
AQUA_KEY_ANTHROPIC="sk-ant-..."
AQUA_KEY_OPENAI="sk-..."
AQUA_KEY_GOOGLE_GEMINI="AIza..."
AQUA_KEY_GROQ="gsk_..."
AQUA_KEY_MISTRAL="..."
```

### Supported Providers

| Provider | Type | Models |
|---|---|---|
| Anthropic | Cloud | claude-sonnet-4-5, claude-haiku-4-5, claude-opus-4-5 |
| OpenAI | Cloud | gpt-4o, gpt-4o-mini, gpt-4-turbo |
| Google Gemini | Cloud | gemini-2.5-flash-lite, gemini-2.0-flash, gemini-1.5-pro |
| Groq | Cloud | llama-3.3-70b-versatile, mixtral-8x7b |
| Mistral | Cloud | mistral-large-latest, codestral-latest |
| Ollama | Local | any model you have pulled |
| vLLM | Local | OpenAI-compatible |
| LM Studio | Local | OpenAI-compatible |

### Deployment Modes

| Mode | Description |
|---|---|
| `cloud` | Use cloud providers only |
| `hybrid` | Prefer cloud, fallback to local |
| `local` | Use local providers only (Ollama, vLLM, etc.) |

### Routing Strategies

| Strategy | Description |
|---|---|
| `capability_match` | Route to provider best suited for the engine type |
| `cost_optimized` | Always pick cheapest available provider |
| `performance_first` | Always pick fastest provider |
| `privacy_first` | Prefer local providers |
| `round_robin` | Distribute load evenly |

---

## Roadmap Status

| Phase | Item | Status |
|---|---|---|
| **Phase 1** | Conversational Core, 5 base engines, RTM Vivo | ✅ Delivered |
| **Phase 2** | AI Gateway, multi-provider, streaming, persistence | ✅ Delivered |
| **Phase 3** | Story Engineering (Monaco), Workbench (Cytoscape) | ✅ Delivered |
| **Phase 3** | AI Observability §29 | ✅ Delivered |
| **Phase 3** | AI Security & Governance §30 | ✅ Delivered |
| **Phase 3** | Knowledge Layer Cognitivo §31 | ✅ Delivered |
| **Phase 3** | Compliance Engine §38 (WCAG/LGPD/OWASP/ISO) | ✅ Delivered |
| **Phase 3** | PostgreSQL + Multi-tenant §33 | ⏸ Deferred (SQLite works great) |
| **Phase 4** | RAG Architecture §32 | ✅ Delivered |
| **Phase 4** | Graph Database §33 (SQLite-based) | ✅ Delivered |
| **Phase 4** | Knowledge Layer Explorer | ✅ Delivered |
| **Phase 4** | CI/CD Integration §36 | ✅ Delivered |
| **Phase 4** | WebSocket Events §35 | ✅ Delivered |

---

## Project Structure

```
aqua-gateway/
├── main.py                          # Entry point (uvicorn, port 8080)
├── requirements.txt
├── .gitignore
├── README.md
│
├── config/
│   ├── gateway.json                 # Provider settings + routing (auto-saved)
│   ├── .env                         # API keys — NOT committed
│   ├── sessions.db                  # Chat history
│   ├── knowledge.db                 # Knowledge Layer
│   └── graph.db                     # Knowledge Graph
│
├── backend/
│   ├── models/schemas.py            # Pydantic models
│   ├── providers/
│   │   ├── registry.py              # 10 providers × 6+ models
│   │   └── adapters.py              # Streaming adapters (Anthropic, OpenAI, Gemini, Ollama)
│   ├── gateway/
│   │   ├── core.py                  # AIGateway orchestrator
│   │   ├── config_manager.py        # Config persistence
│   │   ├── session_manager.py       # Session SQLite
│   │   ├── observability.py         # Metrics + tracing
│   │   ├── security.py              # PII + audit
│   │   ├── knowledge.py             # Knowledge Layer
│   │   ├── rag.py                   # RAG Engine (TF-IDF)
│   │   ├── graph_db.py              # Graph Database
│   │   ├── cicd.py                  # CI/CD export
│   │   └── prompt_manager.py        # Prompt templates
│   ├── engines/
│   │   ├── advanced.py              # 7 cognitive engines
│   │   └── compliance_engine.py     # WCAG/LGPD/OWASP/ISO rules
│   └── api/
│       ├── routes.py                # Core endpoints
│       ├── routes_phase2.py         # Advanced engine endpoints
│       ├── routes_sessions.py       # Session CRUD
│       ├── routes_observability.py  # Observability endpoints
│       ├── routes_security.py       # Security & audit
│       ├── routes_knowledge.py      # Knowledge Layer
│       ├── routes_rag.py            # RAG endpoints
│       ├── routes_graph.py          # Graph DB endpoints
│       ├── routes_compliance.py     # Compliance analysis
│       └── routes_cicd.py           # CI/CD export + WebSocket
│
└── frontend/
    ├── aqua-qe.html                 # Main chat (2800+ lines)
    ├── gateway-panel.html           # Gateway control (2100+ lines)
    ├── workbench.html               # RTM Graph + Coverage
    ├── story-engineering.html       # Monaco Editor IDE
    ├── observability.html           # AI Observability dashboard
    ├── knowledge-explorer.html      # Knowledge Layer Explorer
    └── engines-panel.html           # Engine Studio
```

---

## Notes on Technology Choices

### Why SQLite instead of PostgreSQL/Neo4j/Qdrant?

All three databases (sessions, knowledge, graph) use **SQLite** with WAL mode. This is intentional:

- **Zero infrastructure** — no Docker, no separate process, no connection strings
- **Same semantics** — the `GraphDB` module exposes a Neo4j-compatible interface; migrating to Neo4j means swapping the backend, not the API
- **Production-ready** — SQLite handles millions of rows and concurrent reads with WAL
- **Migration path** — PostgreSQL migration is a config change + schema copy; all SQL in the codebase is ANSI-compatible

### Why TF-IDF instead of sentence-transformers?

The RAG engine uses **TF-IDF + cosine similarity** because:

- Runs fully offline without downloading a 400MB model
- No GPU required
- Excellent results for domain-specific text (QE jargon, story IDs, LKDF patterns)
- Drop-in upgrade path: replace `tokenize()` in `rag.py` with `SentenceTransformer.encode()` when internet access is available

### Streaming

All providers implement **real SSE streaming** — no fake word-by-word simulation. The streaming endpoint uses `ReadableStream` in the browser and `httpx.AsyncClient.stream()` on the backend.

---

## License

MIT — See LICENSE file.

---

*Built with ❤️ by the AQuA-QE team using the LKDF methodology.*
