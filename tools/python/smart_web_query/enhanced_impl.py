# -*- coding: utf-8 -*-
"""
增强版智能网络查询工具 - 混合抓取策略
- 优先使用BeautifulSoup进行快速抓取
- 必要时启用Playwright处理动态内容
- 基于autogen框架的内生机制
"""
from __future__ import annotations

import os
import json
import requests
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
import re
from bs4 import BeautifulSoup

# Playwright相关导入（可选）
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


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
            "tool": "enhanced_web_query",
            "stage": "google_search",
            "ok": False,
            "error": str(e)
        })
        raise


def _extract_text_from_html(html_content: str) -> Tuple[str, bool]:
    """
    从HTML中提取主要文本内容
    返回: (text_content, is_dynamic_content)
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 检测是否为动态内容（需要JavaScript）
        is_dynamic = _detect_dynamic_content(soup, html_content)
        
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
        final_text = text[:5000] if len(text) > 5000 else text
        
        return final_text, is_dynamic
    except Exception:
        return "", False


def _detect_dynamic_content(soup: BeautifulSoup, html_content: str) -> bool:
    """检测是否为动态内容（需要JavaScript渲染）"""
    try:
        # 检测常见的SPA框架标识
        spa_indicators = [
            'ng-app',  # Angular
            'data-reactroot',  # React
            'id="app"',  # Vue.js
            '__NEXT_DATA__',  # Next.js
            'nuxt',  # Nuxt.js
        ]
        
        for indicator in spa_indicators:
            if indicator in html_content:
                return True
        
        # 检测内容是否过少（可能需要JS加载）
        text_content = soup.get_text().strip()
        if len(text_content) < 200:
            return True
            
        # 检测是否有大量空的div（常见于SPA）
        empty_divs = soup.find_all('div', string=lambda text: not text or text.strip() == '')
        if len(empty_divs) > 10:
            return True
            
        return False
    except Exception:
        return False


def _fetch_with_requests(url: str) -> Dict[str, Any]:
    """使用requests+BeautifulSoup快速抓取"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        # 尝试检测编码
        if resp.encoding == 'ISO-8859-1':
            resp.encoding = resp.apparent_encoding
        
        content, is_dynamic = _extract_text_from_html(resp.text)
        
        return {
            "url": url,
            "content": content,
            "success": True,
            "method": "requests",
            "is_dynamic": is_dynamic,
            "error": None
        }
    except Exception as e:
        return {
            "url": url,
            "content": "",
            "success": False,
            "method": "requests",
            "is_dynamic": False,
            "error": str(e)
        }


async def _fetch_with_playwright(url: str) -> Dict[str, Any]:
    """使用Playwright处理动态内容"""
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "url": url,
            "content": "",
            "success": False,
            "method": "playwright",
            "error": "Playwright未安装"
        }
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1440, 'height': 900},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            # 访问页面并等待加载
            await page.goto(url, wait_until='networkidle')
            await page.wait_for_timeout(2000)  # 额外等待2秒确保动态内容加载
            
            # 获取渲染后的内容
            content = await page.evaluate("document.body.innerText")
            
            await browser.close()
            
            # 限制内容长度
            if len(content) > 5000:
                content = content[:5000]
            
            return {
                "url": url,
                "content": content,
                "success": True,
                "method": "playwright",
                "error": None
            }
    except Exception as e:
        return {
            "url": url,
            "content": "",
            "success": False,
            "method": "playwright",
            "error": str(e)
        }


async def _fetch_webpage_content_hybrid(url: str) -> Dict[str, Any]:
    """混合策略获取网页内容"""
    _log_tool_event({
        "tool": "enhanced_web_query",
        "stage": "fetch_start",
        "url": url,
        "method": "hybrid"
    })
    
    # 第一步：尝试requests快速抓取
    requests_result = _fetch_with_requests(url)
    
    if requests_result["success"] and requests_result["content"] and len(requests_result["content"]) > 100:
        # 如果内容足够且不是动态内容，直接返回
        if not requests_result.get("is_dynamic", False):
            _log_tool_event({
                "tool": "enhanced_web_query",
                "stage": "fetch_success",
                "url": url,
                "method": "requests",
                "content_length": len(requests_result["content"])
            })
            return requests_result
    
    # 第二步：如果requests失败或内容不足，使用Playwright
    _log_tool_event({
        "tool": "enhanced_web_query",
        "stage": "fallback_to_playwright",
        "url": url,
        "reason": "insufficient_content" if requests_result["success"] else "requests_failed"
    })
    
    playwright_result = await _fetch_with_playwright(url)
    
    if playwright_result["success"] and playwright_result["content"]:
        _log_tool_event({
            "tool": "enhanced_web_query",
            "stage": "fetch_success",
            "url": url,
            "method": "playwright",
            "content_length": len(playwright_result["content"])
        })
        return playwright_result
    
    # 如果都失败，返回最好的结果
    if requests_result["content"]:
        return requests_result
    else:
        return playwright_result


def _is_valid_url(url: str) -> bool:
    """检查URL是否有效"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


async def run(
    query: str,
    max_results: int = 5,
    max_content_sources: int = 3,
    include_snippets: bool = True,
    force_playwright: bool = False,
    auto_strategy: bool = True
) -> Dict[str, Any]:
    """
    增强版智能网络查询主函数
    
    Args:
        query: 搜索查询
        max_results: 最大搜索结果数
        max_content_sources: 最大内容抓取源数量
        include_snippets: 是否包含搜索片段
        force_playwright: 是否强制使用Playwright
        auto_strategy: 是否启用自动策略选择
    
    Returns:
        包含搜索结果、网页内容和结构化信息的字典
    """
    # 智能策略分析
    strategy_info = {}
    if auto_strategy:
        from .query_strategy import query_strategy
        analysis = query_strategy.analyze_query(query)
        strategy_config = query_strategy.get_strategy_config(analysis)
        
        # 应用策略配置
        if not force_playwright:  # 只有在未强制指定时才应用自动策略
            force_playwright = analysis.level.value in ["advanced", "force_advanced"]
            max_content_sources = strategy_config.get("max_content_sources", max_content_sources)
        
        strategy_info = {
            "analysis": {
                "level": analysis.level.value,
                "confidence": analysis.confidence,
                "reasons": analysis.reasons,
                "browser_needed": analysis.browser_needed,
                "complexity": analysis.estimated_complexity
            },
            "applied_config": strategy_config
        }
    
    _log_tool_event({
        "tool": "enhanced_web_query",
        "stage": "start",
        "ok": True,
        "query": query,
        "max_results": max_results,
        "max_content_sources": max_content_sources,
        "force_playwright": force_playwright,
        "auto_strategy": auto_strategy,
        "strategy_info": strategy_info
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
                "sources": [],
                "method_stats": {"requests": 0, "playwright": 0, "failed": 0}
            }
        
        # 2. 获取网页内容（使用混合策略）
        web_contents = []
        method_stats = {"requests": 0, "playwright": 0, "failed": 0}
        valid_urls = [item["link"] for item in search_results if _is_valid_url(item["link"])]
        
        for i, url in enumerate(valid_urls[:max_content_sources]):
            if force_playwright:
                content_result = await _fetch_with_playwright(url)
            else:
                content_result = await _fetch_webpage_content_hybrid(url)
            
            if content_result["success"] and content_result["content"]:
                web_contents.append(content_result)
                method_stats[content_result.get("method", "unknown")] += 1
            else:
                method_stats["failed"] += 1
        
        # 3. 构建结构化结果
        sources = []
        for i, result in enumerate(search_results):
            source_info = {
                "index": i + 1,
                "title": result["title"],
                "url": result["link"],
                "snippet": result["snippet"] if include_snippets else "",
                "has_content": any(wc["url"] == result["link"] for wc in web_contents),
                "fetch_method": next((wc.get("method") for wc in web_contents if wc["url"] == result["link"]), None)
            }
            sources.append(source_info)
        
        # 4. 生成内容摘要
        content_summary = []
        for wc in web_contents:
            if wc["content"]:
                summary_text = wc["content"][:500] + "..." if len(wc["content"]) > 500 else wc["content"]
                content_summary.append({
                    "url": wc["url"],
                    "summary": summary_text,
                    "method": wc.get("method", "unknown")
                })
        
        result = {
            "query": query,
            "search_results": search_results,
            "web_contents": web_contents,
            "content_summary": content_summary,
            "sources": sources,
            "total_sources": len(search_results),
            "content_sources": len(web_contents),
            "method_stats": method_stats,
            "strategy_info": strategy_info
        }
        
        _log_tool_event({
            "tool": "enhanced_web_query",
            "stage": "complete",
            "ok": True,
            "total_sources": len(search_results),
            "content_sources": len(web_contents),
            "method_stats": method_stats
        })
        
        return result
        
    except Exception as e:
        _log_tool_event({
            "tool": "enhanced_web_query",
            "stage": "error",
            "ok": False,
            "error": str(e)
        })
        raise RuntimeError(f"增强版智能网络查询失败：{e}")
