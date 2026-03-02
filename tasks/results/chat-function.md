# Result: chat-function

**Status**: ✅ Complete

## What was done
- Created `src/functions/chat/__init__.py`
- POST /api/chat — JSON {session_id, message}
- Loads session CLOs for context
- Calls QuestionCopilotAgent.stream() async generator
- Collects all SSE tokens and returns as text/event-stream response
- Each token: `data: "<token>"\n\n`
- Final token: `data: [DONE]\n\n`
- Error SSE on failure (does not 500)

## Note on Azure Functions SSE
Azure Functions HTTP triggers buffer responses; true streaming requires Durable Functions
or Azure Container Apps. The function buffers all tokens then sends as one response with
Content-Type: text/event-stream — the client EventSource still processes it correctly.
