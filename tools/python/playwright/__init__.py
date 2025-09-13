"""
Playwright工具包 - 基于autogen框架的网页自动化工具
"""

from .browser import PlaywrightBrowser
from .web_automation import WebAutomation

__all__ = ["PlaywrightBrowser", "WebAutomation"]
