"""
SyllabusAgent — extract CLO and PLO lists from a .docx or .pdf syllabus.

Environment variables required:
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY
    AZURE_OPENAI_DEPLOYMENT   (default: gpt-4o-mini)
    AZURE_STORAGE_CONNECTION_STRING
"""

import io
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

_EXTRACT_PROMPT = """You are an academic curriculum analyst. Extract ALL Course Learning Outcomes (CLOs) and Programme Learning Outcomes (PLOs) from the provided syllabus text.

Return a JSON object with exactly these keys:
{
  "clo_list": ["CLO1: ...", "CLO2: ...", ...],
  "plo_list": ["PLO1: ...", "PLO2: ...", ...]
}

Rules:
- Include the full text of each CLO and PLO.
- If no PLOs are found, return an empty list for plo_list.
- Do not include duplicates.
- Output ONLY the JSON object, no other text.

Syllabus text:
"""


def _extract_text_from_docx(data: bytes) -> str:
    """Extract plain text from a .docx file."""
    from docx import Document

    doc = Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_text_from_pdf(data: bytes) -> str:
    """Extract plain text from a PDF (best-effort using lxml/fallback)."""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception:
        # Fallback: treat bytes as UTF-8 text (works for text-based PDFs)
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""


class SyllabusAgent:
    """
    Extracts CLO and PLO lists from a syllabus document using GPT-4o-mini.
    """

    def __init__(self) -> None:
        self._openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self._openai_key = os.getenv("AZURE_OPENAI_KEY")

    async def process(
        self, file_bytes: bytes, filename: str, session_id: str
    ) -> Dict[str, List[str]]:
        """
        Extract CLO/PLO from file bytes and update the session.

        Args:
            file_bytes:  Raw bytes of the uploaded syllabus.
            filename:    Original filename (used to detect .docx vs .pdf).
            session_id:  Session ID for storing results.

        Returns:
            dict with keys ``clo_list`` and ``plo_list``.
        """
        # Extract text based on file type
        fname_lower = filename.lower()
        if fname_lower.endswith(".docx"):
            text = _extract_text_from_docx(file_bytes)
        elif fname_lower.endswith(".pdf"):
            text = _extract_text_from_pdf(file_bytes)
        else:
            # Attempt as docx, fall back to raw text
            try:
                text = _extract_text_from_docx(file_bytes)
            except Exception:
                text = file_bytes.decode("utf-8", errors="replace")

        if not text.strip():
            logger.warning("No text extracted from syllabus %s", filename)
            return {"clo_list": [], "plo_list": []}

        # Trim to fit GPT context
        text_excerpt = text[:12000]

        # Call GPT-4o-mini via Azure OpenAI
        result = await self._call_llm(text_excerpt)

        # Persist to session
        await self._update_session(session_id, result)
        return result

    async def _call_llm(self, text: str) -> Dict[str, List[str]]:
        import json
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=self._openai_endpoint,
            api_key=self._openai_key,
            api_version="2024-02-01",
        )
        response = client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "user", "content": _EXTRACT_PROMPT + text},
            ],
            temperature=0.0,
            max_tokens=1024,
        )
        content = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
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
