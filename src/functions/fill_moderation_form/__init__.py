"""
Azure Function HTTP trigger — POST /api/fill-moderation-form

Accepts JSON: {session_id}
Returns:      {download_url}
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
        body = {}

    session_id = (
        body.get("session_id")
        or req.headers.get("X-Session-ID")
        or req.params.get("session_id")
    )

    if not session_id:
        return func.HttpResponse(
            json.dumps({"error": "Provide 'session_id'."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    # ── Fill moderation form ───────────────────────────────────────────────
    try:
        from src.agents.moderation_form_agent.moderation_form_agent import (
            ModerationFormAgent,
        )
        agent = ModerationFormAgent()
        download_url = await agent.fill_form(session_id)
    except ValueError as exc:
        return func.HttpResponse(
            json.dumps({"error": str(exc)}),
            status_code=404,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as exc:
        logger.exception("fill_moderation_form failed for session %s", session_id)
        return func.HttpResponse(
            json.dumps({"error": f"Form generation failed: {exc}"}),
            status_code=500,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    return func.HttpResponse(
        json.dumps({"session_id": session_id, "download_url": download_url}),
        status_code=200,
        mimetype="application/json",
        headers=_CORS_HEADERS,
    )
