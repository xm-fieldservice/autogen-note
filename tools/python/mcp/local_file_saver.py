# -*- coding: utf-8 -*-
"""
MCP Server: Local File Saver
- 提供一个 save_file(path, content) 工具，将文本内容保存到本地文件。
- 使用 mcp>=1.1.0 的 FastMCP 简化实现。
- 运行方式由 config/mcp/servers.json 启动。
"""
from __future__ import annotations
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP, tool

app = FastMCP("Local File Saver")

@app.tool()
def save_file(path: str, content: str) -> str:
    """保存文本到本地文件。
    参数:
      - path: 目标文件路径（可相对，可绝对）。
      - content: 要写入的文本内容。
    返回: 写入后的绝对路径。
    """
    if not path:
        raise ValueError("path 不能为空")
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return str(p)

if __name__ == "__main__":
    app.run()
