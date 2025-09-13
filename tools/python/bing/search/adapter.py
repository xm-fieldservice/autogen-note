# -*- coding: utf-8 -*-
"""
Adapter for bing.search tool to create an AutoGen FunctionTool for agent integration.
"""
from __future__ import annotations

from autogen_core.tools import FunctionTool

from .impl import run as bing_search_run


def build_tool() -> FunctionTool:
    """Return a FunctionTool wrapping bing.search.run.

    Usage:
        from tools.python.bing.search.adapter import build_tool
        tool = build_tool()
    """
    return FunctionTool(
        bing_search_run,
        name="bing_search",
        description="Bing Web Search via Azure Cognitive Services. Requires env BING_SEARCH_KEY (and optional BING_ENDPOINT).",
    )
