"""
Azure Function HTTP trigger — GET /api/web

Serves the ExamOps web frontend (src/web/index.html) as a static HTML page.
Auth level is anonymous so users can access the UI without a function key.
"""

import logging
from pathlib import Path

import azure.functions as func

logger = logging.getLogger(__name__)

# Resolve the HTML file path relative to this module's location.
#
# Deployed layout (after workflow staging):
#   /home/site/wwwroot/
#     serve_web/__init__.py   ← this file (staged from src/functions/serve_web)
#     src/web/index.html      ← included in zip from repo root
#     web/index.html          ← also copied by workflow staging step
#
_THIS_DIR = Path(__file__).resolve().parent
# Primary: src/web/index.html under wwwroot (one level up from serve_web/)
_HTML_PATH = _THIS_DIR.parent / "src" / "web" / "index.html"
# Fallback: web/index.html under wwwroot (if workflow stages it there)
_ALT_HTML_PATH = _THIS_DIR.parent / "web" / "index.html"


def _load_html() -> str:
    """Load the frontend HTML from disk, trying both known paths."""
    for candidate in (_HTML_PATH, _ALT_HTML_PATH):
        if candidate.exists():
            logger.debug("Serving HTML from %s", candidate)
            return candidate.read_text(encoding="utf-8")

    # Last-resort inline fallback so the function never 500s
    logger.warning(
        "index.html not found at %s or %s — returning minimal fallback",
        _HTML_PATH,
        _ALT_HTML_PATH,
    )
    return (
        "<!DOCTYPE html><html><head><title>ExamOps</title></head><body>"
        "<h1>ExamOps Orchestrator</h1>"
        "<p>Frontend asset not found. Please redeploy the application.</p>"
        "</body></html>"
    )


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the ExamOps web UI."""
    html = _load_html()
    return func.HttpResponse(
        html,
        status_code=200,
        mimetype="text/html",
        charset="utf-8",
    )
