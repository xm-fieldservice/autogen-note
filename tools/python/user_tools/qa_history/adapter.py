# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Adapter for qa_history tool to create an AutoGen FunctionTool for agent integration.
- Wraps impl.run(action: str, **kwargs) -> dict
"""
from autogen_core.tools import FunctionTool
from .impl import run as qa_history_run


def build_tool() -> FunctionTool:
    return FunctionTool(
        qa_history_run,
        name="qa_history",
        description="QA history store (SQLite). Actions: ensure_session, append_user, append_assistant, add_*_event, add_feedback, list_*, export_session_json.",
    )
