# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional
import time
import hashlib
import json

from repositories.qa_repo import QARepository


def _now() -> int:
    return int(time.time())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class QAService:
    """对外服务封装：写入、查询、标注、导出、promote占位。"""

    def __init__(self, repo: Optional[QARepository] = None):
        self.repo = repo or QARepository()

    # ---- write flow ----
    def ensure_session(self, session_id: str, domain: str, agent_id: Optional[str] = None, meta: Optional[Dict[str, Any]] = None):
        self.repo.upsert_session(session_id=session_id, domain=domain, agent_id=agent_id, started_at=_now(), meta=meta or {})

    def append_user(self, session_id: str, text: str, tokens: Optional[int] = None, model: Optional[str] = None) -> str:
        turn_id = f"u_{_hash(session_id + text + str(_now()))}"
        self.repo.append_turn(turn_id=turn_id, session_id=session_id, ts=_now(), role="user", text=text, tokens=tokens, model=model, latency_ms=None)
        return turn_id

    def append_assistant(self, session_id: str, text: str, tokens: Optional[int] = None, model: Optional[str] = None, latency_ms: Optional[int] = None) -> str:
        turn_id = f"a_{_hash(session_id + text + str(_now()))}"
        self.repo.append_turn(turn_id=turn_id, session_id=session_id, ts=_now(), role="assistant", text=text, tokens=tokens, model=model, latency_ms=latency_ms)
        return turn_id

    def add_retrieve_event(self, turn_id: str, evidence: Dict[str, Any]):
        ev_id = f"r_{_hash(turn_id + json.dumps(evidence, ensure_ascii=False))}"
        self.repo.add_event(event_id=ev_id, turn_id=turn_id, ts=_now(), type_="retrieve", payload=evidence)
        return ev_id

    def add_tool_event(self, turn_id: str, tool: Dict[str, Any]):
        ev_id = f"t_{_hash(turn_id + json.dumps(tool, ensure_ascii=False))}"
        self.repo.add_event(event_id=ev_id, turn_id=turn_id, ts=_now(), type_="tool", payload=tool)
        return ev_id

    def add_mcp_event(self, turn_id: str, mcp: Dict[str, Any]):
        ev_id = f"m_{_hash(turn_id + json.dumps(mcp, ensure_ascii=False))}"
        self.repo.add_event(event_id=ev_id, turn_id=turn_id, ts=_now(), type_="mcp", payload=mcp)
        return ev_id

    def add_feedback(self, turn_id: str, like: Optional[bool] = None, tags: Optional[List[str]] = None, note: Optional[str] = None):
        payload = {"like": like, "tags": tags or [], "note": note}
        ev_id = f"f_{_hash(turn_id + json.dumps(payload, ensure_ascii=False))}"
        self.repo.add_event(event_id=ev_id, turn_id=turn_id, ts=_now(), type_="feedback", payload=payload)
        return ev_id

    # ---- queries ----
    def list_sessions(self, domain: Optional[str] = None, limit: int = 50, offset: int = 0):
        return self.repo.list_sessions(domain=domain, limit=limit, offset=offset)

    def list_turns(self, session_id: str):
        return self.repo.list_turns(session_id=session_id)

    def list_events(self, turn_id: str):
        return self.repo.list_events(turn_id=turn_id)

    def search(self, keyword: str, domain: Optional[str] = None, limit: int = 50, offset: int = 0):
        return self.repo.search(keyword=keyword, domain=domain, limit=limit, offset=offset)

    # ---- export / promote ----
    def export_session_json(self, session_id: str) -> Dict[str, Any]:
        return self.repo.export_session_json(session_id=session_id)

    def promote_turn_to_doc(self, turn_id: str, domain: str) -> Dict[str, Any]:
        """占位：将问答升级为文档，返回文档结构。UI可调用后续灌注流程。
        这里仅生成一个最小文档结构，后续由灌注脚本写入向量库。
        """
        # 查询 turn 及其上下文
        turns = []
        # 简化：由上层先获取 turns 列表后传入本函数也可，这里为了接口简洁仅返回模板
        doc = {
            "domain": domain,
            "source": "qa_promoted",
            "title": f"QA {turn_id}",
            "text": "",
            "metadata": {
                "turn_id": turn_id,
            }
        }
        return doc
