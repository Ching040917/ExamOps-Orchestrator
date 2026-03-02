# Result: export-questions-function

**Status**: ✅ Complete

## What was done
- Created `src/functions/export_questions/__init__.py`
- POST /api/export-questions — JSON {session_id}
- Loads session.questions
- Builds .docx listing all questions with CLO, marks metadata
- Uploads to examops-output blob with 8-hour SAS URL
- Returns {session_id, download_url}
- Designed for Step 5: lecturer can download questions .docx to paste into exam draft
