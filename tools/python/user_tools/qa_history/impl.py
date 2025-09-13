# -*- coding: utf-8 -*-
from __future__ import annotations
"""
QA History 工具（SQLite 主存访问）
- 供 Agent 与前端调用，作为会话/问答记录的单一事实源访问入口
- 入口函数：run(action: str, **kwargs) -> dict
"""
from typing import Any, Dict, List, Optional

from services.qa_service import QAService

_service = QAService()


def run(action: str, **kwargs) -> Dict[str, Any]:
    """统一入口。
    常用动作：
    - ensure_session(session_id, domain, agent_id?, meta?)
    - append_user(session_id, text, tokens?, model?) -> {turn_id}
    - append_assistant(session_id, text, tokens?, model?, latency_ms?) -> {turn_id}
    - add_retrieve_event(turn_id, evidence: dict)
    - add_tool_event(turn_id, tool: dict)
    - add_mcp_event(turn_id, mcp: dict)
    - add_feedback(turn_id, like?, tags?: list[str], note?)
    - list_sessions(domain?, limit?, offset?)
    - list_turns(session_id)
    - list_events(turn_id)
    - export_session_json(session_id)
    """
    try:
        if action == "ensure_session":
            _service.ensure_session(
                session_id=kwargs["session_id"],
                domain=kwargs["domain"],
                agent_id=kwargs.get("agent_id"),
                meta=kwargs.get("meta"),
            )
            return {"ok": True}
        if action == "append_user":
            turn_id = _service.append_user(
                session_id=kwargs["session_id"],
                text=kwargs["text"],
                tokens=kwargs.get("tokens"),
                model=kwargs.get("model"),
            )
            return {"ok": True, "turn_id": turn_id}
        if action == "append_assistant":
            turn_id = _service.append_assistant(
                session_id=kwargs["session_id"],
                text=kwargs["text"],
                tokens=kwargs.get("tokens"),
                model=kwargs.get("model"),
                latency_ms=kwargs.get("latency_ms"),
            )
            return {"ok": True, "turn_id": turn_id}
        if action == "add_retrieve_event":
            ev_id = _service.add_retrieve_event(kwargs["turn_id"], kwargs.get("evidence") or {})
            return {"ok": True, "event_id": ev_id}
        if action == "add_tool_event":
            ev_id = _service.add_tool_event(kwargs["turn_id"], kwargs.get("tool") or {})
            return {"ok": True, "event_id": ev_id}
        if action == "add_mcp_event":
            ev_id = _service.add_mcp_event(kwargs["turn_id"], kwargs.get("mcp") or {})
            return {"ok": True, "event_id": ev_id}
        if action == "add_feedback":
            ev_id = _service.add_feedback(
                kwargs["turn_id"],
                like=kwargs.get("like"),
                tags=kwargs.get("tags"),
                note=kwargs.get("note"),
            )
            return {"ok": True, "event_id": ev_id}
        if action == "list_sessions":
            data = _service.list_sessions(domain=kwargs.get("domain"), limit=int(kwargs.get("limit", 50)), offset=int(kwargs.get("offset", 0)))
            return {"ok": True, "data": data}
        if action == "list_turns":
            data = _service.list_turns(session_id=kwargs["session_id"])
            return {"ok": True, "data": data}
        if action == "list_events":
            data = _service.list_events(turn_id=kwargs["turn_id"])
            return {"ok": True, "data": data}
        if action == "export_session_json":
            data = _service.export_session_json(session_id=kwargs["session_id"])
            return {"ok": True, "data": data}
        return {"ok": False, "error": f"unknown action: {action}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
