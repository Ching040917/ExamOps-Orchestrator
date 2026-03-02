"""
QuestionCopilotAgent — streaming RAG chat agent for exam question generation.

Uses Azure AI Search over indexed learning materials to ground responses.
Yields SSE-compatible token strings. Each full response includes a suggested
CLO mapping and marks value.

Environment variables required:
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY
    AZURE_OPENAI_DEPLOYMENT   (default: gpt-4o-mini)
    AZURE_SEARCH_ENDPOINT
    AZURE_SEARCH_KEY
    AZURE_EMBEDDING_MODEL     (default: text-embedding-ada-002)
    SEARCH_MATERIALS_INDEX    (default: exam-materials)
"""

import logging
import os
from typing import AsyncIterator, List

logger = logging.getLogger(__name__)

OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("AZURE_EMBEDDING_MODEL", "text-embedding-ada-002")
MATERIALS_INDEX = os.getenv("SEARCH_MATERIALS_INDEX", "exam-materials")

_SYSTEM_PROMPT = """You are an AI exam question generation assistant for Southern University College.
Your role is to help lecturers create high-quality exam questions aligned to Course Learning Outcomes (CLOs).

When generating questions:
1. Base questions on the provided learning materials context.
2. Suggest which CLO each question maps to.
3. Suggest appropriate marks (typically 3, 5, or 10 marks).
4. End EVERY response with a JSON block (surrounded by ```json ... ```) containing:
   {"suggested_clo": "CLO1", "suggested_marks": 5, "question_text": "...the full question..."}

Keep responses focused and academic in tone."""

_RAG_PROMPT_TEMPLATE = """Learning materials context:
{context}

Session CLOs:
{clos}

Lecturer's request: {message}

Generate an appropriate exam question based on the materials above."""


class QuestionCopilotAgent:
    """
    Streaming RAG chat agent for exam question generation.

    Usage:
        agent = QuestionCopilotAgent()
        async for token in agent.stream(session_id, "Generate a question on...", clo_list):
            yield f"data: {token}\\n\\n"
    """

    def __init__(self) -> None:
        self._openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self._openai_key = os.getenv("AZURE_OPENAI_KEY")
        self._search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
        self._search_key = os.getenv("AZURE_SEARCH_KEY")

    async def stream(
        self,
        session_id: str,
        message: str,
        clo_list: List[str] = None,
    ) -> AsyncIterator[str]:
        """
        Retrieve relevant context from AI Search and stream GPT response tokens.

        Yields:
            SSE-compatible strings. The final token is a JSON metadata block.
        """
        clo_list = clo_list or []

        # Retrieve context from Azure AI Search
        context = await self._retrieve_context(session_id, message)

        # Build prompt
        clos_str = "\n".join(f"- {c}" for c in clo_list) if clo_list else "No CLOs loaded yet."
        prompt = _RAG_PROMPT_TEMPLATE.format(
            context=context[:6000],
            clos=clos_str,
            message=message,
        )

        # Stream from Azure OpenAI
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=self._openai_endpoint,
            api_key=self._openai_key,
            api_version="2024-02-01",
        )

        stream = client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            temperature=0.7,
            max_tokens=1024,
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def _retrieve_context(self, session_id: str, query: str) -> str:
        """Retrieve relevant text chunks from Azure AI Search."""
        try:
            from openai import AzureOpenAI
            from azure.search.documents import SearchClient
            from azure.search.documents.models import VectorizedQuery
            from azure.core.credentials import AzureKeyCredential

            openai_client = AzureOpenAI(
                azure_endpoint=self._openai_endpoint,
                api_key=self._openai_key,
                api_version="2024-02-01",
            )
            embedding_response = openai_client.embeddings.create(
                input=query, model=EMBEDDING_MODEL
            )
            embedding = embedding_response.data[0].embedding

            search_client = SearchClient(
                endpoint=self._search_endpoint,
                index_name=MATERIALS_INDEX,
                credential=AzureKeyCredential(self._search_key),
            )
            vector_query = VectorizedQuery(
                vector=embedding,
                k_nearest_neighbors=3,
                fields="content_vector",
            )
            results = list(
                search_client.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    filter=f"session_id eq '{session_id}'",
                    select=["content", "filename"],
                    top=3,
                )
            )

            if not results:
                # Fall back to unfiltered search if session has no indexed materials yet
                results = list(
                    search_client.search(
                        search_text=query,
                        vector_queries=[vector_query],
                        select=["content", "filename"],
                        top=2,
                    )
                )

            chunks = [r.get("content", "") for r in results if r.get("content")]
            return "\n\n---\n\n".join(chunks)

        except Exception as exc:
            logger.warning("AI Search retrieval failed: %s", exc)
            return "(No learning materials indexed yet. Generating question from general knowledge.)"
