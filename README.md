# ExamOps Orchestrator

AI-powered exam paper formatter for Southern University College. Accepts a `.docx` exam paper, applies deterministic rule-based fixes (numbering, spacing, margins, marks notation, headers), runs an LLM compliance pass, and returns a formatted document with a color-coded diff report — all via Microsoft Teams or an HTTP API.

---

## Prerequisites

Provision the following Azure resources before running locally or deploying:

| Resource | Used for |
|----------|----------|
| Azure Storage Account | Input / output / template `.docx` files (3 containers) |
| Azure AI Search | Vector index of template formatting rules |
| Azure OpenAI | Embeddings (`text-embedding-ada-002`) + SK kernel LLM |
| Azure AI Foundry project | LLM validation layer (`gpt-4o-mini`) |
| Azure Bot Framework (+ Entra ID app) | Teams Bot + Microsoft Graph API (OneDrive) |
| Azure Functions (Consumption plan) | HTTP trigger entry point |

---

## Local Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/lerlerchan/examops-orchestrator.git
cd examops-orchestrator
pip install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env
# Edit .env and fill in all Required values (see .env.example for descriptions)

# 3. Verify setup
pytest tests/ -v
```

---

## Run Tests

```bash
pytest tests/ -v

# Single test file
pytest tests/test_formatting_engine.py -v

# Single test case
pytest tests/test_formatting_engine.py::test_numbering_correction -v
```

---

## Run Azure Function Locally

Requires [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) v4+.

```bash
cd src/functions
func start
```

The HTTP trigger will be available at `http://localhost:7071/api/format_exam`.

---

## Deploy to Azure Functions

```bash
func azure functionapp publish examops-functions
```

For GitHub-based deployment, `.github/workflows/deploy.yml` runs:
- `pytest` on every PR/push to `main`
- Azure Functions deployment on push to `main`
- Post-deploy Playwright teacher-flow tests against `https://<AZURE_FUNCTIONAPP_NAME>.azurewebsites.net/api/web` (blocking)

Required GitHub configuration:
- Repository variable: `AZURE_FUNCTIONAPP_NAME`
- Repository secret: `AZURE_CREDENTIALS`

---

## Run Teams Bot

```bash
python src/bot/app.py
```

The bot listens on `PORT` (default `3978`). Use [ngrok](https://ngrok.com/) or a similar tunnel to expose it during local development, then register the messaging endpoint in your Azure Bot resource.

---

## Architecture

See [`claude.md`](./claude.md) for the full architecture, agent design, and decision log.

![ExamOps architecture diagram](sample/diagram.png)

**Agent pipeline** (all routing goes through `CoordinatorAgent`):

```
Teams Bot / HTTP Trigger
        │
        ▼
CoordinatorAgent
        │
        ├─► FileHandlerAgent      — Blob Storage I/O, AI Search, Graph API
        │
        ├─► FormattingEngineAgent — Rule-based (python-docx) + LLM validation
        │
        └─► DiffGeneratorAgent   — HTML diff + compliance stats card
```

---

## Contributors

- [@lerlerchan](https://github.com/lerlerchan)
- [@calvin139](https://github.com/calvin139)
- [@qqrey](https://github.com/qqrey6)
- [@Ching](https://github.com/Ching040917)

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for contribution guidelines.
