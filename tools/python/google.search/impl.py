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


def _build_params(query: str, num: int, site: Optional[str], safe: Optional[str], dateRestrict: Optional[str]) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "q": query,
        "num": max(1, min(int(num), 10)),  # Google API 单次最多 10 条
    }
    if site:
        p["siteSearch"] = site
    if safe in {"active", "off", "high", "medium"}:  # 兼容不同文档表述
        p["safe"] = safe
    if dateRestrict:
        p["dateRestrict"] = dateRestrict
    return p


def run(query: str, num: int = 5, site: str | None = None, safe: str | None = None, dateRestrict: str | None = None) -> Dict[str, Any]:
    api_key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")
    print(f"[DEBUG] Google搜索工具 - API_KEY: {'存在' if api_key else '缺失'}")
    print(f"[DEBUG] Google搜索工具 - CSE_CX: {'存在' if cx else '缺失'}")
    print(f"[DEBUG] Google搜索工具 - 查询: {query}")
    if not api_key or not cx:
        error_msg = "缺少 GOOGLE_API_KEY 或 GOOGLE_CSE_CX 环境变量"
        print(f"[DEBUG] Google搜索工具错误: {error_msg}")
        raise RuntimeError(error_msg)

    url = "https://www.googleapis.com/customsearch/v1"
    params = _build_params(query, num, site, safe, dateRestrict)
    params["key"] = api_key
    params["cx"] = cx

    try:
        resp = requests.get(url, params=params, timeout=30)
    except Exception as e:
        raise RuntimeError(f"Google 搜索请求异常：{e}")

    if resp.status_code != 200:
        text = (resp.text or "")[:500]
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
    return {"items": outputs, "count": len(outputs)}
