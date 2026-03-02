# Azure AI Foundry Setup — ExamOps Developer Reference

> **Related docs**: `AZURE_SETUP.md` (infra provisioning), `SKILL.md` (Foundry Local / offline dev),
> `docs/azure-cost-skill.md` (budget and cost control)

---

## 1. What is Azure AI Foundry?

Azure AI Foundry is Microsoft's cloud AI hub — a model catalog, serverless API gateway, and
project management layer for AI applications. It replaced Azure OpenAI Studio as the primary
way to deploy and call models from Azure.

This project uses Foundry as the default LLM backend:

- **Entry point**: `src/utils/llm_client.py` — `LLMClient` picks backend from `LLM_BACKEND` env var
- **Also used by**: `src/agents/formatting_engine/formatting_engine.py` — `LLMValidator` (Layer 2)
- **Backend value**: `LLM_BACKEND=foundry`

`AZURE_SETUP.md` Section 5 covers infra provisioning (resource group, subscription). This doc
focuses on **model selection** and **project linkage** — what to do after the Azure resources exist.

---

## 2. Free & Lowest-Cost Model Options (ranked)

| Option | Cost | Rate limit | Best for |
|--------|------|-----------|---------|
| **Foundry Local** (see `SKILL.md`) | Free, unlimited | None | Offline dev / CI |
| **GitHub Models** (`LLM_BACKEND=github`) | Free | ~150 req/day | Prototyping |
| **Phi-3.5-mini** (serverless) | ~$0.04/1M in · $0.12/1M out | None | Budget production |
| **Phi-4-mini** (serverless) | ~$0.07/1M in · $0.21/1M out | None | Production (recommended) |
| **GPT-4o-mini** (serverless) | ~$0.15/1M in · $0.60/1M out | None | Max quality |

**Recommendation**:
- **Development / prototyping**: `LLM_BACKEND=github` — zero cost, no infra needed
- **Production**: `AZURE_FOUNDRY_DEPLOYMENT=Phi-4-mini` — best quality-to-cost ratio in the Phi family
- **Offline / CI**: Foundry Local (see `SKILL.md`)

> **Note**: Serverless endpoints require a paid Azure subscription. Free-tier subscriptions
> (`Azure for Students`, `Free Trial`) are blocked from serverless model deployments.

---

## 3. Step-by-Step: Create an Azure AI Foundry Project

Prerequisite: `az login` and `az account set` already completed (see `AZURE_SETUP.md`).

```bash
FOUNDRY_PROJECT=foundry-examops-prod
RG=rg-examops-prod
REGION=southeastasia

# Create an Azure AI hub (required parent for all Foundry projects)
az ml workspace create \
  --name $FOUNDRY_PROJECT \
  --resource-group $RG \
  --location $REGION \
  --kind hub
```

Then complete the remaining steps in the Portal (the CLI does not support all Foundry project
configuration yet):

1. Go to **https://ai.azure.com** → click **New project** → select the hub created above
2. Open the project → **Model catalog** → search for **Phi-4-mini**
3. Click **Deploy** → **Serverless API** → accept defaults → **Deploy**
   - Wait 1–2 minutes until deployment status shows **Succeeded**
4. In the project, go to **Settings** → copy the **Endpoint** URL and **API Key**

---

## 4. Configure This Project

Add the following to `.env` (local dev) or Azure Function App Settings (production):

```env
LLM_BACKEND=foundry
AZURE_FOUNDRY_ENDPOINT=https://<your-project>.cognitiveservices.azure.com
AZURE_FOUNDRY_KEY=<your-api-key>
AZURE_FOUNDRY_DEPLOYMENT=Phi-4-mini
```

Replace `gpt-4o-mini` with `Phi-4-mini` if you previously followed `AZURE_SETUP.md` Section 5.

**Which files consume these variables:**

| File | Usage |
|------|-------|
| `src/utils/llm_client.py` | Primary LLM backend — used by all agents |
| `src/agents/formatting_engine/formatting_engine.py` | `LLMValidator` (Layer 2 of hybrid formatter) |

---

## 5. Switching Models Without Code Changes

Only `AZURE_FOUNDRY_DEPLOYMENT` needs to change. `LLMClient` passes the deployment name
directly to the API — no code edits required.

```env
# Switch from Phi-4-mini to GPT-4o-mini (higher quality, higher cost)
AZURE_FOUNDRY_DEPLOYMENT=gpt-4o-mini

# Switch to Phi-3.5-mini (lower cost, lower quality)
AZURE_FOUNDRY_DEPLOYMENT=Phi-3.5-mini
```

The deployment name must exactly match what is shown under **Deployments** in your Foundry project.

---

## 6. Validate the Connection

Run this smoke test from the repo root after setting environment variables:

```bash
python -c "
import asyncio, os
os.environ['LLM_BACKEND'] = 'foundry'
from src.utils.llm_client import LLMClient
c = LLMClient()
print(asyncio.run(c.chat([{'role': 'user', 'content': 'Hello'}])))
"
```

Expected output: a short string response from the model (no exceptions).

---

## 7. Gotchas

| Issue | Detail |
|-------|--------|
| Free-tier subscriptions blocked | Serverless endpoints require a paid subscription |
| Deployment not ready immediately | Wait for status **Succeeded** before calling the endpoint (1–2 min) |
| API version hardcoded | `LLMClient.__init__` uses `api-version=2024-02-01`; Phi-4-mini supports it |
| Trailing slash in endpoint | `AZURE_FOUNDRY_ENDPOINT` must **not** end with `/` |
| `AZURE_FOUNDRY_*` vars in formatting engine | `formatting_engine.py` still reads `AZURE_FOUNDRY_ENDPOINT` directly for its AIProjectClient path — keep both vars consistent |
