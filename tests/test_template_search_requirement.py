from mcp_server import template_search_state
from mcp_server.telemetry_context import bind_context
from mcp_server.tools import templates


class DummyMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def test_template_search_marks_the_active_mcp_session(monkeypatch):
    mcp = DummyMCP()
    templates.register(mcp)
    monkeypatch.setattr(
        templates,
        "search_templates_tool",
        lambda query, top_k: templates.TemplateSearchResult(
            query=query,
            normalized_query=query,
            count=0,
            templates=[],
        ),
    )

    with bind_context(session_id="template-search-session"):
        assert template_search_state.template_search_completed() is False
        mcp.tools["search_workflow_templates"]("help desk workflow")
        assert template_search_state.template_search_completed() is True
