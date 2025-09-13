# -*- coding: utf-8 -*-
"""
浏览器管理器 - 智能浏览器生命周期管理
避免频繁启动关闭，提供连接池和预热机制
"""
from __future__ import annotations

import asyncio
import time
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from contextlib import asynccontextmanager

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class BrowserSession:
    """浏览器会话信息"""
    browser: Any  # Browser实例
    context: Any  # BrowserContext实例
    created_at: float
    last_used: float
    usage_count: int
    is_busy: bool = False


class BrowserManager:
    """浏览器管理器 - 单例模式"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.sessions: Dict[str, BrowserSession] = {}
            self.playwright_instance = None
            self.max_sessions = 2  # 最大并发浏览器数
            self.session_timeout = 300  # 5分钟超时
            self.cleanup_interval = 60  # 1分钟清理一次
            self._cleanup_task = None
            self._lock = asyncio.Lock()
            BrowserManager._initialized = True
    
    async def start_manager(self):
        """启动浏览器管理器"""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright未安装，无法使用浏览器功能")
        
        if self.playwright_instance is None:
            self.playwright_instance = await async_playwright().start()
        
        # 启动清理任务
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop_manager(self):
        """停止浏览器管理器"""
        # 停止清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        
        # 关闭所有会话
        for session_id in list(self.sessions.keys()):
            await self._close_session(session_id)
        
        # 停止playwright
        if self.playwright_instance:
            await self.playwright_instance.stop()
            self.playwright_instance = None
    
    async def get_browser_session(self, session_id: str = "default") -> BrowserSession:
        """获取或创建浏览器会话"""
        async with self._lock:
            # 检查现有会话
            if session_id in self.sessions:
                session = self.sessions[session_id]
                if not session.is_busy and time.time() - session.created_at < self.session_timeout:
                    session.last_used = time.time()
                    session.usage_count += 1
                    return session
                else:
                    # 会话过期或忙碌，关闭并重新创建
                    await self._close_session(session_id)
            
            # 检查会话数量限制
            if len(self.sessions) >= self.max_sessions:
                # 关闭最老的会话
                oldest_id = min(self.sessions.keys(), 
                              key=lambda x: self.sessions[x].last_used)
                await self._close_session(oldest_id)
            
            # 创建新会话
            return await self._create_session(session_id)
    
    async def _create_session(self, session_id: str) -> BrowserSession:
        """创建新的浏览器会话"""
        if not self.playwright_instance:
            await self.start_manager()
        
        # 启动浏览器
        browser = await self.playwright_instance.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        # 创建上下文
        context = await browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        # 创建会话对象
        session = BrowserSession(
            browser=browser,
            context=context,
            created_at=time.time(),
            last_used=time.time(),
            usage_count=1
        )
        
        self.sessions[session_id] = session
        return session
    
    async def _close_session(self, session_id: str):
        """关闭指定会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            try:
                await session.context.close()
                await session.browser.close()
            except Exception:
                pass  # 忽略关闭错误
            del self.sessions[session_id]
    
    async def _cleanup_loop(self):
        """定期清理过期会话"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                current_time = time.time()
                
                expired_sessions = []
                for session_id, session in self.sessions.items():
                    if (current_time - session.last_used > self.session_timeout or
                        current_time - session.created_at > self.session_timeout * 2):
                        expired_sessions.append(session_id)
                
                for session_id in expired_sessions:
                    await self._close_session(session_id)
                    
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # 忽略清理错误
    
    @asynccontextmanager
    async def get_page(self, session_id: str = "default"):
        """获取页面的上下文管理器"""
        session = await self.get_browser_session(session_id)
        session.is_busy = True
        
        try:
            page = await session.context.new_page()
            yield page
        finally:
            try:
                await page.close()
            except Exception:
                pass
            session.is_busy = False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        return {
            "active_sessions": len(self.sessions),
            "max_sessions": self.max_sessions,
            "session_details": {
                session_id: {
                    "created_at": session.created_at,
                    "last_used": session.last_used,
                    "usage_count": session.usage_count,
                    "is_busy": session.is_busy,
                    "age_seconds": time.time() - session.created_at
                }
                for session_id, session in self.sessions.items()
            }
        }


# 全局浏览器管理器实例
browser_manager = BrowserManager()
