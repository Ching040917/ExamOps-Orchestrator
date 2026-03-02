# Frontend Tasks — 5-Step Wizard

## Task: wizard-ui
**File**: `src/web/index.html`
**Goal**: Single-file 5-step wizard with SSE chat, step nav, and diff viewer.
**Steps**:
1. Left panel: step list with status indicators (pending/active/complete).
2. Step 1: File upload + SharePoint URL input; calls /api/upload-syllabus.
3. Step 2: File upload + SharePoint URL; calls /api/upload-materials.
4. Step 3: Chat panel (left) + question list sidebar (right) with "Add to Exam" per SSE response.
5. Step 4: CLO/PLO review; download moderation form; calls /api/fill-moderation-form.
6. Step 5: Upload exam draft; format; show diff; calls existing /api/format-exam.
7. localStorage stores session_id; sent as X-Session-ID header on all calls.
8. EventSource SSE for Step 3 chat streaming.
**Result file**: `tasks/results/wizard-ui.md`
