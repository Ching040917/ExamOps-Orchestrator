# Azure Cost Control — ExamOps Playbook

> **Related docs**: `AZURE_SETUP.md` (infra provisioning), `docs/azure-foundry-skill.md`
> (model selection and cost per token)

---

## 1. ExamOps Cost Profile

### Fixed monthly costs (approximate)

| Resource | SKU | Cost/month |
|----------|-----|-----------|
| Azure AI Search | Basic | ~$75 |
| Azure Function App | B2 | ~$75 |
| Azure Blob Storage | LRS, low volume | < $5 |
| Azure Table Storage | Low volume | < $1 |
| **Total baseline** | | **~$155/mo** |

### Variable costs

| Resource | Driver | Rate |
|----------|--------|------|
| LLM tokens (Phi-4-mini) | Requests per exam | ~$0.07/1M in · $0.21/1M out |
| LLM tokens (GPT-4o-mini) | Requests per exam | ~$0.15/1M in · $0.60/1M out |
| Blob Storage egress | File downloads | $0.087/GB (Southeast Asia) |

### Quick wins

- **Switch `AZURE_FOUNDRY_DEPLOYMENT` from `gpt-4o-mini` → `Phi-4-mini`** — ~60% LLM cost reduction
- **Use `LLM_BACKEND=github` locally** — 100% LLM cost reduction in development
- **Use `LLM_BACKEND=foundry-local` offline** — 100% LLM cost reduction (see `SKILL.md`)

---

## 2. Set a Monthly Budget + Alerts

```bash
SUBSCRIPTION=$(az account show --query id -o tsv)
RG=rg-examops-prod

# Create a $150/month budget scoped to the resource group
az consumption budget create \
  --budget-name "examops-monthly" \
  --amount 150 \
  --category Cost \
  --time-grain Monthly \
  --start-date "$(date +%Y-%m-01)" \
  --resource-group $RG \
  --subscription $SUBSCRIPTION
```

Budget alert thresholds must be configured in the Portal (CLI doesn't support alert conditions):

1. **Portal**: Cost Management → Budgets → **examops-monthly** → Add alert condition
2. Add two thresholds:
   - **80% actual** → email dev lead
   - **100% forecasted** → email team

---

## 3. Tag Resources for Cost Tracking

Tags let you filter the Cost Analysis view by project, environment, or team.

```bash
RG=rg-examops-prod

# Apply tags to the resource group
az tag update \
  --resource-id $(az group show --name $RG --query id -o tsv) \
  --operation merge \
  --tags project=examops environment=prod team=ai-dev

# Enable tag inheritance so child resources pick up group tags automatically
az feature register \
  --namespace Microsoft.CostManagement \
  --name TagInheritance
```

Tag inheritance takes up to 24 hours to propagate to child resources.

---

## 4. Monitor Costs via CLI

```bash
SUBSCRIPTION=$(az account show --query id -o tsv)
RG=rg-examops-prod

# Install azure-cost-cli (third-party, read-only)
pip install azure-cost-cli

# Current month spend broken down by resource
azure-cost costByResource --subscription $SUBSCRIPTION
```

To export a monthly CSV report to Blob Storage for record-keeping:

```bash
az costmanagement export create \
  --name examops-monthly-report \
  --scope "subscriptions/$SUBSCRIPTION/resourceGroups/$RG" \
  --type ActualCost \
  --dataset-configuration columns="[ResourceId,ServiceName,PreTaxCost,Currency]" \
  --recurrence Monthly \
  --recurrence-period from="$(date +%Y-%m-01)" \
  --storage-account-id $(az storage account show \
      --name stexamopsprod --resource-group $RG --query id -o tsv) \
  --storage-container cost-reports
```

---

## 5. Cost-Optimization Strategies (ExamOps-Specific)

| Strategy | Saving | How |
|----------|--------|-----|
| Phi-4-mini instead of GPT-4o-mini | ~60% on LLM | Set `AZURE_FOUNDRY_DEPLOYMENT=Phi-4-mini` |
| `LLM_BACKEND=github` in local dev | 100% on LLM | Set in local `.env` only, not production |
| `LLM_BACKEND=foundry-local` offline | 100% on LLM | See `SKILL.md` for setup |
| GitHub Models as primary in staging | 100% on LLM | Set `LLM_BACKEND=github` in staging App Settings |
| Downscale Function App to B1 off-hours | ~50% compute | Azure autoscale rules (Portal: App Service → Scale out) |
| Move AI Search to Free tier (dev env only) | $75/mo | 50 MB limit — not suitable for production |
| Delete unused Blob Storage versions | Varies | Enable lifecycle policy in Portal |

### Developer workflow rule

```
Local dev  →  LLM_BACKEND=github   (free, rate-limited)
Staging    →  LLM_BACKEND=github   (free, rate-limited)
Production →  LLM_BACKEND=foundry  (paid, Phi-4-mini)
```

---

## 6. Set an Auto-Stop Action (Optional)

Budget alerts are notification-only by default. To automatically stop resources when spending
exceeds the budget, wire an Azure Automation Runbook or Logic App to a budget action group.

```bash
RG=rg-examops-prod

# Create an action group that calls a webhook (e.g., a Logic App or Azure Function)
az monitor action-group create \
  --name ag-examops-cost-stop \
  --resource-group $RG \
  --short-name costStop \
  --webhook-receiver name=stopFunctions \
    service-uri=<your-logic-app-or-azure-function-url>
```

Then attach it in the Portal:
**Cost Management → Budgets → examops-monthly → Action groups** → select `ag-examops-cost-stop`

> The webhook payload is a standard Azure Budget alert schema. Your Logic App or Function
> can call `az functionapp stop` or scale down the App Service plan.

---

## 7. View Costs in the Portal

**Portal path**: Cost Management + Billing → Cost Management → **Cost Analysis**

Useful views:

| View | How to configure |
|------|-----------------|
| Cost by service | Group by: **Service name** |
| Cost by resource | Group by: **Resource** |
| ExamOps only | Filter by: Resource group = `rg-examops-prod` |
| LLM vs compute split | Group by: Service name; look for "Cognitive Services" vs "App Service" |

Download as Excel or CSV for monthly reporting to stakeholders.
