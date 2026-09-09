import asyncio

import httpx

from api import app as tunnel_app
from mcp_server.http_assets import WORKFLOW_SETTINGS_RUNTIME_ROUTE
from server_http import app


def test_streamable_http_connector_paths_initialize():
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "connector-test", "version": "1"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}

    async def exercise_paths():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                responses = []
                for path in ("/mcp", "/", "/sse"):
                    responses.append(
                        await client.post(path, json=initialize, headers=headers)
                    )
                return responses

    for response in asyncio.run(exercise_paths()):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["mcp-session-id"]
        assert '"result"' in response.text


def test_settings_runtime_is_served_as_a_same_origin_browser_asset(
    monkeypatch,
    tmp_path,
):
    runtime = tmp_path / "workflow-settings-runtime.js"
    runtime.write_text("window.WorkflowSettings = {};", encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_SETTINGS_RUNTIME_PATH", str(runtime))

    async def fetch_runtime(candidate_app):
        transport = httpx.ASGITransport(app=candidate_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(WORKFLOW_SETTINGS_RUNTIME_ROUTE)

    async def fetch_all_runtimes():
        return await asyncio.gather(
            fetch_runtime(app),
            fetch_runtime(tunnel_app),
        )

    responses = asyncio.run(fetch_all_runtimes())

    for response in responses:
        assert response.status_code == 200
        assert response.text == "window.WorkflowSettings = {};"
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
