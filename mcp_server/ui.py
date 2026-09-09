"""MCP Apps resource and presentation tools for workflow UI surfaces."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from mcp.server.apps import Apps, ResourceCsp
from mcp_types import CallToolResult, TextContent
from pydantic import Field

from mcp_server.jotform_client import JotformAPIError, JotformClient
from mcp_server.models import (
    NodeSettingsContextResult,
    UpdateStepResult,
    WorkflowListUIResult,
    WorkflowPreviewUIResult,
)
from mcp_server.tools import building
from mcp_server.tools.reading import (
    form_fields_from_questions,
    read_workflow_list,
    read_workflow_preview,
)

# Bump this whenever the embedded MCP UI or its CSP contract changes. Clients
# cache `ui://` resources by URI, so reusing a version can leave an older host
# unable to load a newly configured settings runtime.
WORKFLOW_UI_RESOURCE_VERSION = 94
WORKFLOW_UI_RESOURCE_URI = (
    f"ui://jotform/workflows/v{WORKFLOW_UI_RESOURCE_VERSION}.html"
)
WORKFLOW_UI_LEGACY_RESOURCE_URIS: tuple[str, ...] = tuple(
    f"ui://jotform/workflows/v{version}.html"
    for version in range(1, WORKFLOW_UI_RESOURCE_VERSION)
)
LOGGER = logging.getLogger(__name__)

# ResourceCsp controls destinations loaded *by* the sandboxed MCP App. Keep
# these as exact origins: wildcard Jotform subdomains would let a compromised
# or user-controlled tenant origin become an allowed script/network source.
WORKFLOW_UI_CONNECT_ORIGINS = ("https://api.jotform.com",)
WORKFLOW_UI_RESOURCE_ORIGINS = (
    "https://www.jotform.com",
    "https://cdn.jotfor.ms",
)

_FALLBACK_HTML = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
  <body style="font-family:system-ui,sans-serif;padding:24px">
    <h2>Workflow preview is unavailable</h2>
    <p>The Workflow MCP UI asset has not been built for this server deployment.</p>
  </body>
</html>
"""


def workflow_settings_runtime_url() -> str | None:
    """Return the explicitly configured HTTPS runtime without guessing a host."""
    value = os.environ.get("WORKFLOW_SETTINGS_RUNTIME_URL", "").strip()
    if not value:
        return None

    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        LOGGER.warning("Ignoring invalid WORKFLOW_SETTINGS_RUNTIME_URL; HTTPS is required.")
        return None
    return value


def _runtime_resource_origin(runtime_url: str | None) -> str | None:
    if not runtime_url:
        return None
    parsed = urlsplit(runtime_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _ui_asset_candidates() -> list[Path]:
    configured = os.environ.get("WORKFLOW_MCP_UI_HTML_PATH")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())

    repository_root = Path(__file__).resolve().parents[1]
    workspace_root = repository_root.parent
    candidates.extend([
        repository_root / "mcp_server" / "assets" / "workflow-mcp-ui.html",
        workspace_root / "frontend" / "packages" / "apps" / "workflow-mcp-ui" / "build" / "mcp-app.html",
    ])
    return candidates


def load_workflow_ui_html() -> str:
    """Load the packaged frontend without making server startup depend on it."""
    for candidate in _ui_asset_candidates():
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")

    LOGGER.warning(
        "Workflow MCP UI asset was not found. Build the frontend resource or set "
        "WORKFLOW_MCP_UI_HTML_PATH. Falling back to a diagnostic page."
    )
    return _FALLBACK_HTML


def create_workflow_apps(client: JotformClient, *, html: str | None = None) -> Apps:
    """Create the UI extension before it is attached to the MCP server."""
    apps = Apps()
    resource_html = html if html is not None else load_workflow_ui_html()
    settings_runtime_url = workflow_settings_runtime_url()
    runtime_resource_origin = _runtime_resource_origin(settings_runtime_url)
    resource_domains = list(WORKFLOW_UI_RESOURCE_ORIGINS)
    if runtime_resource_origin and runtime_resource_origin not in resource_domains:
        resource_domains.append(runtime_resource_origin)

    for resource_uri in (*WORKFLOW_UI_LEGACY_RESOURCE_URIS, WORKFLOW_UI_RESOURCE_URI):
        apps.add_html_resource(
            resource_uri,
            resource_html,
            name="Jotform Workflow UI",
            title="Jotform Workflows",
            description="Read-only workflow list and verified workflow graph preview.",
            csp=ResourceCsp(
                connect_domains=list(WORKFLOW_UI_CONNECT_ORIGINS),
                resource_domains=resource_domains,
                frame_domains=[],
                base_uri_domains=[],
            ),
            prefers_border=True,
        )

    compatibility_meta = {
        "openai/outputTemplate": WORKFLOW_UI_RESOURCE_URI,
        "openai/widgetAccessible": True,
    }
    widget_tool_meta = {
        "openai/widgetAccessible": True,
    }

    @apps.tool(
        resource_uri=WORKFLOW_UI_RESOURCE_URI,
        title="Workflow node settings context",
        meta=widget_tool_meta,
    )
    async def get_node_settings_context(
        workflow_id: Annotated[str, Field(description="Workflow ID containing the selected node.")],
        step_id: Annotated[str, Field(description="Selected workflow element ID.")],
        form_id: Annotated[str, Field(description="Optional trigger form ID used for field tokens.")] = "",
    ) -> NodeSettingsContextResult:
        """Return one node's current config and its form-field token choices for the UI."""
        try:
            config = client.get_element(workflow_id, step_id)
        except JotformAPIError as error:  # Jotform errors are safe data for the UI.
            return NodeSettingsContextResult(
                workflow_id=workflow_id,
                step_id=step_id,
                error=str(error),
            )

        form_fields = []
        warning = None
        if not form_id:
            resolved_form_id, _, _ = building._trigger_form_questions(client, workflow_id)
            form_id = resolved_form_id or ""

        if form_id:
            try:
                form_fields = form_fields_from_questions(client.get_form_questions(form_id))
            except JotformAPIError as error:  # Keep node editing usable with its saved config.
                warning = f"Form fields could not be refreshed: {error}"

        return NodeSettingsContextResult(
            workflow_id=workflow_id,
            step_id=step_id,
            config=config,
            form_fields=form_fields,
            warning=warning,
        )

    @apps.tool(
        resource_uri=WORKFLOW_UI_RESOURCE_URI,
        title="Save workflow node settings",
        meta=widget_tool_meta,
    )
    async def save_node_settings(
        workflow_id: Annotated[str, Field(description="Workflow ID containing the selected node.")],
        step_id: Annotated[str, Field(description="Selected workflow element ID.")],
        config: Annotated[dict, Field(description="Only the node settings changed by the user.")],
    ) -> UpdateStepResult:
        """Persist one node edit through the same updateTree path as update_step."""
        return building.save_step_settings(
            client,
            workflow_id,
            step_id,
            config,
            audit_tool_name="save_node_settings",
        )

    @apps.tool(
        resource_uri=WORKFLOW_UI_RESOURCE_URI,
        title="Jotform Workflows",
        meta={
            **compatibility_meta,
            "openai/toolInvocation/invoking": "Loading workflows…",
            "openai/toolInvocation/invoked": "Workflows loaded",
        },
    )
    async def show_workflows(
        limit: Annotated[int, Field(description="Page size, 1-100. Default 50.")] = 50,
        offset: Annotated[int, Field(description="Zero-based page offset. Default 0.")] = 0,
    ) -> WorkflowListUIResult:
        """
        Show the user's workflows in the interactive workflow list UI.

        Use this presentation tool when the user asks to see, browse, list,
        or choose from their workflows. It reads Jotform directly; never build
        its payload from assistant prose or remembered tool results.
        """
        return WorkflowListUIResult(data=read_workflow_list(client, limit=limit, offset=offset))

    @apps.tool(
        resource_uri=WORKFLOW_UI_RESOURCE_URI,
        title="Jotform Workflow",
        meta={
            **compatibility_meta,
            "openai/toolInvocation/invoking": "Loading workflow…",
            "openai/toolInvocation/invoked": "Workflow loaded",
        },
    )
    async def show_workflow(
        workflow_id: Annotated[
            str,
            Field(description="Workflow id returned by build_workflow_bulk or resolved from list_workflows."),
        ],
    ) -> CallToolResult:
        """
        Show one workflow in the interactive read-only workflow preview UI.

        Use when the user asks to open, show, preview, or inspect a workflow.
        Call immediately after build_workflow_bulk to present the interactive UI
        canvas, or after any other workflow update operations have finished.
        Do NOT insert an extra get_workflow call before show_workflow — build_workflow_bulk
        already returns the complete summary, and show_workflow fetches and verifies the
        live workflow graph internally. Do not call it for intermediate write steps.
        """
        data = read_workflow_preview(client, workflow_id)
        data.settings_runtime_url = settings_runtime_url
        payload = WorkflowPreviewUIResult(data=data)
        structured = payload.model_dump(mode="json", by_alias=True)
        data = structured["data"]
        summary = {
            "view": "workflow-preview",
            "workflow_id": data.get("workflow_id"),
            "workflow_url": data.get("workflow_url"),
            "title": data.get("title"),
            "status": data.get("status"),
            "revision_id": data.get("revision_id"),
            "step_count": len(data.get("step_states") or []),
            "warnings": data.get("warnings") or [],
            "error": data.get("error"),
            "ui_rendered": True,
        }
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(summary, ensure_ascii=False))],
            structured_content=structured,
        )

    return apps
