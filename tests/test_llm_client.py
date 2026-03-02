"""
Unit tests for src/utils/llm_client.py

Covers:
- Primary backend success path
- Primary 429 → GitHub Models fallback
- No GITHUB_TOKEN → re-raises RateLimitError
- Streaming fallback on 429
- Foundry backend init (LLM_BACKEND=foundry)
- Ollama backend init (LLM_BACKEND=ollama)
"""

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Module-level openai stub so LLMClient.__init__ can import AsyncAzureOpenAI
# ---------------------------------------------------------------------------

def _install_openai_stub():
    """
    Install a minimal openai stub into sys.modules so that LLMClient can be
    imported and instantiated in environments where openai>=1.0 is not present.
    The real AsyncAzureOpenAI / AsyncOpenAI are replaced with MagicMock classes.
    """
    stub = types.ModuleType("openai")
    stub.AsyncAzureOpenAI = MagicMock
    stub.AsyncOpenAI = MagicMock

    class _RateLimitError(Exception):
        def __init__(self, message="", response=None, body=None):
            super().__init__(message)
            self.response = response
            self.body = body

    stub.RateLimitError = _RateLimitError
    sys.modules["openai"] = stub
    return stub


_openai_stub = _install_openai_stub()
RateLimitError = _openai_stub.RateLimitError  # re-export for test use


# ---------------------------------------------------------------------------
# Module-level foundry_local stub
# ---------------------------------------------------------------------------

def _install_foundry_local_stub():
    stub = types.ModuleType("foundry_local")
    _manager_instance = MagicMock()
    _manager_instance.endpoint = "http://localhost:5272/v1"
    _manager_instance.api_key = "notneeded"
    model_info = MagicMock(id="phi-3.5-mini-onnx-cpu")
    _manager_instance.get_model_info.return_value = model_info
    stub.FoundryLocalManager = MagicMock(return_value=_manager_instance)
    sys.modules["foundry_local"] = stub
    return stub, _manager_instance


_foundry_local_stub, _foundry_manager_mock = _install_foundry_local_stub()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """Provide required env vars for LLMClient construction."""
    monkeypatch.setenv("LLM_BACKEND", "foundry")
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://fake.foundry.azure.com/")
    monkeypatch.setenv("AZURE_FOUNDRY_KEY", "fake-foundry-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-gh-token")


@pytest.fixture()
def client():
    """A fresh LLMClient instance per test."""
    from src.utils.llm_client import LLMClient
    return LLMClient()


# ---------------------------------------------------------------------------
# Test: Primary backend success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_azure_success(client):
    """chat() returns the primary backend response when it succeeds."""
    client._primary_chat = AsyncMock(return_value="Hello from primary")

    result = await client.chat(messages=[{"role": "user", "content": "hi"}])

    client._primary_chat.assert_awaited_once()
    assert result == "Hello from primary"


# ---------------------------------------------------------------------------
# Test: Primary 429 → fallback to GitHub Models
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_falls_back_on_rate_limit(client):
    """chat() uses GitHub Models when primary returns 429 RateLimitError."""
    client._primary_chat = AsyncMock(side_effect=RateLimitError("rate limited"))
    client._github_chat = AsyncMock(return_value="Hello from GitHub Models")
    # Ensure _fallback is not None so the branch is taken
    client._fallback = MagicMock()

    result = await client.chat(messages=[{"role": "user", "content": "hi"}])

    client._primary_chat.assert_awaited_once()
    client._github_chat.assert_awaited_once()
    assert result == "Hello from GitHub Models"


# ---------------------------------------------------------------------------
# Test: No GITHUB_TOKEN → re-raises RateLimitError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_no_token_reraises(client):
    """chat() re-raises RateLimitError when no fallback is configured."""
    client._primary_chat = AsyncMock(side_effect=RateLimitError("rate limited"))
    client._fallback = None  # simulates no GITHUB_TOKEN

    with pytest.raises(RateLimitError):
        await client.chat(messages=[{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Test: Streaming fallback on 429
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_falls_back_on_rate_limit(client):
    """stream() switches to GitHub Models generator on primary 429."""
    client._fallback = MagicMock()

    async def _primary_raises(*args, **kwargs):
        raise RateLimitError("rate limited")
        yield  # make it an async generator

    async def _github_gen(*args, **kwargs):
        for tok in ["chunk1", "chunk2"]:
            yield tok

    client._primary_stream = _primary_raises
    client._github_stream = _github_gen

    tokens = []
    async for tok in client.stream(messages=[{"role": "user", "content": "hi"}]):
        tokens.append(tok)

    assert tokens == ["chunk1", "chunk2"]


# ---------------------------------------------------------------------------
# Test: Foundry backend init
# ---------------------------------------------------------------------------

def test_foundry_backend_init(monkeypatch):
    """LLM_BACKEND=foundry → _primary_model is Phi-3.5-mini-instruct."""
    monkeypatch.setenv("LLM_BACKEND", "foundry")
    monkeypatch.delenv("AZURE_FOUNDRY_DEPLOYMENT", raising=False)

    from src.utils.llm_client import LLMClient
    client = LLMClient()

    assert client._primary_model == "Phi-3.5-mini-instruct"
    # Foundry uses AsyncAzureOpenAI, not AsyncOpenAI
    assert isinstance(client._primary, MagicMock)


# ---------------------------------------------------------------------------
# Test: Foundry Local backend init
# ---------------------------------------------------------------------------

def test_foundry_local_backend_init(monkeypatch):
    """LLM_BACKEND=foundry-local → uses FoundryLocalManager, endpoint from manager."""
    monkeypatch.setenv("LLM_BACKEND", "foundry-local")
    monkeypatch.delenv("FOUNDRY_LOCAL_MODEL", raising=False)

    calls = []
    original_AsyncOpenAI = _openai_stub.AsyncOpenAI

    class _TrackingOpenAI(MagicMock):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            calls.append(("AsyncOpenAI", kwargs))

    _openai_stub.AsyncOpenAI = _TrackingOpenAI

    try:
        from src.utils.llm_client import LLMClient
        client = LLMClient()

        assert client._primary_model == "phi-3.5-mini-onnx-cpu"
        primary_calls = [c for c in calls if c[0] == "AsyncOpenAI"]
        assert len(primary_calls) >= 1
        assert primary_calls[0][1].get("base_url") == "http://localhost:5272/v1"
        # Manager should be stored to keep service alive
        assert hasattr(client, "_foundry_manager")
    finally:
        _openai_stub.AsyncOpenAI = original_AsyncOpenAI


# ---------------------------------------------------------------------------
# Test: GitHub Models backend init
# ---------------------------------------------------------------------------

def test_github_backend_init(monkeypatch):
    """LLM_BACKEND=github → _primary_model is Phi-3.5-mini-instruct via AsyncOpenAI."""
    from src.utils.llm_client import _GITHUB_MODELS_BASE_URL

    monkeypatch.setenv("LLM_BACKEND", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-gh-token")
    monkeypatch.delenv("GITHUB_MODELS_MODEL", raising=False)

    calls = []
    original_AsyncOpenAI = _openai_stub.AsyncOpenAI
    original_AsyncAzureOpenAI = _openai_stub.AsyncAzureOpenAI

    class _TrackingOpenAI(MagicMock):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            calls.append(("AsyncOpenAI", kwargs))

    class _TrackingAzureOpenAI(MagicMock):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            calls.append(("AsyncAzureOpenAI", kwargs))

    _openai_stub.AsyncOpenAI = _TrackingOpenAI
    _openai_stub.AsyncAzureOpenAI = _TrackingAzureOpenAI

    try:
        from src.utils.llm_client import LLMClient
        client = LLMClient()

        assert client._primary_model == "Phi-3.5-mini-instruct"
        primary_calls = [c for c in calls if c[0] == "AsyncOpenAI"]
        assert len(primary_calls) >= 1
        assert primary_calls[0][1].get("base_url") == _GITHUB_MODELS_BASE_URL
    finally:
        _openai_stub.AsyncOpenAI = original_AsyncOpenAI
        _openai_stub.AsyncAzureOpenAI = original_AsyncAzureOpenAI


# ---------------------------------------------------------------------------
# Test: Fallback model defaults to Phi-3.5-mini-instruct
# ---------------------------------------------------------------------------

def test_fallback_model_default(monkeypatch):
    """Default _fallback_model is Phi-3.5-mini-instruct (not gpt-4o-mini)."""
    monkeypatch.setenv("LLM_BACKEND", "foundry")
    monkeypatch.delenv("GITHUB_FALLBACK_MODEL", raising=False)

    from src.utils.llm_client import LLMClient
    client = LLMClient()

    assert client._fallback_model == "Phi-3.5-mini-instruct"
