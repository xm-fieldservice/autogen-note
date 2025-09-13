# -*- coding: utf-8 -*-
"""
Adapter for google.search tool to create an AutoGen FunctionTool for agent integration.
"""
from __future__ import annotations

from autogen_core.tools import FunctionTool

from .impl import run as google_search_run


def build_tool() -> FunctionTool:
    """Return a FunctionTool wrapping google.search.run.

    Usage:
        from tools.python.google.search.adapter import build_tool
        tool = build_tool()
    """
    return FunctionTool(
        google_search_run,
        name="google_search",
        description="Google Custom Search via Programmable Search Engine. Requires env GOOGLE_API_KEY and GOOGLE_CSE_CX.",
    )
