# Claude Code Prompt — ExamOps Orchestrator

## Mode
`--dangerously-skip-permissions` enabled. Auto-approve everything. No confirmation needed.

## Context
Repo: `https://github.com/lerlerchan/examops-orchestrator`
Docs: `AZURE_SETUP.md` (infra), `PRD.md` (architecture), `requirements.txt` (deps)
Region: `southeastasia` | RG: `rg-examops-prod` | Python 3.11 | Azure Functions v4
User has already run `az login`.

## 5-Step Wizard — Execute Sequentially

### Step 1: Provision Azure Infra
Create all resources per `AZURE_SETUP.md` steps 1-7:
- Resource Group → Storage Account + 3 containers → AI Search + vector index → OpenAI (gpt-4o-mini + ada-002) → Entra ID app reg → Bot Framework → App Service Plan (B2) + Function App
- Store ALL keys/endpoints/connection strings as shell vars
- If name collision → append random 4-char suffix
- Save everything to `.env`

### Step 2: Configure & Wire
- Set all app settings on Function App (step 9 of AZURE_SETUP.md)
- Update bot messaging endpoint
- Verify `.env` is complete

### Step 3: Test
```bash
pytest tests/ -v
```
- If tests fail → read error → fix code → rerun
- Loop until green or 3 attempts max

### Step 4: Deploy
```bash
cd src/functions && func azure functionapp publish func-examops-prod --python
```
- Health check: `curl -X POST https://func-examops-prod.azurewebsites.net/api/format-exam`
- If 5xx → check `az functionapp logs` → fix → redeploy
- If 400 → success (expected, missing fields)

### Step 5: CI/CD
Create `.github/workflows/deploy.yml`:
- Trigger: push to `main`
- Jobs: install deps → pytest → `azure/functions-action@v1` deploy
- List required GitHub Actions secrets in a comment block

## Rules
1. **Auto-approve**: No prompts, no confirmations. Just do it.
2. **Test-fix loop**: On any error → diagnose → fix → retry (max 3 loops)
3. **Clean code**: After each step, lint/tidy touched files. Remove dead code, unused imports.
4. **Resume-safe**: If context limit hit, print `## RESUME FROM STEP N` with remaining state (saved vars, completed steps) so next session can continue.
5. **Summary**: After all steps, print a table of: all resources created, endpoints, keys (masked), and status (✅/❌).
6. **No hallucination**: If unsure about a value, read it from Azure CLI output. Never hardcode secrets.
