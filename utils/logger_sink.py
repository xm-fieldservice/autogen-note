"""
Centralized logging sink gateway for MCP save_message.

This module enforces:
- role whitelist: only {"user", "assistant"}
- content filters: drop ephemeral/system/thought-like messages
- dedup/rate-limit within a short window
- per-turn idempotency for assistant messages (optional hook)

Actual sending is delegated to a pluggable callable to avoid
hard-coupling with any specific MCP client at import time.

Usage:
- set_sink_callable(callable): register the function that actually sends
  to MCP (e.g., windsorf sink MCP client). The callable signature:
  (session_id: str, role: str, content: str, meta: dict, **kwargs) -> dict
- log_user_message(session_id, content, meta=None, **kwargs)
- log_assistant_message(session_id, content, meta=None, **kwargs)

If no sink callable is registered, messages are skipped with reason
"no_sink_callable".
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable, Dict, Optional, Tuple

_ALLOWED_ROLES = {"user", "assistant"}
_BLOCK_MARKERS = (
    "<ephemeral_message>",
    "Thought for ",
)

_recent: Dict[Tuple[str, str], float] = {}
_recent_ttl_sec: float = 7.0
_sink_callable: Optional[Callable[..., Dict]] = None

# Optional per-turn assistant idempotency flag map: session_id -> bool
_assistant_saved_this_turn: Dict[str, bool] = {}


def set_sink_callable(fn: Callable[..., Dict]) -> None:
    global _sink_callable
    _sink_callable = fn


def reset_turn(session_id: str) -> None:
    """Call this at the start of a new user turn to allow one assistant save."""
    _assistant_saved_this_turn[session_id] = False


def _hash(role: str, content: str, max_len: int = 2048) -> str:
    payload = (role + "\n" + (content or "")[:max_len]).encode("utf-8", errors="ignore")
    return hashlib.sha1(payload).hexdigest()


def _should_skip(session_id: str, role: str, content: str, *, is_assistant: bool) -> Tuple[bool, str]:
    if role not in _ALLOWED_ROLES:
        return True, "role_filtered"
    for marker in _BLOCK_MARKERS:
        if marker in (content or ""):
            return True, "content_filtered"

    # Per-turn assistant idempotency (allow only once per turn)
    if is_assistant:
        if _assistant_saved_this_turn.get(session_id):
            return True, "assistant_idempotent"

    # Dedup/rate-limit
    now = time.time()
    h = _hash(role, content)
    key = (session_id, h)
    last = _recent.get(key)
    if last is not None and (now - last) < _recent_ttl_sec:
        return True, "dedup_rate_limited"
    _recent[key] = now

    # GC
    if len(_recent) > 2048:
        cutoff = now - _recent_ttl_sec
        for k, ts0 in list(_recent.items()):
            if ts0 < cutoff:
                _recent.pop(k, None)

    return False, ""


def _send(session_id: str, role: str, content: str, meta: Optional[Dict] = None, **kwargs) -> Dict:
    if _sink_callable is None:
        return {"skipped": True, "reason": "no_sink_callable"}
    try:
        return _sink_callable(session_id=session_id, role=role, content=content, meta=meta or {}, **kwargs)
    except Exception as e:
        return {"skipped": True, "reason": f"sink_error:{type(e).__name__}"}


def log_user_message(session_id: str, content: str, meta: Optional[Dict] = None, **kwargs) -> Dict:
    skipped, reason = _should_skip(session_id, "user", content or "", is_assistant=False)
    if skipped:
        return {"skipped": True, "reason": reason}
    # New user turn: reset assistant idempotency
    _assistant_saved_this_turn[session_id] = False
    return _send(session_id, "user", content, meta, **kwargs)


def log_assistant_message(session_id: str, content: str, meta: Optional[Dict] = None, **kwargs) -> Dict:
    skipped, reason = _should_skip(session_id, "assistant", content or "", is_assistant=True)
    if skipped:
        return {"skipped": True, "reason": reason}
    # Mark assistant saved for this turn
    _assistant_saved_this_turn[session_id] = True
    return _send(session_id, "assistant", content, meta, **kwargs)
