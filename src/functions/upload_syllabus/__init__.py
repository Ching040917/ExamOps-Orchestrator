"""
Azure Function HTTP trigger — POST /api/upload-syllabus

Accepts multipart/form-data with:
  file          : .docx or .pdf binary (optional if sharepoint_url given)
  sharepoint_url: SharePoint URL (optional if file given)

Returns: {session_id, clo_list, plo_list}
"""

import json
import logging
import os

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

    # ── Resolve session ────────────────────────────────────────────────────
    session_id = req.headers.get("X-Session-ID") or req.params.get("session_id")

    from src.session.session_store import SessionStore
    store = SessionStore()
    session = store.get_or_create(session_id)
    session_id = session.session_id

    # ── Resolve file bytes ─────────────────────────────────────────────────
    file_bytes: bytes = b""
    filename = "syllabus.docx"

    sharepoint_url = (
        req.form.get("sharepoint_url") or req.params.get("sharepoint_url")
    )
    file_data = req.files.get("file")
    raw_text = (req.form.get("raw_text") or "").strip()

    if file_data:
        file_bytes = file_data.read()
        filename = file_data.filename or filename
    elif sharepoint_url:
        # Pre-check Graph API credentials before attempting download
        if not all([
            os.environ.get("GRAPH_TENANT_ID"),
            os.environ.get("GRAPH_CLIENT_ID"),
            os.environ.get("GRAPH_CLIENT_SECRET"),
        ]):
            return func.HttpResponse(
                json.dumps({
                    "error": (
                        "SharePoint URL requires Microsoft Graph API credentials. "
                        "Set GRAPH_TENANT_ID, GRAPH_CLIENT_ID, and GRAPH_CLIENT_SECRET "
                        "in your .env or Azure Function App Settings. "
                        "Alternatively, upload a file or paste your syllabus text."
                    )
                }),
                status_code=400,
                mimetype="application/json",
                headers=_CORS_HEADERS,
            )
        try:
            from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent
            fh = FileHandlerAgent()
            file_bytes = await fh.download_from_sharepoint(sharepoint_url)
            filename = sharepoint_url.split("/")[-1] or filename
        except Exception as exc:
            logger.exception("SharePoint download failed")
            return func.HttpResponse(
                json.dumps({"error": f"SharePoint download failed: {exc}"}),
                status_code=502,
                mimetype="application/json",
                headers=_CORS_HEADERS,
            )
    elif raw_text:
        file_bytes = b""
        filename = "syllabus_pasted.txt"
    else:
        return func.HttpResponse(
            json.dumps({"error": "Provide 'file', 'sharepoint_url', or 'raw_text'."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    if not file_bytes and not raw_text:
        return func.HttpResponse(
            json.dumps({"error": "File is empty."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    # ── Upload syllabus to Blob for reference ──────────────────────────────
    try:
        from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent
        import io
        fh = FileHandlerAgent()
        blob_url = await fh.upload_to_blob(
            file_stream=io.BytesIO(file_bytes),
            filename=filename,
            user_id=session_id,
        )
        session.syllabus_url = blob_url
    except Exception as exc:
        logger.warning("Blob upload failed (non-fatal): %s", exc)

    # ── Run SyllabusAgent ──────────────────────────────────────────────────
    try:
        from src.agents.syllabus_agent.syllabus_agent import SyllabusAgent
        agent = SyllabusAgent()
        result = await agent.process(file_bytes, filename, session_id, raw_text=raw_text)
    except Exception as exc:
        logger.exception("SyllabusAgent failed for session %s", session_id)
        return func.HttpResponse(
            json.dumps({"error": f"CLO/PLO extraction failed: {exc}"}),
            status_code=500,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    return func.HttpResponse(
        json.dumps({
            "session_id": session_id,
            "clo_list": result["clo_list"],
            "plo_list": result["plo_list"],
        }),
        status_code=200,
        mimetype="application/json",
        headers=_CORS_HEADERS,
    )
