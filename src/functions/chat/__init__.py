"""
Azure Function HTTP trigger — POST /api/chat

Accepts JSON: {session_id, message}
Returns:      Server-Sent Events (text/event-stream) streaming from QuestionCopilotAgent.

SSE format:
  data: <token>\\n\\n
  ...
  data: [DONE]\\n\\n
"""

import json
import logging

import azure.functions as func

logger = logging.getLogger(__name__)

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Session-ID",
}


async def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_CORS_HEADERS)

    # ── Parse body ─────────────────────────────────────────────────────────
    try:
        body = req.get_json()
    except Exception:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    session_id = (
        body.get("session_id")
        or req.headers.get("X-Session-ID")
        or req.params.get("session_id")
    )
    message = body.get("message", "").strip()

    if not session_id or not message:
        return func.HttpResponse(
            json.dumps({"error": "Provide 'session_id' and 'message'."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    # ── Load session CLOs ──────────────────────────────────────────────────
    clo_list = []
    try:
        from src.session.session_store import SessionStore
        store = SessionStore()
        session = store.get_session(session_id)
        if session:
            clo_list = session.clo_list
    except Exception as exc:
        logger.warning("Could not load session CLOs: %s", exc)

    # ── Stream via QuestionCopilotAgent ────────────────────────────────────
    try:
        from src.agents.question_copilot_agent.question_copilot_agent import (
            QuestionCopilotAgent,
        )
        agent = QuestionCopilotAgent()

        sse_chunks = []
        async for token in agent.stream(session_id, message, clo_list):
            sse_chunks.append(f"data: {json.dumps(token)}\n\n")

        sse_chunks.append("data: [DONE]\n\n")
        sse_body = "".join(sse_chunks)

    except Exception as exc:
        logger.exception("QuestionCopilotAgent stream failed for session %s", session_id)
        error_sse = f"data: {json.dumps({'error': str(exc)})}\n\ndata: [DONE]\n\n"
        return func.HttpResponse(
            error_sse,
            status_code=200,
            mimetype="text/event-stream",
            charset="utf-8",
            headers={
                **_CORS_HEADERS,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return func.HttpResponse(
        sse_body,
        status_code=200,
        mimetype="text/event-stream",
        charset="utf-8",
        headers={
            **_CORS_HEADERS,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
