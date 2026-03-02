# Result: moderation-form-agent

**Status**: ✅ Complete

## What was done
- Created `src/agents/moderation_form_agent/__init__.py` and `moderation_form_agent.py`
- `ModerationFormAgent.fill_form(session_id)` — loads session, builds docx, uploads to blob
- Tries to load AARO-FM-030.docx template from `examops-templates` container
- Falls back to a clean generated document if template not found
- Generates: title block, CLO/PLO summary, questions table (No.|Question|CLO|PLO|Marks)
- Uploads to `examops-output` container with 8-hour SAS URL
- Updates session.moderation_form_url

## Caveats
- MODERATION_TEMPLATE_BLOB env var overrides template blob name (default: AARO-FM-030.docx)
