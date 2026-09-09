"""HTTP routes for browser assets used by the embedded Workflow MCP App."""
from __future__ import annotations

import os
from pathlib import Path

from starlette.responses import FileResponse, PlainTextResponse
from starlette.routing import Route

WORKFLOW_SETTINGS_RUNTIME_ROUTE = "/assets/workflow-settings-runtime.js"


def workflow_settings_runtime_candidates() -> list[Path]:
    """Return explicit, packaged, then sibling-workspace runtime candidates."""
    configured = os.environ.get("WORKFLOW_SETTINGS_RUNTIME_PATH", "").strip()
    repository_root = Path(__file__).resolve().parents[1]
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            repository_root / "mcp_server" / "assets" / "workflow-settings-runtime.js",
            repository_root.parent
            / "frontend"
            / "packages"
            / "cdns"
            / "for-workflow-settings"
            / "build"
            / "for-workflow-settings.js",
        )
    )
    return candidates


def workflow_settings_runtime_path() -> Path | None:
    """Resolve the first available runtime without requiring a frontend checkout."""
    return next(
        (candidate for candidate in workflow_settings_runtime_candidates() if candidate.is_file()),
        None,
    )


async def serve_workflow_settings_runtime(_request):
    """Serve the packaged UMD from the same public origin as the MCP endpoint."""
    runtime_path = workflow_settings_runtime_path()
    if runtime_path is None:
        return PlainTextResponse(
            "Workflow settings runtime has not been built.",
            status_code=404,
        )
    return FileResponse(
        runtime_path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def register_workflow_ui_asset_routes(app) -> None:
    """Attach browser assets shared by all HTTP transport entrypoints."""
    app.routes.append(
        Route(
            WORKFLOW_SETTINGS_RUNTIME_ROUTE,
            endpoint=serve_workflow_settings_runtime,
            methods=["GET", "HEAD"],
        )
    )
