"""
FileHandlerAgent — Azure Blob Storage I/O, Azure AI Search vector queries,
and OneDrive sharing links via Microsoft Graph API.

Environment variables required at runtime:
    AZURE_STORAGE_CONNECTION_STRING
    AZURE_SEARCH_ENDPOINT
    AZURE_SEARCH_KEY
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY          (for ada-002 embeddings)
    GRAPH_TENANT_ID           (for OneDrive / Graph API)
    GRAPH_CLIENT_ID
    GRAPH_CLIENT_SECRET
"""

import io
import os
import logging
from datetime import datetime, timedelta, timezone

from docx import Document

logger = logging.getLogger(__name__)

# Azure container names
CONTAINER_INPUT = os.getenv("BLOB_CONTAINER_INPUT", "examops-input")
CONTAINER_OUTPUT = os.getenv("BLOB_CONTAINER_OUTPUT", "examops-output")
CONTAINER_TEMPLATES = os.getenv("BLOB_CONTAINER_TEMPLATES", "examops-templates")

# Azure AI Search index
SEARCH_INDEX = os.getenv("SEARCH_INDEX_NAME", "exam-templates")

# Embedding model
EMBEDDING_MODEL = os.getenv("AZURE_EMBEDDING_MODEL", "text-embedding-ada-002")


class FileHandlerAgent:
    """
    Handles all file I/O for the ExamOps pipeline.

    Blob containers:
        examops-input     — incoming .docx files from users
        examops-output    — formatted .docx + HTML diff reports
        examops-templates — static template reference files

    SAS token expiry policy:
        Input  uploads  — 1-hour SAS URL returned to caller
        Output files    — 1-hour SAS URL; refresh via save_outputs()
    """

    def __init__(self) -> None:
        self._connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self._search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
        self._search_key = os.getenv("AZURE_SEARCH_KEY")
        self._openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self._openai_key = os.getenv("AZURE_OPENAI_KEY")
        self._graph_tenant_id = os.getenv("GRAPH_TENANT_ID")
        self._graph_client_id = os.getenv("GRAPH_CLIENT_ID")
        self._graph_client_secret = os.getenv("GRAPH_CLIENT_SECRET")

    # ── Upload ───────────────────────────────────────────────────────────────

    async def upload_to_blob(
        self, file_stream: io.BytesIO, filename: str, user_id: str
    ) -> str:
        """
        Upload a .docx file to the examops-input container.

        Blob naming: ``{timestamp}_{user_id}_{filename}``
        e.g. ``20260226T093000Z_u123_MidtermPaper.docx``

        Args:
            file_stream: Binary stream of the .docx file.
            filename:    Original filename (used as suffix).
            user_id:     AAD / Teams user ID.

        Returns:
            SAS URL with 1-hour expiry.
        """
        from azure.storage.blob import (
            BlobServiceClient,
            generate_blob_sas,
            BlobSasPermissions,
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        blob_name = f"{timestamp}_{user_id}_{filename}"

        service_client = BlobServiceClient.from_connection_string(
            self._connection_string
        )
        container_client = service_client.get_container_client(CONTAINER_INPUT)
        container_client.upload_blob(blob_name, file_stream, overwrite=True)

        sas_token = generate_blob_sas(
            account_name=service_client.account_name,
            container_name=CONTAINER_INPUT,
            blob_name=blob_name,
            account_key=service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        blob_url = (
            f"https://{service_client.account_name}.blob.core.windows.net"
            f"/{CONTAINER_INPUT}/{blob_name}?{sas_token}"
        )
        logger.info("Uploaded %s to %s", blob_name, CONTAINER_INPUT)
        return blob_url

    # ── Download ─────────────────────────────────────────────────────────────

    async def download_from_blob(self, blob_url: str) -> Document:
        """
        Download a blob and return a python-docx Document.

        Args:
            blob_url: Full SAS URL of the .docx blob.

        Returns:
            python-docx Document object.

        Raises:
            ValueError: If the blob cannot be parsed as a valid .docx.
        """
        import requests

        response = requests.get(blob_url, timeout=30)
        response.raise_for_status()

        try:
            doc = Document(io.BytesIO(response.content))
        except Exception as exc:
            raise ValueError(f"Could not parse blob as .docx: {exc}") from exc

        logger.info("Downloaded and parsed document from blob")
        return doc

    # ── Template retrieval ───────────────────────────────────────────────────

    async def get_template_from_vectordb(self, query: str) -> dict:
        """
        Retrieve template rules from Azure AI Search using vector similarity.

        Steps:
            1. Generate embedding for ``query`` via OpenAI ada-002.
            2. Run vector search against the ``exam-templates`` index.
            3. Return the top result's template_rules field as a dict.

        Args:
            query: Natural-language description of the formatting context.

        Returns:
            Template rules dict, e.g.:
            {
                "header_text": "SOUTHERN UNIVERSITY COLLEGE",
                "numbering_scheme": ["Q{n}.", "(a)", "(i)"],
                "marks_pattern": "(\\d+ marks?)",
                "margin_cm": {"top": 2.5, "bottom": 2.5, "left": 3.0, "right": 2.5},
                ...
            }

        Raises:
            RuntimeError: If Azure AI Search returns no results.
        """
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
            index_name=SEARCH_INDEX,
            credential=AzureKeyCredential(self._search_key),
        )
        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=1,
            fields="content_vector",
        )
        results = list(
            search_client.search(
                search_text=None,
                vector_queries=[vector_query],
                select=["template_rules"],
                top=1,
            )
        )

        if not results:
            raise RuntimeError("Azure AI Search returned no template rules")

        template_rules = results[0].get("template_rules", {})
        logger.info("Retrieved template rules from Azure AI Search")
        return template_rules

    # ── Save outputs ─────────────────────────────────────────────────────────

    async def save_outputs(
        self, formatted_doc: Document, diff_html: str, job_id: str
    ) -> dict:
        """
        Save formatted document and HTML diff to examops-output.

        Args:
            formatted_doc: Formatted python-docx Document.
            diff_html:     HTML string of the diff report.
            job_id:        Job identifier used as filename prefix.

        Returns:
            dict with keys ``docx``, ``html`` — each a 1-hour SAS URL.
        """
        from azure.storage.blob import (
            BlobServiceClient,
            generate_blob_sas,
            BlobSasPermissions,
        )

        service_client = BlobServiceClient.from_connection_string(
            self._connection_string
        )

        def _upload_and_sas(blob_name: str, data: bytes, content_type: str) -> str:
            container_client = service_client.get_container_client(CONTAINER_OUTPUT)
            container_client.upload_blob(
                blob_name,
                data,
                overwrite=True,
                content_settings={"content_type": content_type},
            )
            sas_token = generate_blob_sas(
                account_name=service_client.account_name,
                container_name=CONTAINER_OUTPUT,
                blob_name=blob_name,
                account_key=service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            return (
                f"https://{service_client.account_name}.blob.core.windows.net"
                f"/{CONTAINER_OUTPUT}/{blob_name}?{sas_token}"
            )

        # Save .docx
        docx_buffer = io.BytesIO()
        formatted_doc.save(docx_buffer)
        docx_url = _upload_and_sas(
            f"{job_id}_formatted.docx",
            docx_buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        # Save HTML diff
        html_url = _upload_and_sas(
            f"{job_id}_diff.html",
            diff_html.encode("utf-8"),
            "text/html",
        )

        logger.info("Saved outputs for job %s", job_id)
        return {"docx": docx_url, "html": html_url}

    # ── OneDrive link ────────────────────────────────────────────────────────

    async def create_onedrive_link(self, blob_url: str) -> str:
        """
        Generate a shareable OneDrive link for a blob.

        Uses the Microsoft Graph API ``/me/drive/items/{item-id}/createLink``
        endpoint with ``type=view`` and ``scope=anonymous``.

        Args:
            blob_url: Azure Blob SAS URL to wrap as a OneDrive share.

        Returns:
            Shareable OneDrive URL string.

        Note:
            Requires the file to already be present in a OneDrive-backed
            SharePoint library. If the blob is in plain Azure Storage (not
            SharePoint), this method uploads a copy first via Graph API.
        """
        import requests

        token = self._get_graph_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Download blob content to re-upload via Graph
        file_response = requests.get(blob_url, timeout=30)
        file_response.raise_for_status()
        filename = blob_url.split("/")[-1].split("?")[0]

        # Upload to OneDrive root
        upload_url = (
            f"https://graph.microsoft.com/v1.0/me/drive/root:/{filename}:/content"
        )
        upload_response = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            data=file_response.content,
            timeout=60,
        )
        upload_response.raise_for_status()
        item_id = upload_response.json()["id"]

        # Create sharing link
        share_url = (
            f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/createLink"
        )
        share_response = requests.post(
            share_url,
            headers=headers,
            json={"type": "view", "scope": "anonymous"},
            timeout=30,
        )
        share_response.raise_for_status()
        link = share_response.json()["link"]["webUrl"]
        logger.info("Created OneDrive link for item %s", item_id)
        return link

    # ── SharePoint download ───────────────────────────────────────────────────

    async def download_from_sharepoint(self, sharepoint_url: str) -> bytes:
        """
        Download a file from SharePoint/OneDrive using Microsoft Graph API.

        Resolves a SharePoint sharing URL to raw file bytes.

        Args:
            sharepoint_url: SharePoint file URL or sharing link.

        Returns:
            Raw bytes of the file.
        """
        import base64
        import requests

        token = self._get_graph_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Encode the URL as a sharing token (Graph API shares endpoint)
        encoded = base64.urlsafe_b64encode(sharepoint_url.encode()).rstrip(b"=").decode()
        shares_url = f"https://graph.microsoft.com/v1.0/shares/u!{encoded}/driveItem/content"

        response = requests.get(shares_url, headers=headers, timeout=60, allow_redirects=True)

        if response.status_code == 302:
            # Follow redirect to actual download URL
            response = requests.get(
                response.headers["Location"], timeout=60
            )

        response.raise_for_status()
        logger.info("Downloaded %d bytes from SharePoint", len(response.content))
        return response.content

    # ── Blob upload for bytes ─────────────────────────────────────────────────

    async def upload_bytes_to_blob(
        self, data: bytes, filename: str, container: str = None
    ) -> str:
        """
        Upload raw bytes to Blob Storage and return a SAS URL.

        Args:
            data:      Raw bytes to upload.
            filename:  Blob name / filename.
            container: Target container (defaults to examops-input).

        Returns:
            1-hour SAS URL.
        """
        import io

        return await self.upload_to_blob(
            file_stream=io.BytesIO(data),
            filename=filename,
            user_id="system",
        )

    # ── Upsert document into AI Search ───────────────────────────────────────

    async def index_document_in_search(
        self, doc_id: str, content: str, session_id: str, filename: str
    ) -> None:
        """
        Upsert a document into Azure AI Search materials index.

        Args:
            doc_id:     Unique document ID.
            content:    Extracted text content.
            session_id: Session identifier for filtering.
            filename:   Original filename.
        """
        from openai import AzureOpenAI
        from azure.search.documents import SearchClient
        from azure.core.credentials import AzureKeyCredential

        materials_index = os.getenv("SEARCH_MATERIALS_INDEX", "exam-materials")

        openai_client = AzureOpenAI(
            azure_endpoint=self._openai_endpoint,
            api_key=self._openai_key,
            api_version="2024-02-01",
        )
        embedding_response = openai_client.embeddings.create(
            input=content[:8000], model=EMBEDDING_MODEL
        )
        embedding = embedding_response.data[0].embedding

        search_client = SearchClient(
            endpoint=self._search_endpoint,
            index_name=materials_index,
            credential=AzureKeyCredential(self._search_key),
        )
        search_client.upload_documents([
            {
                "id": doc_id,
                "session_id": session_id,
                "filename": filename,
                "content": content[:32000],
                "content_vector": embedding,
            }
        ])
        logger.info("Indexed document %s in AI Search index %s", doc_id, materials_index)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get_graph_token(self) -> str:
        """Acquire a Graph API bearer token via client credentials flow."""
        import requests

        token_url = (
            f"https://login.microsoftonline.com/{self._graph_tenant_id}/oauth2/v2.0/token"
        )
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._graph_client_id,
                "client_secret": self._graph_client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["access_token"]
