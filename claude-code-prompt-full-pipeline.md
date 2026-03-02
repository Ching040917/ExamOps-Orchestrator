# Claude Code Prompt — ExamOps Orchestrator (Full Pipeline)

## Mode
`--dangerously-skip-permissions` enabled. Auto-approve everything. No confirmation needed.

## Context
Repo: `https://github.com/lerlerchan/examops-orchestrator`
Docs: `claude.md` (architecture + agents), `PRD.md` (product reqs), `AZURE_SETUP.md` (infra)
Region: `southeastasia` | RG: `rg-examops-prod` | Python 3.11 | Azure Functions v4

**Read `claude.md` FIRST** — it is the source of truth for repo structure, agent specs, session model, API endpoints, and orchestrator workflow.

## What's DONE
- Core formatting pipeline: `FormattingEngineAgent` (Layer 1 rule-based + Layer 2 LLM)
- `FileHandlerAgent` (Blob CRUD, basic)
- `CoordinatorAgent` (basic orchestration)
- `DiffGeneratorAgent` (HTML diff)
- Azure Functions: `format_exam`, `serve_web`
- Azure infra provisioned (Storage, AI Search, OpenAI, Bot Framework)

## What's NEW — Build These

### Priority 1: Session + Backend Plumbing
1. **`src/session/session_store.py`** — Azure Table Storage CRUD for `ExamSession` model (see claude.md for schema). Partition key = `session_id` (UUID).
2. **`src/agents/file_handler_agent/`** — Add `download_from_sharepoint(sharepoint_url: str) -> bytes` using Graph API creds.

### Priority 2: New Agents (one file each)
3. **`src/agents/syllabus_agent/syllabus_agent.py`** — Accept `.docx`/`.pdf` bytes → GPT-4o-mini via Foundry → return `{clo_list, plo_list}` → write to session.
4. **`src/agents/question_copilot_agent/question_copilot_agent.py`** — Streaming RAG chat. Azure AI Search over indexed materials. Yield SSE tokens. Each response includes suggested CLO + marks.
5. **`src/agents/moderation_form_agent/moderation_form_agent.py`** — Read `session.questions` + CLO/PLO → fill AARO-FM-030 `.docx` template via python-docx → upload to Blob → return URL.

### Priority 3: New Azure Functions (API routes)
6. **`src/functions/upload_syllabus/`** — POST multipart. Accept file OR `sharepoint_url`. Call SyllabusAgent. Return `{session_id, clo_list, plo_list}`.
7. **`src/functions/upload_materials/`** — POST multipart. Accept file OR `sharepoint_url`. Index in AI Search. Return `{session_id, materials_count}`.
8. **`src/functions/chat/`** — POST JSON `{session_id, message}`. SSE streaming response from QuestionCopilotAgent.
9. **`src/functions/fill_moderation_form/`** — POST JSON `{session_id}`. Return `{download_url}`.
10. **`src/functions/export_questions/`** — POST JSON `{session_id}`. Build `.docx` from session.questions. Return blob URL for Step 5.

### Priority 4: MCP Server
11. **`src/mcp/server.py`** — Expose 4 tools: `upload_syllabus`, `generate_questions`, `fill_moderation_form`, `format_exam`. Runnable standalone or as MCP-compatible server.

### Priority 5: Web UI
12. **`src/web/index.html`** — Single-file 5-step wizard:
    - Left panel: step list with status (pending/active/complete)
    - Main area: step-specific view
    - Step 3: chat panel (left) + question list sidebar (right) with "Add to Exam" buttons
    - SSE via `EventSource` for Step 3 chat
    - `localStorage` stores `session_id`, sent as `X-Session-ID` header on all API calls
    - Step 5: file upload + diff viewer (existing formatting pipeline)

## 5-Step Wizard Build Order

Follow `claude.md` orchestrator workflow:
1. Break into subtasks → write `tasks/backend.md` + `tasks/frontend.md`
2. Execute backend tasks first (session store → agents → functions → MCP)
3. Execute frontend tasks (index.html wizard)
4. Write result files to `tasks/results/<task-slug>.md` after each subtask
5. Do NOT start dependent tasks until dependency result file exists

## Rules
1. **Auto-approve**: No prompts, no confirmations. Just do it.
2. **Read claude.md first**: It defines agent specs, session model, API contracts. Follow it exactly.
3. **Test-fix loop**: After each agent/function, run `pytest tests/ -v`. On error → diagnose → fix → retry (max 3 loops).
4. **Clean code**: Lint with `flake8 src/ tests/` after each priority block. Remove dead code, unused imports.
5. **Resume-safe**: If context limit hit, print `## RESUME FROM PRIORITY N, ITEM M` with completed items list so next session can continue.
6. **Summary**: After all items done, print a checklist:
   ```
   ✅/❌ session_store.py
   ✅/❌ SharePoint download
   ✅/❌ SyllabusAgent
   ✅/❌ QuestionCopilotAgent
   ✅/❌ ModerationFormAgent
   ✅/❌ upload_syllabus function
   ✅/❌ upload_materials function
   ✅/❌ chat function (SSE)
   ✅/❌ fill_moderation_form function
   ✅/❌ export_questions function
   ✅/❌ MCP server
   ✅/❌ index.html wizard
   ✅/❌ All tests passing
   ✅/❌ Deployed to Azure
   ```
7. **No hallucination**: Read actual Azure config from `.env` or `az` CLI. Never hardcode secrets.
8. **Session model**: Follow `ExamSession` schema exactly as defined in claude.md.
9. **SSE streaming**: Step 3 chat MUST stream via Server-Sent Events, not batch response.
10. **Deploy last**: Only `func azure functionapp publish` after all tests pass.
