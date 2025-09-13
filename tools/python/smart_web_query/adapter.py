# -*- coding: utf-8 -*-
"""
智能网络查询工具的AutoGen适配器
"""
from __future__ import annotations

from autogen_core.tools import FunctionTool

from .impl import run as smart_web_query_run


def build_tool() -> FunctionTool:
    """创建智能网络查询的FunctionTool
    
    Usage:
        from tools.python.smart_web_query.adapter import build_tool
        tool = build_tool()
    """
    return FunctionTool(
        smart_web_query_run,
        name="smart_web_query",
        description="智能网络查询工具：搜索并获取网页内容，生成结构化答案。需要环境变量 GOOGLE_API_KEY 和 GOOGLE_CSE_CX。",
    )
