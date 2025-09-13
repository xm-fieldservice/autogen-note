# -*- coding: utf-8 -*-
"""
智能网络查询工具实现
- 基于Google搜索获取相关链接
- 抓取网页内容并提取关键信息
- 生成结构化答案
"""
from __future__ import annotations

import os
import json
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
import re
from bs4 import BeautifulSoup


def _ensure_log_dir(path: str) -> None:
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass


def _log_tool_event(event: Dict[str, Any]) -> None:
    """记录工具执行事件"""
    try:
        log_path = os.path.join("logs", "agent", "tools.log")
        _ensure_log_dir(log_path)
        event = {**event, "ts": datetime.utcnow().isoformat()}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _google_search(query: str, num: int = 5) -> List[Dict[str, str]]:
    """执行Google搜索获取链接列表"""
    api_key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")
    if not api_key or not cx:
        raise RuntimeError("缺少 GOOGLE_API_KEY 或 GOOGLE_CSE_CX 环境变量")

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "num": min(num, 8),
        "key": api_key,
        "cx": cx
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Google搜索失败：status={resp.status_code}")
        
        data = resp.json() or {}
        items = data.get("items", [])
        return [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", "")
            }
            for item in items
        ]
    except Exception as e:
        _log_tool_event({
            "tool": "smart_web_query",
            "stage": "google_search",
            "ok": False,
            "error": str(e)
        })
        raise


def _extract_text_from_html(html_content: str) -> str:
    """从HTML中提取主要文本内容"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 移除脚本和样式标签
        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script.decompose()
        
        # 优先提取主要内容区域
        main_content = None
        for selector in ['main', 'article', '.content', '.main-content', '#content', '#main']:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        if main_content:
            text = main_content.get_text()
        else:
            text = soup.get_text()
        
        # 清理文本
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        # 限制长度避免过长
        return text[:5000] if len(text) > 5000 else text
    except Exception:
        return ""


def _fetch_webpage_content(url: str) -> Dict[str, str]:
    """获取网页内容"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        # 尝试检测编码
        if resp.encoding == 'ISO-8859-1':
            resp.encoding = resp.apparent_encoding
        
        content = _extract_text_from_html(resp.text)
        return {
            "url": url,
            "content": content,
            "success": True,
            "error": None
        }
    except Exception as e:
        return {
            "url": url,
            "content": "",
            "success": False,
            "error": str(e)
        }


def _is_valid_url(url: str) -> bool:
    """检查URL是否有效"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def run(
    query: str,
    max_results: int = 5,
    max_content_sources: int = 3,
    include_snippets: bool = True
) -> Dict[str, Any]:
    """
    智能网络查询主函数
    
    Args:
        query: 搜索查询
        max_results: 最大搜索结果数
        max_content_sources: 最大内容抓取源数量
        include_snippets: 是否包含搜索片段
    
    Returns:
        包含搜索结果、网页内容和结构化信息的字典
    """
    _log_tool_event({
        "tool": "smart_web_query",
        "stage": "start",
        "ok": True,
        "query": query,
        "max_results": max_results,
        "max_content_sources": max_content_sources
    })
    
    try:
        # 1. 执行Google搜索
        search_results = _google_search(query, max_results)
        
        if not search_results:
            return {
                "query": query,
                "search_results": [],
                "web_contents": [],
                "summary": "未找到相关搜索结果",
                "sources": []
            }
        
        # 2. 获取网页内容
        web_contents = []
        valid_urls = [item["link"] for item in search_results if _is_valid_url(item["link"])]
        
        for i, url in enumerate(valid_urls[:max_content_sources]):
            _log_tool_event({
                "tool": "smart_web_query",
                "stage": "fetch_content",
                "ok": True,
                "url": url,
                "index": i + 1
            })
            
            content_result = _fetch_webpage_content(url)
            if content_result["success"] and content_result["content"]:
                web_contents.append(content_result)
        
        # 3. 构建结构化结果
        sources = []
        for i, result in enumerate(search_results):
            source_info = {
                "index": i + 1,
                "title": result["title"],
                "url": result["link"],
                "snippet": result["snippet"] if include_snippets else "",
                "has_content": any(wc["url"] == result["link"] for wc in web_contents)
            }
            sources.append(source_info)
        
        # 4. 生成内容摘要
        content_summary = []
        for wc in web_contents:
            if wc["content"]:
                # 提取前500字符作为摘要
                summary_text = wc["content"][:500] + "..." if len(wc["content"]) > 500 else wc["content"]
                content_summary.append({
                    "url": wc["url"],
                    "summary": summary_text
                })
        
        result = {
            "query": query,
            "search_results": search_results,
            "web_contents": web_contents,
            "content_summary": content_summary,
            "sources": sources,
            "total_sources": len(search_results),
            "content_sources": len(web_contents)
        }
        
        _log_tool_event({
            "tool": "smart_web_query",
            "stage": "complete",
            "ok": True,
            "total_sources": len(search_results),
            "content_sources": len(web_contents)
        })
        
        return result
        
    except Exception as e:
        _log_tool_event({
            "tool": "smart_web_query",
            "stage": "error",
            "ok": False,
            "error": str(e)
        })
        raise RuntimeError(f"智能网络查询失败：{e}")
