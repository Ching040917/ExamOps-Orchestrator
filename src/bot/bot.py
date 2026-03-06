"""
ExamOpsBot — Microsoft Teams bot.

Accepts a .docx attachment, triggers the formatting pipeline via CoordinatorAgent,
and replies with an adaptive card summarising the results.
"""

import io
import logging
import uuid

import requests
from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.schema import Activity, Attachment

logger = logging.getLogger(__name__)

# Adaptive card template — filled at runtime.
_RESULT_CARD_TEMPLATE = {
    "type": "AdaptiveCard",
    "version": "1.4",
    "body": [],
    "actions": [],
}


def _build_result_card(result: dict) -> dict:
    """Build an adaptive card dict from a CoordinatorAgent result."""
    score = result.get("compliance_score")
    score_text = f"{score}%" if score is not None else "N/A (rule-based only)"
    status = result.get("status", "unknown")
    summary = result.get("summary", "")

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "ExamOps Formatting Complete",
                "weight": "Bolder",
                "size": "Large",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Status", "value": status.capitalize()},
                    {"title": "Compliance Score", "value": score_text},
                    {"title": "Summary", "value": summary or "—"},
                ],
            },
        ],
        "actions": [],
    }

    if result.get("onedrive_link"):
        card["actions"].append(
            {
                "type": "Action.OpenUrl",
                "title": "Open Formatted Document",
                "url": result["onedrive_link"],
            }
        )

    if result.get("diff_url"):
        card["actions"].append(
            {
                "type": "Action.OpenUrl",
                "title": "View Diff Report",
                "url": result["diff_url"],
            }
        )

    return card


def _adaptive_card_attachment(card: dict) -> Attachment:
    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card,
    )


class ExamOpsBot(ActivityHandler):
    """Teams bot that handles .docx uploads and returns formatted exam results."""

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity: Activity = turn_context.activity

        # Check for .docx attachment
        docx_attachment = None
        if activity.attachments:
            for att in activity.attachments:
                name = att.name or ""
                if name.lower().endswith(".docx"):
                    docx_attachment = att
                    break

        if docx_attachment is None:
            await turn_context.send_activity(
                MessageFactory.text(
                    "Hi! Please attach a **.docx** exam paper and I'll format it for you.\n\n"
                    "**Usage**: Attach a `.docx` file to your message and send it."
                )
            )
            return

        # Identify the sender
        user_id = (
            activity.from_property.id
            if activity.from_property
            else "unknown"
        )

        await turn_context.send_activity(
            MessageFactory.text("Received your document. Processing — this may take a moment...")
        )

        # Download the attachment
        try:
            resp = requests.get(docx_attachment.content_url, timeout=30)
            resp.raise_for_status()
            file_bytes = resp.content
            filename = docx_attachment.name or "upload.docx"
        except Exception as exc:
            logger.exception("Failed to download attachment from Teams")
            await turn_context.send_activity(
                MessageFactory.text(f"Could not download the attachment: {exc}")
            )
            return

        # Upload to Blob Storage
        try:
            from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent

            file_handler = FileHandlerAgent()
            blob_url = await file_handler.upload_to_blob(
                file_stream=io.BytesIO(file_bytes),
                filename=filename,
                user_id=user_id,
            )
        except Exception as exc:
            logger.exception("Blob upload failed in bot")
            await turn_context.send_activity(
                MessageFactory.text(f"Failed to upload your document to storage: {exc}")
            )
            return

        # Run pipeline
        try:
            from src.agents.coordinator_agent.coordinator_agent import CoordinatorAgent

            coordinator = CoordinatorAgent()
            job_id = str(uuid.uuid4())
            result = await coordinator.process_job(
                job_id=job_id,
                user_id=user_id,
                file_url=blob_url,
            )
        except Exception as exc:
            logger.exception("Pipeline failed in bot for user_id=%s", user_id)
            await turn_context.send_activity(
                MessageFactory.text(f"Pipeline failed unexpectedly: {exc}")
            )
            return

        if result.get("status") == "failed":
            await turn_context.send_activity(
                MessageFactory.text(
                    f"Processing failed: {result.get('error', 'Unknown error')}. "
                    "Please check your document and try again."
                )
            )
            return

        # Send result adaptive card
        card = _build_result_card(result)
        card_attachment = _adaptive_card_attachment(card)
        reply = MessageFactory.attachment(card_attachment)
        await turn_context.send_activity(reply)
