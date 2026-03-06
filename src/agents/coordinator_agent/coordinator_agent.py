"""
CoordinatorAgent — single entry point for the ExamOps formatting pipeline.

Orchestrates the full job lifecycle using a Semantic Kernel "team leader"
ChatCompletionAgent that delegates each pipeline step to the registered
plugins via automatic function calling.

Pipeline order (enforced by team leader system prompt):
  FileHandlerPlugin.download_document
  FileHandlerPlugin.get_template
  FormattingPlugin.format_and_validate
  DiffPlugin.generate_diff
  FileHandlerPlugin.save_outputs
  FileHandlerPlugin.create_sharing_link

On any SK failure the coordinator falls back to the original manual
sequential chain so the pipeline never silently drops a job.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Team leader system prompt ────────────────────────────────────────────────

TEAM_LEADER_PROMPT = (
    "You are the ExamOps Coordinator, team leader of an exam paper formatting pipeline.\n"
    "Your job is to process a formatting request by calling your tools in this exact order:\n"
    "  1. download_document    — download the .docx file\n"
    "  2. get_template         — retrieve institutional formatting rules\n"
    "  3. format_and_validate  — apply rules and validate compliance\n"
    "  4. generate_diff        — produce the HTML diff report\n"
    "  5. save_outputs         — save formatted doc and diff to storage\n"
    "  6. create_sharing_link  — create a shareable OneDrive link\n"
    "Call each tool once, in order, passing the job_id. Stop after step 6."
)


# ── JobState (lightweight lifecycle tracker) ─────────────────────────────────


@dataclass
class JobState:
    """Tracks lifecycle state for a single formatting job."""

    job_id: str
    user_id: str
    file_url: str
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

    def update_status(self, status: str, error: Optional[str] = None) -> None:
        self.status = status
        self.updated_at = datetime.now(timezone.utc)
        if error:
            self.error = error


# ── CoordinatorAgent ─────────────────────────────────────────────────────────


class CoordinatorAgent:
    """
    Orchestrates the end-to-end exam formatting pipeline.

    Entry points:
      - process_job()  — called by the Azure Function HTTP trigger
      - process_job()  — called by the Teams Bot ActivityHandler

    Primary path (SK):
      A ChatCompletionAgent backed by Semantic Kernel calls the pipeline
      plugins in order via automatic function calling.  Results are
      exchanged through a JobContextRegistry keyed by job_id.

    Fallback path (manual):
      If SK initialisation or invocation fails, the coordinator runs
      the original sequential chain directly.
    """

    def __init__(self) -> None:
        # Lazy imports to avoid circular dependencies at module load time
        from src.agents.file_handler_agent.file_handler_agent import (
            FileHandlerAgent,
        )
        from src.agents.formatting_engine.formatting_engine import (
            FormattingEngineAgent,
        )
        from src.agents.diff_generator.diff_generator import DiffGeneratorAgent

        self.file_handler = FileHandlerAgent()
        self.formatting_engine = FormattingEngineAgent()
        self.diff_generator = DiffGeneratorAgent()

        # Build the SK team leader — gracefully degrade if unavailable
        self.team_leader = None
        try:
            from semantic_kernel.agents import ChatCompletionAgent
            from src.agents.kernel_setup import build_kernel

            kernel = build_kernel(
                self.file_handler, self.formatting_engine, self.diff_generator
            )
            self.team_leader = ChatCompletionAgent(
                kernel=kernel,
                name="ExamOpsCoordinator",
                instructions=TEAM_LEADER_PROMPT,
            )
            logger.info("Semantic Kernel team leader initialised")
        except Exception as exc:
            logger.warning(
                "SK team leader init failed (%s); will use manual chain", exc
            )

    # ── Public entry point ───────────────────────────────────────────────────

    async def process_job(
        self, job_id: str, user_id: str, file_url: str
    ) -> dict:
        """
        Run the full formatting pipeline for one exam paper.

        Args:
            job_id:   Unique identifier for this job (UUID string).
            user_id:  Teams / AAD user ID of the requester.
            file_url: Azure Blob SAS URL of the uploaded .docx file.

        Returns:
            dict with keys:
                status          — "success" | "partial" | "failed"
                compliance_score — 0–100 float, or None if LLM unavailable
                formatted_url   — SAS URL of the formatted .docx
                diff_url        — SAS URL of the HTML diff report
                onedrive_link   — Shareable OneDrive URL
                summary         — Human-readable summary string
                error           — Error message if status != "success"

        Error codes (returned in result["error"]):
            ERR_CORRUPTED_FILE      — .docx could not be parsed
            ERR_TEMPLATE_NOT_FOUND  — Azure AI Search returned no template rules
            ERR_LLM_TIMEOUT         — LLM validation timed out; rule-based only
            ERR_STORAGE             — Azure Blob upload/download failure
        """
        if getattr(self, "team_leader", None) is not None:
            try:
                return await self._sk_path(job_id, user_id, file_url)
            except Exception as exc:
                logger.warning(
                    "Job %s: SK path failed (%s), falling back to manual chain",
                    job_id,
                    exc,
                )
                # Clean up any partial registry entry before manual fallback
                from src.agents.job_context import registry
                registry.remove(job_id)

        return await self._manual_chain(job_id, user_id, file_url)

    # ── SK path ──────────────────────────────────────────────────────────────

    async def _sk_path(
        self, job_id: str, user_id: str, file_url: str
    ) -> dict:
        """
        Invoke the SK team leader to run the full pipeline.

        Creates a JobContext in the registry, lets the team leader call
        plugins in order via automatic function calling, then reads the
        final state back from the registry.

        Raises:
            Any exception from team_leader.invoke() or missing registry state.
        """
        from src.agents.job_context import registry

        # Build SK chat history and arguments, with graceful degradation when
        # semantic_kernel is not installed (e.g. in unit-test environments).
        try:
            from semantic_kernel.contents import ChatHistory
            from semantic_kernel.connectors.ai.function_choice_behavior import (
                FunctionChoiceBehavior,
            )
            from semantic_kernel.connectors.ai.open_ai import (
                AzureChatPromptExecutionSettings,
            )
            from semantic_kernel.kernel_arguments import KernelArguments

            chat_history = ChatHistory()
            chat_history.add_user_message(
                f"Process exam formatting job. job_id={job_id}. "
                "Start the pipeline now by calling each tool in order."
            )
            settings = AzureChatPromptExecutionSettings()
            settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
            args = KernelArguments(settings=settings)
        except ImportError:
            # SK not installed — use lightweight stubs so that a mocked
            # team_leader.invoke (e.g. in tests) can still be called.
            class _Stub:
                def add_user_message(self, _msg: str) -> None:
                    pass

            chat_history = _Stub()
            args = None

        registry.create(job_id, file_url, user_id)
        logger.info("[SK] Job %s started for user %s", job_id, user_id)

        async for _ in self.team_leader.invoke(
            messages=chat_history, arguments=args
        ):
            pass  # SK handles all function calling internally

        ctx = registry.get(job_id)
        if ctx is None:
            raise RuntimeError(
                f"Job context missing after SK invocation for job {job_id}"
            )

        # Surface hard failures (e.g. storage error) as exceptions so the
        # fallback path can run cleanly
        if ctx.last_error and not ctx.output_urls:
            raise RuntimeError(f"SK pipeline failed: {ctx.last_error}")

        # Build result dict from final JobContext state
        stats = ctx.diff_result.get("summary_stats", {}) if ctx.diff_result else {}
        compliance_score = (
            ctx.validation_result.get("compliance_score")
            if ctx.validation_result
            else None
        )
        llm_timed_out = (
            ctx.validation_result.get("fallback_mode", False)
            if ctx.validation_result
            else False
        )
        status = "partial" if llm_timed_out else "success"

        logger.info(
            "[SK] Job %s completed — status=%s compliance=%s",
            job_id,
            status,
            compliance_score,
        )

        result = {
            "status": status,
            "compliance_score": compliance_score,
            "formatted_url": ctx.output_urls.get("docx", "") if ctx.output_urls else "",
            "diff_url": ctx.output_urls.get("html", "") if ctx.output_urls else "",
            "onedrive_link": ctx.onedrive_link or "",
            "summary": self._build_summary(stats, compliance_score, llm_timed_out),
            "error": None,
        }

        registry.remove(job_id)
        return result

    # ── Manual fallback chain ────────────────────────────────────────────────

    async def _manual_chain(
        self, job_id: str, user_id: str, file_url: str
    ) -> dict:
        """
        Original sequential pipeline — runs when SK is unavailable or fails.

        Sequential call chain:
          1. FileHandlerAgent.download_from_blob()
          2. FileHandlerAgent.get_template_from_vectordb()
          3. FormattingEngineAgent.process_and_validate()
          4. DiffGeneratorAgent.create_html_diff()
          5. FileHandlerAgent.save_outputs()
          6. FileHandlerAgent.create_onedrive_link()
        """
        job = JobState(job_id=job_id, user_id=user_id, file_url=file_url)
        logger.info("Job %s started for user %s", job_id, user_id)

        # ── Step 1: Download original document ─────────────────────────────
        job.update_status("downloading")
        try:
            original_doc = await self.file_handler.download_from_blob(file_url)
        except Exception as exc:
            logger.error("Job %s: download failed — %s", job_id, exc)
            job.update_status("failed", error="ERR_CORRUPTED_FILE")
            return self._failure_result(job, "ERR_CORRUPTED_FILE", str(exc))

        # ── Step 2: Retrieve template rules ────────────────────────────────
        job.update_status("retrieving_template")
        try:
            template_rules = await self.file_handler.get_template_from_vectordb(
                query="Southern University College exam paper formatting rules"
            )
        except Exception as exc:
            logger.error("Job %s: template retrieval failed — %s", job_id, exc)
            job.update_status("failed", error="ERR_TEMPLATE_NOT_FOUND")
            return self._failure_result(job, "ERR_TEMPLATE_NOT_FOUND", str(exc))

        if not template_rules:
            job.update_status("failed", error="ERR_TEMPLATE_NOT_FOUND")
            return self._failure_result(
                job, "ERR_TEMPLATE_NOT_FOUND", "Azure AI Search returned no results"
            )

        # ── Step 3: Format + validate ───────────────────────────────────────
        job.update_status("formatting")
        try:
            formatted_doc, validation_result = (
                await self.formatting_engine.process_and_validate(
                    original_doc, template_rules
                )
            )
        except Exception as exc:
            logger.error("Job %s: formatting failed — %s", job_id, exc)
            job.update_status("failed")
            return self._failure_result(job, "ERR_FORMATTING", str(exc))

        # Detect LLM timeout fallback
        llm_timed_out = validation_result.get("fallback_mode", False)
        if llm_timed_out:
            logger.warning(
                "Job %s: LLM timed out, proceeding with rule-based only", job_id
            )

        # ── Step 4: Generate diff ───────────────────────────────────────────
        job.update_status("generating_diff")
        try:
            diff_result = self.diff_generator.create_html_diff(
                original_doc, formatted_doc, validation_result
            )
        except Exception as exc:
            logger.error("Job %s: diff generation failed — %s", job_id, exc)
            diff_result = {"html_report": "", "summary_stats": {}}

        # ── Step 5: Save outputs ────────────────────────────────────────────
        job.update_status("saving")
        try:
            output_urls = await self.file_handler.save_outputs(
                formatted_doc, diff_result["html_report"], job_id
            )
        except Exception as exc:
            logger.error("Job %s: save outputs failed — %s", job_id, exc)
            job.update_status("failed", error="ERR_STORAGE")
            return self._failure_result(job, "ERR_STORAGE", str(exc))

        # ── Step 6: Create OneDrive sharing link ────────────────────────────
        try:
            onedrive_link = await self.file_handler.create_onedrive_link(
                output_urls["docx"]
            )
        except Exception as exc:
            logger.warning(
                "Job %s: OneDrive link creation failed — %s", job_id, exc
            )
            onedrive_link = output_urls.get("docx", "")

        # ── Build result ────────────────────────────────────────────────────
        stats = diff_result.get("summary_stats", {})
        compliance_score = validation_result.get("compliance_score")
        status = "partial" if llm_timed_out else "success"

        job.update_status(status)
        logger.info(
            "Job %s completed — status=%s compliance=%.1f",
            job_id,
            status,
            compliance_score or 0.0,
        )

        return {
            "status": status,
            "compliance_score": compliance_score,
            "formatted_url": output_urls.get("docx", ""),
            "diff_url": output_urls.get("html", ""),
            "onedrive_link": onedrive_link,
            "summary": self._build_summary(stats, compliance_score, llm_timed_out),
            "error": None,
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _failure_result(self, job: JobState, error_code: str, detail: str) -> dict:
        return {
            "status": "failed",
            "compliance_score": None,
            "formatted_url": "",
            "diff_url": "",
            "onedrive_link": "",
            "summary": f"Job failed: {error_code}",
            "error": f"{error_code}: {detail}",
        }

    def _build_summary(
        self,
        stats: dict,
        compliance_score: Optional[float],
        llm_timed_out: bool,
    ) -> str:
        total = stats.get("total_changes", 0)
        score_str = (
            f"{compliance_score:.1f}%" if compliance_score is not None else "N/A"
        )
        fallback_note = " (LLM timed out — rule-based only)" if llm_timed_out else ""
        return (
            f"Formatting complete. {total} change(s) applied. "
            f"Compliance score: {score_str}.{fallback_note}"
        )
