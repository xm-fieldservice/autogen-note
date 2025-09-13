# -*- coding: utf-8 -*-
"""
Google Custom Search (Programmable Search Engine) 工具实现
- 放置于客户端内，供前端仓库与 Agent 集成使用
- 依赖 AutoGen 0.7.1 的 HttpTool 发起真实外网请求
- 需要环境变量：GOOGLE_API_KEY、GOOGLE_CSE_CX

入口函数：run(query: str, num: int = 5, site: str | None = None, safe: str | None = None, dateRestrict: str | None = None)
返回：{"items": [{"title": str, "link": str, "snippet": str}], "count": int}
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import requests
import json
from datetime import datetime


def _ensure_log_dir(path: str) -> None:
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass


def _log_tool_event(event: Dict[str, Any]) -> None:
    """Append a JSON line to logs/agent/tools.log for observability."""
    try:
        log_path = os.path.join("logs", "agent", "tools.log")
        _ensure_log_dir(log_path)
        event = {**event, "ts": datetime.utcnow().isoformat()}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Logging must never break tool execution
        pass


def _build_params(query: str, num: int, site: Optional[str], safe: Optional[str], dateRestrict: Optional[str]) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "q": query,
        "num": max(1, min(int(num), 8)),  # 限制为8条，便于总结梳理
    }
    if site:
        p["siteSearch"] = site
    if safe in {"active", "off", "high", "medium"}:  # 兼容不同文档表述
        p["safe"] = safe
    if dateRestrict:
        p["dateRestrict"] = dateRestrict
    return p


def run(
    query: str,
    num: int = 10,
    site: str | None = None,
    safe: str | None = None,
    dateRestrict: str | None = None,
    days: int | None = None,
) -> Dict[str, Any]:
    api_key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")
    if not api_key or not cx:
        err = "缺少 GOOGLE_API_KEY 或 GOOGLE_CSE_CX 环境变量"
        _log_tool_event({
            "tool": "google.search",
            "stage": "env_check",
            "ok": False,
            "error": err,
        })
        raise RuntimeError(err)

    url = "https://www.googleapis.com/customsearch/v1"
    # 优先使用 days 映射到 dateRestrict: dN
    if days is not None and days >= 0:
        try:
            dateRestrict = f"d{int(days)}"
        except Exception:
            pass

    params = _build_params(query, num, site, safe, dateRestrict)
    params["key"] = api_key
    params["cx"] = cx

    _log_tool_event({
        "tool": "google.search",
        "stage": "request",
        "ok": True,
        "query": query,
        "params": {k: v for k, v in params.items() if k not in {"key", "cx"}},
    })

    try:
        resp = requests.get(url, params=params, timeout=30)
    except Exception as e:
        _log_tool_event({
            "tool": "google.search",
            "stage": "request",
            "ok": False,
            "error": f"exception: {e}",
        })
        raise RuntimeError(f"Google 搜索请求异常：{e}")

    if resp.status_code != 200:
        text = (resp.text or "")[:500]
        _log_tool_event({
            "tool": "google.search",
            "stage": "response",
            "ok": False,
            "status": resp.status_code,
            "body": text,
        })
        raise RuntimeError(f"Google 搜索请求失败：status={resp.status_code}, body={text}")

    try:
        data = resp.json() or {}
    except Exception:
        data = {}
    items = data.get("items") or []
    outputs: List[Dict[str, Any]] = []
    for it in items:
        outputs.append({
            "title": it.get("title"),
            "link": it.get("link"),
            "snippet": it.get("snippet"),
        })
    result = {"items": outputs, "count": len(outputs)}
    _log_tool_event({
        "tool": "google.search",
        "stage": "done",
        "ok": True,
        "count": result["count"],
    })
    return result
