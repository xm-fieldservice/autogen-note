"""
MultimodalWebSurfer Agent工具 - 基于autogen框架实现
"""

import asyncio
import sys
from typing import Any, Dict, List, Optional
from autogen_agentchat.agents import BaseChatAgent
from autogen_core.models import ChatCompletionClient


class MultimodalWebSurferTool:
    """
    MultimodalWebSurfer工具封装类
    """
    
    def __init__(self, model_client: ChatCompletionClient, **kwargs):
        self.model_client = model_client
        self.config = kwargs
        self._agent = None
        
        # Windows事件循环策略设置
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    async def _get_agent(self):
        """获取或创建MultimodalWebSurfer实例"""
        if self._agent is None:
            try:
                from autogen_ext.agents.web_surfer import MultimodalWebSurfer
                
                self._agent = MultimodalWebSurfer(
                    name="WebSurfer",
                    model_client=self.model_client,
                    headless=self.config.get("headless", True),
                    start_page=self.config.get("start_page", "https://www.bing.com/"),
                    animate_actions=self.config.get("animate_actions", False),
                    to_save_screenshots=self.config.get("to_save_screenshots", False),
                    downloads_folder=self.config.get("downloads_folder"),
                    debug_dir=self.config.get("debug_dir"),
                    use_ocr=self.config.get("use_ocr", False),
                    browser_channel=self.config.get("browser_channel"),
                    browser_data_dir=self.config.get("browser_data_dir"),
                    to_resize_viewport=self.config.get("to_resize_viewport", True)
                )
            except ImportError as e:
                raise ImportError(f"无法导入MultimodalWebSurfer: {e}. 请确保已安装 autogen-ext[web-surfer]")
        
        return self._agent
    
    async def search_web(self, query: str) -> Dict[str, Any]:
        """执行网页搜索"""
        try:
            agent = await self._get_agent()
            
            # 创建搜索消息
            from autogen_agentchat.messages import TextMessage
            message = TextMessage(content=f"请在网上搜索: {query}", source="user")
            
            # 执行搜索
            response = await agent.on_messages([message])
            
            return {
                "success": True,
                "query": query,
                "response": response.chat_message.content if response.chat_message else "无响应",
                "message": f"成功搜索: {query}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"搜索失败: {str(e)}"
            }
    
    async def visit_page(self, url: str) -> Dict[str, Any]:
        """访问指定网页"""
        try:
            agent = await self._get_agent()
            
            # 创建访问消息
            from autogen_agentchat.messages import TextMessage
            message = TextMessage(content=f"请访问这个网页: {url}", source="user")
            
            # 执行访问
            response = await agent.on_messages([message])
            
            return {
                "success": True,
                "url": url,
                "response": response.chat_message.content if response.chat_message else "无响应",
                "message": f"成功访问: {url}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"访问失败: {str(e)}"
            }
    
    async def summarize_page(self) -> Dict[str, Any]:
        """总结当前页面内容"""
        try:
            agent = await self._get_agent()
            
            # 创建总结消息
            from autogen_agentchat.messages import TextMessage
            message = TextMessage(content="请总结当前页面的内容", source="user")
            
            # 执行总结
            response = await agent.on_messages([message])
            
            return {
                "success": True,
                "summary": response.chat_message.content if response.chat_message else "无总结",
                "message": "成功总结页面内容"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"总结失败: {str(e)}"
            }
    
    async def close(self):
        """关闭浏览器"""
        if self._agent:
            try:
                await self._agent.close()
            except Exception:
                pass
            self._agent = None
