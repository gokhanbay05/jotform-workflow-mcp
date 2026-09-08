"""Track template discovery completed during the active MCP session."""
from __future__ import annotations

import threading
import time

from mcp_server.telemetry_context import get_current_session_id


_SEARCH_TTL_SECONDS = 60 * 60
_searches: dict[str, float] = {}
_template_backed_forms: dict[str, float] = {}
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


def mark_template_backed_form(form_id: str) -> None:
    """Remember that an AI form was created after discovery."""
    if not form_id or not template_search_completed():
        return
    now = time.monotonic()
    with _lock:
        _template_backed_forms[str(form_id)] = now
        _prune(now)


def template_search_completed_for_form(form_id: str) -> bool:
    """Allow a template-backed trigger form across connector session boundaries."""
    if template_search_completed():
        return True
    if not form_id:
        return False
    now = time.monotonic()
    with _lock:
        searched_at = _template_backed_forms.get(str(form_id))
        _prune(now)
    return searched_at is not None and now - searched_at <= _SEARCH_TTL_SECONDS


def _prune(now: float) -> None:
    for session_id, searched_at in list(_searches.items()):
        if now - searched_at > _SEARCH_TTL_SECONDS:
            del _searches[session_id]
    for form_id, searched_at in list(_template_backed_forms.items()):
        if now - searched_at > _SEARCH_TTL_SECONDS:
            del _template_backed_forms[form_id]
