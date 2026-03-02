"""
ExamOps MCP Server — exposes the ExamOps pipeline as callable MCP tools.

Exposed tools:
    upload_syllabus       — upload a syllabus file/URL, extract CLO/PLO
    generate_questions    — chat with the copilot to generate exam questions
    fill_moderation_form  — fill AARO-FM-030 with session questions
    format_exam           — format an exam paper .docx

Run standalone:
    python -m src.mcp.server

Or register with any MCP-compatible host (Claude Desktop, Copilot Studio, etc.)
by pointing it at this module.
"""

import asyncio
import io
import json
import logging
import os

logger = logging.getLogger(__name__)


def _build_server():
    """Build and return the MCP server instance."""
    from mcp.server import Server
    from mcp.server.models import InitializationOptions
    import mcp.types as types

    server = Server("examops-orchestrator")

    # ── Tool: upload_syllabus ──────────────────────────────────────────────

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="upload_syllabus",
                description=(
                    "Upload a syllabus file (.docx or .pdf) or provide a SharePoint URL "
                    "to extract Course Learning Outcomes (CLOs) and Programme Learning "
                    "Outcomes (PLOs). Returns the session ID plus CLO/PLO lists."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Local file path to the syllabus .docx or .pdf",
                        },
                        "sharepoint_url": {
                            "type": "string",
                            "description": "SharePoint sharing URL (use instead of file_path)",
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Existing session ID to reuse (optional)",
                        },
                    },
                },
            ),
            types.Tool(
                name="generate_questions",
                description=(
                    "Chat with the AI copilot to generate exam questions. "
                    "Uses RAG over indexed learning materials. "
                    "Returns a list of question suggestions with CLO mappings and marks."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID from upload_syllabus",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Instruction for the copilot, e.g. 'Generate 3 MCQs on Chapter 2'",
                        },
                    },
                    "required": ["session_id", "prompt"],
                },
            ),
            types.Tool(
                name="fill_moderation_form",
                description=(
                    "Fill the AARO-FM-030 moderation form .docx with all questions in "
                    "the session, including CLO/PLO mapping and marks. "
                    "Returns the Blob Storage download URL of the completed form."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID",
                        },
                    },
                    "required": ["session_id"],
                },
            ),
            types.Tool(
                name="format_exam",
                description=(
                    "Apply exam paper formatting rules to a .docx file. "
                    "Returns the formatted exam URL and a compliance score (0–100)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID",
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Local path to the exam .docx to format",
                        },
                    },
                    "required": ["session_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        try:
            result = await _dispatch_tool(name, arguments)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(exc)}),
                )
            ]

    return server


async def _dispatch_tool(name: str, args: dict) -> dict:
    """Route tool calls to the appropriate agent."""

    if name == "upload_syllabus":
        return await _tool_upload_syllabus(args)

    elif name == "generate_questions":
        return await _tool_generate_questions(args)

    elif name == "fill_moderation_form":
        return await _tool_fill_moderation_form(args)

    elif name == "format_exam":
        return await _tool_format_exam(args)

    else:
        raise ValueError(f"Unknown tool: {name}")


async def _tool_upload_syllabus(args: dict) -> dict:
    from src.session.session_store import SessionStore
    from src.agents.syllabus_agent.syllabus_agent import SyllabusAgent

    store = SessionStore()
    session = store.get_or_create(args.get("session_id"))

    file_bytes: bytes = b""
    filename = "syllabus.docx"

    if args.get("file_path"):
        with open(args["file_path"], "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(args["file_path"])
    elif args.get("sharepoint_url"):
        from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent
        fh = FileHandlerAgent()
        file_bytes = await fh.download_from_sharepoint(args["sharepoint_url"])
        filename = args["sharepoint_url"].split("/")[-1] or filename
    else:
        raise ValueError("Provide 'file_path' or 'sharepoint_url'.")

    agent = SyllabusAgent()
    result = await agent.process(file_bytes, filename, session.session_id)
    return {"session_id": session.session_id, **result}


async def _tool_generate_questions(args: dict) -> dict:
    from src.session.session_store import SessionStore
    from src.agents.question_copilot_agent.question_copilot_agent import (
        QuestionCopilotAgent,
    )

    session_id = args["session_id"]
    prompt = args["prompt"]

    store = SessionStore()
    session = store.get_session(session_id)
    clo_list = session.clo_list if session else []

    agent = QuestionCopilotAgent()
    tokens = []
    async for token in agent.stream(session_id, prompt, clo_list):
        tokens.append(token)

    full_response = "".join(tokens)

    # Parse JSON metadata block from response if present
    suggestion = {}
    if "```json" in full_response:
        try:
            json_str = full_response.split("```json")[1].split("```")[0].strip()
            suggestion = json.loads(json_str)
        except Exception:
            pass

    return {
        "session_id": session_id,
        "response": full_response,
        "suggestion": suggestion,
    }


async def _tool_fill_moderation_form(args: dict) -> dict:
    from src.agents.moderation_form_agent.moderation_form_agent import (
        ModerationFormAgent,
    )

    agent = ModerationFormAgent()
    download_url = await agent.fill_form(args["session_id"])
    return {"session_id": args["session_id"], "download_url": download_url}


async def _tool_format_exam(args: dict) -> dict:
    from src.session.session_store import SessionStore
    from src.agents.file_handler_agent.file_handler_agent import FileHandlerAgent
    from src.agents.coordinator_agent.coordinator_agent import CoordinatorAgent
    import uuid

    session_id = args["session_id"]
    file_path = args.get("file_path")

    if not file_path:
        # Use the questions export as the exam draft
        store = SessionStore()
        session = store.get_session(session_id)
        if session and session.formatted_exam_url:
            return {
                "session_id": session_id,
                "formatted_exam_url": session.formatted_exam_url,
                "compliance_score": session.compliance_score,
            }
        raise ValueError("Provide 'file_path' for the exam .docx to format.")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    fh = FileHandlerAgent()
    blob_url = await fh.upload_to_blob(
        file_stream=io.BytesIO(file_bytes),
        filename=os.path.basename(file_path),
        user_id=session_id,
    )

    job_id = str(uuid.uuid4())
    coordinator = CoordinatorAgent()
    result = await coordinator.process_job(
        job_id=job_id,
        user_id=session_id,
        file_url=blob_url,
    )

    # Update session with result
    try:
        store = SessionStore()
        session = store.get_session(session_id)
        if session:
            session.formatted_exam_url = result.get("formatted_url", "")
            session.compliance_score = result.get("compliance_score") or 0.0
            store.update_session(session)
    except Exception:
        pass

    return {
        "session_id": session_id,
        "formatted_exam_url": result.get("formatted_url", ""),
        "compliance_score": result.get("compliance_score"),
    }


def run():
    """Run the MCP server (stdio transport)."""
    from mcp.server.stdio import stdio_server

    server = _build_server()

    async def _run():
        from mcp.server.models import InitializationOptions
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="examops-orchestrator",
                    server_version="1.0.0",
                ),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    run()
