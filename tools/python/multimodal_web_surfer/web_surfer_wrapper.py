"""
MultimodalWebSurfer包装器 - 提供简化的调用接口
"""

import asyncio
import sys
from typing import Any, Dict, Optional
from .web_surfer_agent import MultimodalWebSurferTool


def create_web_surfer(model_client, **kwargs) -> MultimodalWebSurferTool:
    """
    创建MultimodalWebSurfer实例
    
    Args:
        model_client: 模型客户端
        **kwargs: 其他配置参数
        
    Returns:
        MultimodalWebSurferTool实例
    """
    return MultimodalWebSurferTool(model_client, **kwargs)


def web_search(query: str, model_client, **kwargs) -> Dict[str, Any]:
    """
    执行网页搜索
    
    Args:
        query: 搜索查询
        model_client: 模型客户端
        **kwargs: 其他配置参数
        
    Returns:
        搜索结果字典
    """
    async def _search():
        surfer = MultimodalWebSurferTool(model_client, **kwargs)
        try:
            result = await surfer.search_web(query)
            await surfer.close()
            return result
        except Exception as e:
            await surfer.close()
            return {
                "success": False,
                "error": str(e),
                "message": f"搜索失败: {str(e)}"
            }
    
    return asyncio.run(_search())


def visit_url(url: str, model_client, **kwargs) -> Dict[str, Any]:
    """
    访问指定URL
    
    Args:
        url: 要访问的网页URL
        model_client: 模型客户端
        **kwargs: 其他配置参数
        
    Returns:
        访问结果字典
    """
    async def _visit():
        surfer = MultimodalWebSurferTool(model_client, **kwargs)
        try:
            result = await surfer.visit_page(url)
            await surfer.close()
            return result
        except Exception as e:
            await surfer.close()
            return {
                "success": False,
                "error": str(e),
                "message": f"访问失败: {str(e)}"
            }
    
    return asyncio.run(_visit())


def get_page_summary(model_client, **kwargs) -> Dict[str, Any]:
    """
    获取当前页面总结
    
    Args:
        model_client: 模型客户端
        **kwargs: 其他配置参数
        
    Returns:
        页面总结字典
    """
    async def _summarize():
        surfer = MultimodalWebSurferTool(model_client, **kwargs)
        try:
            result = await surfer.summarize_page()
            await surfer.close()
            return result
        except Exception as e:
            await surfer.close()
            return {
                "success": False,
                "error": str(e),
                "message": f"总结失败: {str(e)}"
            }
    
    return asyncio.run(_summarize())


# 简化的同步接口，用于Agent工具调用
def search_web_simple(query: str) -> str:
    """
    简化的网页搜索接口（需要预先配置模型客户端）
    """
    try:
        # 这里需要从环境或配置中获取模型客户端
        # 暂时返回提示信息
        return f"需要配置模型客户端来执行搜索: {query}"
    except Exception as e:
        return f"搜索失败: {str(e)}"


def visit_url_simple(url: str) -> str:
    """
    简化的URL访问接口（需要预先配置模型客户端）
    """
    try:
        # 这里需要从环境或配置中获取模型客户端
        # 暂时返回提示信息
        return f"需要配置模型客户端来访问: {url}"
    except Exception as e:
        return f"访问失败: {str(e)}"
