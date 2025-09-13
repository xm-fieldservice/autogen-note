"""
网页自动化工具 - 基于autogen框架的Playwright集成
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from .browser import PlaywrightBrowser


class WebAutomation:
    """
    网页自动化工具类，提供高级网页操作功能
    """
    
    def __init__(self, **kwargs):
        self.browser = PlaywrightBrowser(**kwargs)
        self._running = False
    
    async def __aenter__(self):
        await self.browser.start()
        self._running = True
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.browser.stop()
        self._running = False
    
    def visit_page(self, url: str) -> Dict[str, Any]:
        """
        访问指定网页
        
        Args:
            url: 要访问的网页URL
            
        Returns:
            Dict: 包含访问结果的字典
        """
        if not self._running:
            return asyncio.run(self._visit_page_sync(url))
        else:
            return asyncio.create_task(self.browser.visit_url(url))
    
    async def _visit_page_sync(self, url: str) -> Dict[str, Any]:
        """同步访问页面的内部方法"""
        async with self:
            return await self.browser.visit_url(url)
    
    def get_page_text(self) -> Dict[str, Any]:
        """
        获取当前页面的文本内容
        
        Returns:
            Dict: 包含页面文本内容的字典
        """
        if not self._running:
            return {"success": False, "error": "浏览器未启动"}
        return asyncio.create_task(self.browser.get_page_content())
    
    def click_element(self, selector: str) -> Dict[str, Any]:
        """
        点击页面元素
        
        Args:
            selector: CSS选择器或XPath
            
        Returns:
            Dict: 包含点击结果的字典
        """
        if not self._running:
            return {"success": False, "error": "浏览器未启动"}
        return asyncio.create_task(self.browser.click_element(selector))
    
    def fill_form(self, selector: str, value: str) -> Dict[str, Any]:
        """
        填写表单输入框
        
        Args:
            selector: 输入框的CSS选择器
            value: 要填入的值
            
        Returns:
            Dict: 包含填写结果的字典
        """
        if not self._running:
            return {"success": False, "error": "浏览器未启动"}
        return asyncio.create_task(self.browser.fill_input(selector, value))
    
    def take_screenshot(self, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        截取当前页面截图
        
        Args:
            filename: 截图文件名，如果为None则自动生成
            
        Returns:
            Dict: 包含截图结果的字典
        """
        if not self._running:
            return {"success": False, "error": "浏览器未启动"}
        return asyncio.create_task(self.browser.take_screenshot(filename))
    
    def wait_for_element(self, selector: str, timeout: int = 5000) -> Dict[str, Any]:
        """
        等待元素出现
        
        Args:
            selector: 元素的CSS选择器
            timeout: 超时时间（毫秒）
            
        Returns:
            Dict: 包含等待结果的字典
        """
        if not self._running:
            return {"success": False, "error": "浏览器未启动"}
        return asyncio.create_task(self.browser.wait_for_element(selector, timeout))


# 工具函数，供Agent调用
def create_web_automation(**kwargs) -> WebAutomation:
    """创建网页自动化实例"""
    return WebAutomation(**kwargs)


def visit_webpage(url: str, headless: bool = True) -> Dict[str, Any]:
    """
    访问网页并获取基本信息
    
    Args:
        url: 要访问的网页URL
        headless: 是否无头模式运行
        
    Returns:
        Dict: 包含访问结果的字典
    """
    automation = WebAutomation(headless=headless)
    return automation.visit_page(url)


def get_webpage_content(url: str) -> Dict[str, Any]:
    """
    获取网页内容
    
    Args:
        url: 要获取内容的网页URL
        
    Returns:
        Dict: 包含网页内容的字典
    """
    async def _get_content():
        async with WebAutomation(headless=True) as automation:
            visit_result = await automation.browser.visit_url(url)
            if visit_result["success"]:
                return await automation.browser.get_page_content()
            return visit_result
    
    return asyncio.run(_get_content())


def take_webpage_screenshot(url: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """
    访问网页并截图
    
    Args:
        url: 要截图的网页URL
        filename: 截图文件名
        
    Returns:
        Dict: 包含截图结果的字典
    """
    async def _take_screenshot():
        async with WebAutomation(headless=True) as automation:
            visit_result = await automation.browser.visit_url(url)
            if visit_result["success"]:
                return await automation.browser.take_screenshot(filename)
            return visit_result
    
    return asyncio.run(_take_screenshot())
