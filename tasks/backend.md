# Backend Tasks — 5-Step Pipeline

## Task: session-store
**File**: `src/session/session_store.py`
**Goal**: Azure Table Storage CRUD for ExamSession model with full schema from claude.md.
**Steps**:
1. Define `ExamSession` dataclass matching claude.md schema.
2. Implement `SessionStore` with `create_session`, `get_session`, `update_session`.
3. Partition key = `session_id` (UUID). Row key = `session_id`.
4. JSON-serialize list fields (clo_list, plo_list, materials_urls, questions).
**Result file**: `tasks/results/session-store.md`

---

## Task: sharepoint-download
**File**: `src/agents/file_handler_agent/file_handler_agent.py`
**Goal**: Add `download_from_sharepoint(sharepoint_url) -> bytes` using Graph API.
**Steps**:
1. Acquire Graph API token via client credentials.
2. Resolve SharePoint sharing URL to file bytes.
3. Return raw bytes usable for both .docx and .pdf.
**Result file**: `tasks/results/sharepoint-download.md`

---

## Task: syllabus-agent
**File**: `src/agents/syllabus_agent/syllabus_agent.py`
**Goal**: Accept .docx/.pdf bytes, extract CLO/PLO via GPT-4o-mini, write to session.
**Steps**:
1. Parse .docx with python-docx or detect PDF (fallback: treat as text).
2. Prompt GPT-4o-mini via Azure OpenAI to extract CLO and PLO lists.
3. Write {clo_list, plo_list} to session via SessionStore.
4. Return {clo_list, plo_list}.
**Result file**: `tasks/results/syllabus-agent.md`

---

## Task: question-copilot-agent
**File**: `src/agents/question_copilot_agent/question_copilot_agent.py`
**Goal**: Streaming RAG chat agent using Azure AI Search over indexed materials.
**Steps**:
1. Accept session_id and user message.
2. Retrieve relevant context from Azure AI Search (materials index).
3. Yield SSE tokens from GPT-4o-mini streaming completion.
4. Include suggested CLO mapping and marks in final response.
**Result file**: `tasks/results/question-copilot-agent.md`

---

## Task: moderation-form-agent
**File**: `src/agents/moderation_form_agent/moderation_form_agent.py`
**Goal**: Fill AARO-FM-030 .docx template with session questions + CLO/PLO mapping.
**Steps**:
1. Load AARO-FM-030 template from blob storage or embedded fallback.
2. Populate table rows with question text, CLO, PLO, marks.
3. Upload completed form to Blob Storage (examops-output).
4. Update session moderation_form_url and return download URL.
**Result file**: `tasks/results/moderation-form-agent.md`

---

## Task: upload-syllabus-function
**File**: `src/functions/upload_syllabus/__init__.py`
**Goal**: POST /api/upload-syllabus — accept file or sharepoint_url, return {session_id, clo_list, plo_list}.
**Steps**:
1. Accept multipart file OR sharepoint_url query param.
2. Create or reuse session_id from X-Session-ID header.
3. Call SyllabusAgent.process(file_bytes, session_id).
4. Return {session_id, clo_list, plo_list}.
**Result file**: `tasks/results/upload-syllabus-function.md`

---

## Task: upload-materials-function
**File**: `src/functions/upload_materials/__init__.py`
**Goal**: POST /api/upload-materials — upload to Blob, index in AI Search.
**Steps**:
1. Accept multipart file OR sharepoint_url.
2. Upload bytes to examops-input blob.
3. Upsert document into Azure AI Search materials index.
4. Update session.materials_urls and return {session_id, materials_count}.
**Result file**: `tasks/results/upload-materials-function.md`

---

## Task: chat-function
**File**: `src/functions/chat/__init__.py`
**Goal**: POST /api/chat — SSE streaming from QuestionCopilotAgent.
**Steps**:
1. Accept JSON {session_id, message}.
2. Invoke QuestionCopilotAgent and yield SSE tokens.
3. Stream response with Content-Type: text/event-stream.
4. Final SSE event includes suggested CLO + marks.
**Result file**: `tasks/results/chat-function.md`

---

## Task: fill-moderation-form-function
**File**: `src/functions/fill_moderation_form/__init__.py`
**Goal**: POST /api/fill-moderation-form — return {download_url}.
**Steps**:
1. Accept JSON {session_id}.
2. Call ModerationFormAgent.fill_form(session_id).
3. Return {download_url}.
**Result file**: `tasks/results/fill-moderation-form-function.md`

---

## Task: export-questions-function
**File**: `src/functions/export_questions/__init__.py`
**Goal**: POST /api/export-questions — build .docx from session.questions, return blob URL.
**Steps**:
1. Accept JSON {session_id}.
2. Load session.questions.
3. Build .docx with python-docx listing all questions.
4. Upload to Blob, return {download_url}.
**Result file**: `tasks/results/export-questions-function.md`

---

## Task: mcp-server
**File**: `src/mcp/server.py`
**Goal**: Expose ExamOps pipeline as 4 MCP tools.
**Steps**:
1. Expose upload_syllabus, generate_questions, fill_moderation_form, format_exam tools.
2. Runnable standalone as MCP server.
3. Tools delegate to respective agents.
**Result file**: `tasks/results/mcp-server.md`
