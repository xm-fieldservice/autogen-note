"""
Playwright工具实现 - Agent调用接口
"""

from .web_automation import visit_webpage, get_webpage_content, take_webpage_screenshot, create_web_automation


def visit_page(url: str, headless: bool = True):
    """访问网页"""
    return visit_webpage(url, headless)


def get_page_content(url: str):
    """获取网页内容"""
    return get_webpage_content(url)


def screenshot_page(url: str, filename: str = None):
    """网页截图"""
    return take_webpage_screenshot(url, filename)


def create_browser_automation(**kwargs):
    """创建浏览器自动化实例"""
    return create_web_automation(**kwargs)
