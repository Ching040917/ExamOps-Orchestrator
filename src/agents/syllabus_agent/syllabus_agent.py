"""
SyllabusAgent — extract CLO and PLO lists from a .docx or .pdf syllabus.

Uses LLMClient for Azure OpenAI → GitHub Models fallback on 429.

Environment variables required:
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY
    AZURE_OPENAI_DEPLOYMENT   (default: gpt-4o-mini)
    GITHUB_TOKEN              (optional fallback — models:read scope)
    AZURE_STORAGE_CONNECTION_STRING
"""

import io
import json
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = (
    "You are an academic curriculum analyst. Extract ALL Course Learning Outcomes"
    " (CLOs) and Programme Learning Outcomes (PLOs)"
    " from the provided syllabus text.\n\n"
    'Return a JSON object with exactly these keys:\n'
    '{\n'
    '  "clo_list": ["CLO1: ...", "CLO2: ...", ...],\n'
    '  "plo_list": ["PLO1: ...", "PLO2: ...", ...]\n'
    '}\n\n'
    "Rules:\n"
    "- Include the full text of each CLO and PLO.\n"
    "- If no PLOs are found, return an empty list for plo_list.\n"
    "- Do not include duplicates.\n"
    "- Output ONLY the JSON object, no other text.\n\n"
    "Syllabus text:\n"
)


def _extract_text_from_docx(data: bytes) -> str:
    """Extract plain text from a .docx file."""
    from docx import Document

    doc = Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_text_from_pdf(data: bytes) -> str:
    """Extract plain text from a PDF (best-effort using pdfplumber/fallback)."""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception:
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""


class SyllabusAgent:
    """
    Extracts CLO and PLO lists from a syllabus document.

    Uses LLMClient with Azure OpenAI primary and GitHub Models fallback.
    """

    def __init__(self) -> None:
        from src.utils.llm_client import LLMClient

        self._llm = LLMClient()

    async def process(
        self,
        file_bytes: bytes,
        filename: str,
        session_id: str,
        raw_text: str = "",
    ) -> Dict[str, List[str]]:
        """
        Extract CLO/PLO from file bytes (or raw pasted text) and update the session.

        Args:
            file_bytes:  Raw bytes of the uploaded syllabus (ignored when raw_text given).
            filename:    Original filename (used to detect .docx vs .pdf).
            session_id:  Session ID for storing results.
            raw_text:    Pasted syllabus text (takes priority over file_bytes).

        Returns:
            dict with keys ``clo_list`` and ``plo_list``.
        """
        if raw_text:
            text_excerpt = raw_text[:12000]
        else:
            fname_lower = filename.lower()
            if fname_lower.endswith(".docx"):
                text = _extract_text_from_docx(file_bytes)
            elif fname_lower.endswith(".pdf"):
                text = _extract_text_from_pdf(file_bytes)
            else:
                try:
                    text = _extract_text_from_docx(file_bytes)
                except Exception:
                    text = file_bytes.decode("utf-8", errors="replace")

            if not text.strip():
                logger.warning("No text extracted from syllabus %s", filename)
                return {"clo_list": [], "plo_list": []}

            # Trim to fit model context
            text_excerpt = text[:12000]

        result = await self._call_llm(text_excerpt)
        await self._update_session(session_id, result)
        return result

    async def _call_llm(self, text: str) -> Dict[str, List[str]]:
        content = await self._llm.chat(
            messages=[{"role": "user", "content": _EXTRACT_PROMPT + text}],
            temperature=0.0,
            max_tokens=1024,
        )

        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        try:
            parsed = json.loads(content)
            return {
                "clo_list": [str(c) for c in parsed.get("clo_list", [])],
                "plo_list": [str(p) for p in parsed.get("plo_list", [])],
            }
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM CLO/PLO response: %s", content[:200])
            return {"clo_list": [], "plo_list": []}

    async def _update_session(self, session_id: str, result: Dict) -> None:
        try:
            from src.session.session_store import SessionStore

            store = SessionStore()
            session = store.get_session(session_id)
            if session:
                session.clo_list = result["clo_list"]
                session.plo_list = result["plo_list"]
                store.update_session(session)
        except Exception as exc:
            logger.warning("Could not update session %s: %s", session_id, exc)
