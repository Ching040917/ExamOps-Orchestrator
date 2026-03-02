# Result: question-copilot-agent

**Status**: ✅ Complete

## What was done
- Created `src/agents/question_copilot_agent/__init__.py` and `question_copilot_agent.py`
- `QuestionCopilotAgent.stream(session_id, message, clo_list)` — async generator
- RAG: vector query against `exam-materials` Azure AI Search index filtered by session_id
- Falls back to unfiltered search if session has no indexed materials
- Streams GPT-4o-mini tokens via openai streaming API
- System prompt instructs model to include ```json {...} ``` suggestion block in every response
- Suggestion block contains: suggested_clo, suggested_marks, question_text

## Caveats
- Requires AZURE_OPENAI_*, AZURE_SEARCH_* env vars
- SEARCH_MATERIALS_INDEX defaults to "exam-materials"
