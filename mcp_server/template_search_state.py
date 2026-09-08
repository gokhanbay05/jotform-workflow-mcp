"""Track template discovery completed during the active MCP session."""
from __future__ import annotations

import threading
import time

from mcp_server.telemetry_context import get_current_session_id


_SEARCH_TTL_SECONDS = 60 * 60
_searches: dict[str, float] = {}
_lock = threading.Lock()


def mark_template_search() -> None:
    session_id = get_current_session_id()
    if not session_id:
        return
    now = time.monotonic()
    with _lock:
        _searches[session_id] = now
        _prune(now)


def template_search_completed() -> bool:
    """Return whether discovery ran in the active MCP session.

    Direct helper calls have no MCP session context, so local scripts and unit
    tests remain usable; live MCP tool calls always bind a session.
    """
    session_id = get_current_session_id()
    if not session_id:
        return True
    now = time.monotonic()
    with _lock:
        searched_at = _searches.get(session_id)
        _prune(now)
    return searched_at is not None and now - searched_at <= _SEARCH_TTL_SECONDS


def _prune(now: float) -> None:
    for session_id, searched_at in list(_searches.items()):
        if now - searched_at > _SEARCH_TTL_SECONDS:
            del _searches[session_id]
