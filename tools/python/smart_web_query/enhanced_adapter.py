# -*- coding: utf-8 -*-
"""
增强版智能网络查询工具的AutoGen适配器
支持混合抓取策略（BeautifulSoup + Playwright）
"""
from __future__ import annotations

from autogen_core.tools import FunctionTool

from .enhanced_impl import run as enhanced_web_query_run


def build_tool() -> FunctionTool:
    """创建增强版智能网络查询的FunctionTool
    
    Usage:
        from tools.python.smart_web_query.enhanced_adapter import build_tool
        tool = build_tool()
    """
    return FunctionTool(
        enhanced_web_query_run,
        name="enhanced_web_query",
        description="增强版智能网络查询工具：混合使用BeautifulSoup和Playwright抓取策略，优先快速抓取，必要时深度渲染。需要环境变量 GOOGLE_API_KEY 和 GOOGLE_CSE_CX。",
    )
