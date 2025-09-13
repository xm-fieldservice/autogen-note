"""
MultimodalWebSurfer工具实现 - Agent调用接口
"""

import asyncio
import sys
from typing import Any, Dict
from .web_surfer_wrapper import search_web_simple, visit_url_simple


def web_search(query: str) -> str:
    """网页搜索工具"""
    return search_web_simple(query)


def visit_page(url: str) -> str:
    """访问网页工具"""
    return visit_url_simple(url)


def get_web_surfer_info() -> str:
    """获取MultimodalWebSurfer工具信息"""
    return """MultimodalWebSurfer多模态网页浏览工具

功能特性：
- 智能网页搜索和导航
- 多模态内容理解（文本+图像）
- 自动页面交互（点击、填写表单等）
- 页面内容总结和问答
- 截图和视觉分析
- 支持复杂网页操作流程

使用说明：
1. 需要配置支持多模态和函数调用的模型客户端（推荐GPT-4o）
2. 支持有头/无头模式运行
3. 可保存截图和下载文件
4. 基于autogen框架的内生机制实现

注意事项：
- Windows平台需要设置WindowsProactorEventLoopPolicy
- 需要安装autogen-ext[web-surfer]和playwright
- 建议在受控环境中使用，注意网页安全"""
