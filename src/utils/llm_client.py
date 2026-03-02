"""
LLMClient — Unified LLM client with multi-backend primary + GitHub Models fallback.

Selects the primary backend via the LLM_BACKEND env var:
  "foundry" (default) — Azure AI Foundry → Phi-3.5-mini-instruct
  "github"            — GitHub Models → Phi-3.5-mini-instruct (requires GITHUB_TOKEN only)
  "foundry-local"     — Foundry Local → Phi-3.5-mini (on-device, OpenAI-compat)
  "azure"             — Azure OpenAI → GPT-4o-mini (legacy)

GitHub Models stays as a last-resort 429 fallback for all backends.

Environment variables:
    LLM_BACKEND                — "foundry" | "github" | "foundry-local" | "azure"
                                 (default: foundry)

    # Foundry backend (default):
    AZURE_FOUNDRY_ENDPOINT     — Azure AI Foundry endpoint
    AZURE_FOUNDRY_KEY          — Azure AI Foundry key
    AZURE_FOUNDRY_DEPLOYMENT   — model deployment name (default: Phi-3.5-mini-instruct)

    # GitHub Models backend:
    GITHUB_MODELS_MODEL        — model name (default: Phi-3.5-mini-instruct)

    # Foundry Local backend:
    FOUNDRY_LOCAL_MODEL        — model alias (default: phi-3.5-mini)

    # Azure backend (legacy):
    AZURE_OPENAI_ENDPOINT      — Azure OpenAI endpoint
    AZURE_OPENAI_KEY           — Azure OpenAI key
    AZURE_OPENAI_DEPLOYMENT    — deployment name (default: gpt-4o-mini)

    # Fallback (all backends):
    GITHUB_TOKEN               — GitHub personal access token (fallback on 429)
                                 Grant models:read permission.
                                 https://github.com/settings/tokens
    GITHUB_FALLBACK_MODEL      — model used for 429 fallback (default: Phi-3.5-mini-instruct)

Rate limits (GitHub Models free tier):
    Phi-3.5-mini-instruct : 150 req/day, 15 req/min, 8000 tokens in / 4000 out
    Phi-4                 : 150 req/day, 15 req/min, 8000 tokens in / 4000 out
"""

import logging
import os

logger = logging.getLogger(__name__)

_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"
_GITHUB_MAX_TOKENS = 4000  # GitHub Models output cap


class LLMClient:
    """
    Unified LLM client: configurable primary backend → GitHub Models fallback.

    Usage (non-streaming)::

        client = LLMClient()
        text = await client.chat(messages=[{"role": "user", "content": "Hello"}])

    Usage (streaming)::

        async for chunk in client.stream(messages):
            yield chunk
    """

    def __init__(self) -> None:
        from openai import AsyncAzureOpenAI, AsyncOpenAI

        backend = os.getenv("LLM_BACKEND", "foundry").lower()

        if backend == "github":
            self._primary = AsyncOpenAI(
                base_url=_GITHUB_MODELS_BASE_URL,
                api_key=os.getenv("GITHUB_TOKEN", ""),
            )
            self._primary_model = os.getenv(
                "GITHUB_MODELS_MODEL", "Phi-3.5-mini-instruct"
            )

        elif backend == "foundry-local":
            from foundry_local import FoundryLocalManager
            alias = os.getenv("FOUNDRY_LOCAL_MODEL", "phi-3.5-mini")
            self._foundry_manager = FoundryLocalManager(alias)
            self._primary = AsyncOpenAI(
                base_url=self._foundry_manager.endpoint,
                api_key=self._foundry_manager.api_key,
            )
            self._primary_model = self._foundry_manager.get_model_info(alias).id

        elif backend == "foundry":
            self._primary = AsyncAzureOpenAI(
                azure_endpoint=os.getenv("AZURE_FOUNDRY_ENDPOINT", ""),
                api_key=os.getenv("AZURE_FOUNDRY_KEY", ""),
                api_version="2024-02-01",
            )
            self._primary_model = os.getenv(
                "AZURE_FOUNDRY_DEPLOYMENT", "Phi-3.5-mini-instruct"
            )

        else:  # "azure" — original behaviour
            self._primary = AsyncAzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                api_key=os.getenv("AZURE_OPENAI_KEY", ""),
                api_version="2024-02-01",
            )
            self._primary_model = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

        gh_token = os.getenv("GITHUB_TOKEN")
        self._fallback = (
            AsyncOpenAI(
                base_url=_GITHUB_MODELS_BASE_URL,
                api_key=gh_token,
            )
            if gh_token
            else None
        )
        self._fallback_model = os.getenv(
            "GITHUB_FALLBACK_MODEL", "Phi-3.5-mini-instruct"
        )

    async def chat(
        self,
        messages: list,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> str:
        """
        Non-streaming completion. Tries the primary backend first, falls back to
        GitHub Models on 429 RateLimitError.

        Returns:
            Assistant message content string.

        Raises:
            openai.RateLimitError: if both primary and GitHub Models are unavailable.
        """
        from openai import RateLimitError

        try:
            return await self._primary_chat(messages, temperature, max_tokens)
        except RateLimitError:
            if self._fallback is None:
                logger.error(
                    "Primary LLM 429 and no GITHUB_TOKEN fallback configured"
                )
                raise
            logger.warning(
                "Primary LLM rate limited (429) → falling back to GitHub Models"
            )
            return await self._github_chat(messages, temperature, max_tokens)

    async def stream(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        """
        Streaming completion. Yields token strings.
        Falls back to GitHub Models on 429.

        Usage::

            async for token in client.stream(messages):
                print(token, end="")
        """
        from openai import RateLimitError

        try:
            async for token in self._primary_stream(messages, temperature, max_tokens):
                yield token
        except RateLimitError:
            if self._fallback is None:
                logger.error(
                    "Primary LLM 429 and no GITHUB_TOKEN fallback configured"
                )
                raise
            logger.warning(
                "Primary LLM rate limited (429) during streaming → "
                "falling back to GitHub Models"
            )
            async for token in self._github_stream(messages, temperature, max_tokens):
                yield token

    # ── Primary backend ───────────────────────────────────────────────────────

    async def _primary_chat(self, messages, temperature, max_tokens) -> str:
        response = await self._primary.chat.completions.create(
            model=self._primary_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def _primary_stream(self, messages, temperature, max_tokens):
        stream = await self._primary.chat.completions.create(
            model=self._primary_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ── GitHub Models fallback ────────────────────────────────────────────────

    async def _github_chat(self, messages, temperature, max_tokens) -> str:
        capped = min(max_tokens, _GITHUB_MAX_TOKENS)
        response = await self._fallback.chat.completions.create(
            model=self._fallback_model,
            messages=messages,
            temperature=temperature,
            max_tokens=capped,
        )
        return response.choices[0].message.content

    async def _github_stream(self, messages, temperature, max_tokens):
        capped = min(max_tokens, _GITHUB_MAX_TOKENS)
        stream = await self._fallback.chat.completions.create(
            model=self._fallback_model,
            messages=messages,
            temperature=temperature,
            max_tokens=capped,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
