"""
Playwright浏览器工具 - 基于autogen框架实现
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


class PlaywrightBrowser:
    """
    Playwright浏览器控制器，提供网页自动化功能
    """
    
    def __init__(
        self,
        headless: bool = True,
        viewport_width: int = 1440,
        viewport_height: int = 900,
        downloads_folder: Optional[str] = None,
        browser_channel: Optional[str] = None,
        browser_data_dir: Optional[str] = None
    ):
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.downloads_folder = downloads_folder
        self.browser_channel = browser_channel
        self.browser_data_dir = browser_data_dir
        
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
    
    async def start(self) -> None:
        """启动浏览器"""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            
        if self._browser is None:
            launch_options = {
                "headless": self.headless,
                "channel": self.browser_channel,
            }
            if self.browser_data_dir:
                launch_options["user_data_dir"] = self.browser_data_dir
                
            self._browser = await self._playwright.chromium.launch(**launch_options)
            
        if self._context is None:
            context_options = {
                "viewport": {"width": self.viewport_width, "height": self.viewport_height}
            }
            if self.downloads_folder:
                context_options["accept_downloads"] = True
                
            self._context = await self._browser.new_context(**context_options)
            
        if self._page is None:
            self._page = await self._context.new_page()
            
    async def stop(self) -> None:
        """停止浏览器"""
        if self._page:
            await self._page.close()
            self._page = None
            
        if self._context:
            await self._context.close()
            self._context = None
            
        if self._browser:
            await self._browser.close()
            self._browser = None
            
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
    
    async def visit_url(self, url: str) -> Dict[str, Any]:
        """访问指定URL"""
        await self.start()
        assert self._page is not None
        
        try:
            await self._page.goto(url)
            await self._page.wait_for_load_state()
            
            title = await self._page.title()
            current_url = self._page.url
            
            return {
                "success": True,
                "title": title,
                "url": current_url,
                "message": f"成功访问页面: {title}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"访问页面失败: {str(e)}"
            }
    
    async def get_page_content(self) -> Dict[str, Any]:
        """获取页面内容"""
        if not self._page:
            return {"success": False, "error": "浏览器未启动"}
            
        try:
            title = await self._page.title()
            url = self._page.url
            text_content = await self._page.evaluate("document.body.innerText")
            
            return {
                "success": True,
                "title": title,
                "url": url,
                "content": text_content[:2000],  # 限制内容长度
                "message": f"成功获取页面内容: {title}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"获取页面内容失败: {str(e)}"
            }
    
    async def click_element(self, selector: str) -> Dict[str, Any]:
        """点击页面元素"""
        if not self._page:
            return {"success": False, "error": "浏览器未启动"}
            
        try:
            await self._page.click(selector)
            await self._page.wait_for_load_state()
            
            return {
                "success": True,
                "message": f"成功点击元素: {selector}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"点击元素失败: {str(e)}"
            }
    
    async def fill_input(self, selector: str, value: str) -> Dict[str, Any]:
        """填写输入框"""
        if not self._page:
            return {"success": False, "error": "浏览器未启动"}
            
        try:
            await self._page.fill(selector, value)
            
            return {
                "success": True,
                "message": f"成功填写输入框: {selector}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"填写输入框失败: {str(e)}"
            }
    
    async def take_screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        """截取页面截图"""
        if not self._page:
            return {"success": False, "error": "浏览器未启动"}
            
        try:
            if path is None:
                path = f"screenshot_{int(asyncio.get_event_loop().time())}.png"
                
            await self._page.screenshot(path=path)
            
            return {
                "success": True,
                "path": path,
                "message": f"成功截取截图: {path}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"截取截图失败: {str(e)}"
            }
    
    async def wait_for_element(self, selector: str, timeout: int = 5000) -> Dict[str, Any]:
        """等待元素出现"""
        if not self._page:
            return {"success": False, "error": "浏览器未启动"}
            
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            
            return {
                "success": True,
                "message": f"元素已出现: {selector}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"等待元素超时: {str(e)}"
            }
