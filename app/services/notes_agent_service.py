# -*- coding: utf-8 -*-
"""
NotesAgentService
- 进程内集成 Autogen 0.7.1 内生机制，提供『笔记模式（仅记录）』与『问答模式（调用模型）』能力。
- 统一管理后端 AutogenAgentBackend 的生命周期（惰性创建、复用）。
- 统一补全 MemoryContent.metadata（scene/role/app/page/agent/source/session_id/timestamp/version）。
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, Optional, List

from autogen_client.autogen_backends import AutogenAgentBackend
from autogen_client.config_loader import load_agent_json


class NotesAgentService:
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._backend: Optional[AutogenAgentBackend] = None
        self._session_id = str(uuid.uuid4())
        self._runtime_system_message: str = ""

    # -------- 内部：后端创建与复用 --------
    def _ensure_backend(self) -> AutogenAgentBackend:
        if self._backend is None:
            cfg = load_agent_json(self._config_path)
            # 运行时覆盖 system_message（仅内存态，不落盘）
            if self._runtime_system_message:
                try:
                    cfg = dict(cfg)
                    cfg["system_message"] = self._runtime_system_message
                except Exception:
                    pass
            self._backend = AutogenAgentBackend(agent_config=cfg, log_dir="logs/agent")
        return self._backend

    # -------- 对外：运行时设置系统提示词 --------
    def set_system_message(self, text: str):
        self._runtime_system_message = text or ""
        # 若已存在 backend，更新其 cfg 的 system_message（不重建）
        if self._backend is not None:
            try:
                self._backend.cfg["system_message"] = self._runtime_system_message
            except Exception:
                pass

    # -------- 元数据构造 --------
    def _base_metadata(self) -> Dict[str, Any]:
        return {
            "app": "desktop_app",
            "page": "notes",
            "agent": "笔记助理",
            "session_id": self._session_id,
            "timestamp": int(time.time()),
            "version": "0.7.1",
        }

    # -------- 笔记模式：仅记录，不回答 --------
    def record_only(self, text: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """将文本按 AutoGen 内生内存机制写入当前向量库。
        返回写入统计信息。
        """
        if not text or not isinstance(text, str):
            raise ValueError("record_only: 文本为空或类型错误")
        backend = self._ensure_backend()

        # 解析 memory 对象（使用后端的原生解析逻辑）
        memories = backend._resolve_memory(backend.cfg.get("memory"))  # noqa: E721 (内部方法)
        if not memories:
            return {"written": 0, "memories": 0}

        md = self._base_metadata()
        md.update({
            "scene": "note",
            "role": "user",
            "source": "editor",
        })
        if tags:
            md["tags"] = list(tags)

        # 复用后端的写入流程，构造 entries
        entries = [{"text": text, "metadata": md}]
        backend._write_memory_entries(memories, entries)  # 使用内生 add() 写入流程

        # 返回简单统计
        return {"written": len(entries), "memories": (len(memories) if isinstance(memories, list) else 1)}

    # -------- 问答模式：调用模型问答 --------
    def ask(self, prompt: str) -> str:
        if not prompt or not isinstance(prompt, str):
            raise ValueError("ask: 提示为空或类型错误")
        backend = self._ensure_backend()
        # 直接使用后端的内生 infer_once，内部会根据策略写回问答
        return backend.infer_once(prompt)

    # -------- 显式回忆：直接查询记忆库 --------
    def direct_recall(self, query: str, k: int = 5) -> list[dict]:
        """直接在已解析的 Memory 上执行查询，返回片段摘要列表。
        输出每条包含 content、score（若有）与 metadata（若有）。
        """
        if not query or not isinstance(query, str):
            raise ValueError("direct_recall: 查询为空或类型错误")
        backend = self._ensure_backend()
        memories = backend._resolve_memory(backend.cfg.get("memory"))
        if not memories:
            return []
        mem_list = memories if isinstance(memories, list) else [memories]
        results: list[dict] = []
        for mem in mem_list:
            try:
                if hasattr(mem, "query") and callable(getattr(mem, "query")):
                    items = mem.query(query, k=k)  # AutoGen 内生 Memory.query
                else:
                    continue
                if not items:
                    continue
                for it in items:
                    content = None
                    md = None
                    score = None
                    if isinstance(it, dict):
                        content = it.get("content") or it.get("text") or it.get("document")
                        md = it.get("metadata") or it.get("meta")
                    else:
                        content = str(it)
                    if isinstance(md, dict):
                        score = md.get("score")
                    entry = {"content": content or ""}
                    if score is not None:
                        entry["score"] = float(score)
                    if md:
                        entry["metadata"] = md
                    results.append(entry)
            except Exception:
                continue
        return results
