"""
Azure Function HTTP trigger — POST /api/upload-materials

Accepts multipart/form-data with:
  file          : document binary (optional if sharepoint_url given)
  sharepoint_url: SharePoint URL (optional if file given)

Returns: {session_id, materials_count}
"""

import io
import json
import logging
import uuid as _uuid

import azure.functions as func

logger = logging.getLogger(__name__)

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Session-ID",
}


def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Best-effort text extraction for indexing."""
    fname_lower = filename.lower()
    if fname_lower.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            pass
    # Fallback: decode as UTF-8
    return file_bytes.decode("utf-8", errors="replace")[:32000]


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
    filename = "material.docx"

    sharepoint_url = (
        req.form.get("sharepoint_url") or req.params.get("sharepoint_url")
    )
    file_data = req.files.get("file")

    if file_data:
        file_bytes = file_data.read()
        filename = file_data.filename or filename
    elif sharepoint_url:
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
    else:
        return func.HttpResponse(
            json.dumps({"error": "Provide either 'file' or 'sharepoint_url'."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    if not file_bytes:
        return func.HttpResponse(
            json.dumps({"error": "File is empty."}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    # ── Upload to Blob ─────────────────────────────────────────────────────
    try:
        from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent
        fh = FileHandlerAgent()
        blob_url = await fh.upload_to_blob(
            file_stream=io.BytesIO(file_bytes),
            filename=filename,
            user_id=session_id,
        )
        session.materials_urls.append(blob_url)
    except Exception as exc:
        logger.warning("Blob upload failed (non-fatal): %s", exc)

    # ── Index in Azure AI Search ───────────────────────────────────────────
    try:
        from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent
        fh = FileHandlerAgent()
        text_content = _extract_text(file_bytes, filename)
        doc_id = str(_uuid.uuid4())
        await fh.index_document_in_search(
            doc_id=doc_id,
            content=text_content,
            session_id=session_id,
            filename=filename,
        )
    except Exception as exc:
        logger.warning("AI Search indexing failed (non-fatal): %s", exc)

    # ── Update session ─────────────────────────────────────────────────────
    store.update_session(session)
    materials_count = len(session.materials_urls)

    return func.HttpResponse(
        json.dumps({
            "session_id": session_id,
            "materials_count": materials_count,
        }),
        status_code=200,
        mimetype="application/json",
        headers=_CORS_HEADERS,
    )
