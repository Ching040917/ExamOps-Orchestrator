# Result: wizard-ui

**Status**: ✅ Complete

## What was done
- Replaced `src/web/index.html` with full 5-step wizard (single-file, no external deps)
- Left panel: step navigation with pending/active/complete status indicators (dot colors + checkmark SVG)
- Step 1: File upload (drag-drop) + SharePoint URL → calls /api/upload-syllabus → renders CLO/PLO pills
- Step 2: Multi-file upload + SharePoint URL → calls /api/upload-materials → shows indexed count
- Step 3: Split layout — chat panel (left) + question sidebar (right)
  - SSE streaming via fetch + ReadableStream (EventSource alternative that supports POST)
  - Each assistant response with ```json block gets "Add to Exam" button
  - Sidebar shows curated questions with remove option
- Step 4: CLO/PLO moderation table rendered from session questions
  - "Download AARO-FM-030" calls /api/fill-moderation-form
- Step 5: Upload exam draft → calls /api/format-exam → shows compliance badge, fix counts, diff iframe
- localStorage persists session_id; sent as X-Session-ID header on all calls
- CORS headers on all API functions
- SUC branding (blue gradient header)
