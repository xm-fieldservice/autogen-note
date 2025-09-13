from __future__ import annotations
from typing import Optional
import re

_MD_HEADER_RE = re.compile(r"^\s*#\s+", re.MULTILINE)
_CODEBLOCK_JSON_RE = re.compile(r"```json[\s\S]*?```", re.IGNORECASE)


def ensure_structured_markdown(text: str, mode: str = "note") -> str:
    """确保输出为结构化 Markdown：
    - 若检测到纯 JSON 或只有 JSON 代码块，转换为要点型 Markdown；
    - 若已有 Markdown 标题，直接返回；
    - 对 QA 模式，附加“要点/结论/参考来源”骨架占位；
    """
    text = text or ""
    t = text.strip()
    if not t:
        return t

    # 已有 Markdown 标题，视为结构化
    if _MD_HEADER_RE.search(t):
        return t

    # 若含有 JSON 代码块，保留为附录，正文给出结构化框架
    if _CODEBLOCK_JSON_RE.search(t):
        body = [
            "# 结果整理",
            "",
            "## 要点",
            "- （自动生成占位）",
            "",
            "## 细节",
            t,
            "",
        ]
        if mode == "qa":
            body.extend([
                "## 结论",
                "- （自动生成占位）",
                "",
                "## 参考来源",
                "- （自动生成占位）",
            ])
        return "\n".join(body)

    # 可能是纯 JSON：简单探测
    if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
        # 转为代码块附录 + 结构化骨架
        body = [
            "# 结果整理",
            "",
            "## 要点",
            "- （自动生成占位）",
            "",
            "## 细节",
            "```json",
            t,
            "```",
            "",
        ]
        if mode == "qa":
            body.extend([
                "## 结论",
                "- （自动生成占位）",
                "",
                "## 参考来源",
                "- （自动生成占位）",
            ])
        return "\n".join(body)

    # 默认补一个标题，避免裸文本
    header = "# 结果整理" if mode != "qa" else "# 问答结果"
    return f"{header}\n\n{t}"
