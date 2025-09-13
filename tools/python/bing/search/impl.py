# -*- coding: utf-8 -*-
"""
Bing Web Search 工具实现（Azure Cognitive Services）
- 放在客户端内，供前端仓库与 Agent 集成
- 使用 requests 发起真实外网请求（避免 HttpTool 版本差异导致的构造不兼容）
- 需要环境变量：
  - BING_SEARCH_KEY：Azure Bing Web Search 的订阅密钥
  - BING_ENDPOINT（可选）：自定义端点，默认 https://api.bing.microsoft.com

入口：run(query: str, count: int = 5, mkt: str = "zh-CN", safe: str = "Moderate")
返回：{"items": [{"title": str, "link": str, "snippet": str}], "count": int}
"""
from __future__ import annotations

import os
from typing import Any, Dict, List
import requests


def run(query: str, count: int = 5, mkt: str = "zh-CN", safe: str = "Moderate") -> Dict[str, Any]:
    key = os.getenv("BING_SEARCH_KEY")
    if not key:
        raise RuntimeError("缺少 BING_SEARCH_KEY 环境变量（Azure Bing 订阅密钥）")

    endpoint = os.getenv("BING_ENDPOINT") or "https://api.bing.microsoft.com"
    base = endpoint.rstrip("/")
    # Support both global and regional endpoints
    # - Global legacy: https://api.bing.microsoft.com/v7.0/search
    # - Azure regional: https://<region>.cognitiveservices.azure.com/bing/v7.0/search
    if "cognitiveservices.azure.com" in base:
        url = base + "/bing/v7.0/search"
    else:
        url = base + "/v7.0/search"

    params = {
        "q": query,
        "count": max(1, min(int(count), 50)),  # Bing 默认最多50/次
        "mkt": mkt,
        "safeSearch": safe,  # Off | Moderate | Strict
        # 也可加入 "responseFilter": "Webpages"
    }

    headers = {
        "Ocp-Apim-Subscription-Key": key,
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
    except Exception as e:
        raise RuntimeError(f"Bing 搜索请求异常：{e}")

    if resp.status_code != 200:
        text = (resp.text or "")[:500]
        raise RuntimeError(f"Bing 搜索请求失败：status={resp.status_code}, body={text}")

    try:
        data = resp.json() or {}
    except Exception:
        data = {}
    web = (data.get("webPages") or {}).get("value") or []
    items: List[Dict[str, Any]] = []
    for it in web:
        items.append({
            "title": it.get("name"),
            "link": it.get("url"),
            "snippet": it.get("snippet"),
        })

    return {"items": items, "count": len(items)}
