"""
桌面版Playwright录制器核心模块
"""

import asyncio
import json
import time
import os
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from dataclasses import dataclass, asdict


@dataclass
class WebAction:
    """网页操作记录"""
    type: str  # click, input, navigate, scroll, etc.
    timestamp: float
    url: str
    selector: Optional[str] = None
    text: Optional[str] = None
    value: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None
    element_info: Optional[Dict[str, Any]] = None


class PlaywrightRecorder:
    """桌面版Playwright录制器"""
    
    def __init__(self, headless: bool = False, record_screenshots: bool = True):
        self.headless = headless
        self.record_screenshots = record_screenshots
        self.actions: List[WebAction] = []
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_recording = False
        self.start_time = 0
        self.output_dir = "./recordings"
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
    
    async def start_recording(self, start_url: str = "https://www.baidu.com") -> None:
        """开始录制"""
        if self.is_recording:
            print("录制已在进行中")
            return
        
        print("🎬 启动Playwright录制器...")
        
        # 启动浏览器
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        
        # 创建上下文
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        # 创建页面
        self.page = await self.context.new_page()
        
        # 设置事件监听
        await self._setup_event_listeners()
        
        # 导航到起始页面
        await self.page.goto(start_url)
        
        # 记录导航动作
        self._record_action(WebAction(
            type="navigate",
            timestamp=time.time(),
            url=start_url
        ))
        
        self.is_recording = True
        self.start_time = time.time()
        
        print(f"✅ 录制开始，访问: {start_url}")
        print("💡 在浏览器中进行操作，完成后调用 stop_recording() 停止录制")
    
    async def _setup_event_listeners(self) -> None:
        """设置事件监听器"""
        if not self.page:
            return
        
        # 监听点击事件
        await self.page.expose_function("recordClick", self._on_click)
        
        # 监听输入事件
        await self.page.expose_function("recordInput", self._on_input)
        
        # 监听导航事件
        self.page.on("framenavigated", self._on_navigate)
        
        # 注入监听脚本
        await self.page.add_init_script("""
            // 监听点击事件
            document.addEventListener('click', (e) => {
                const rect = e.target.getBoundingClientRect();
                window.recordClick({
                    selector: getSelector(e.target),
                    text: e.target.textContent?.trim() || '',
                    tagName: e.target.tagName,
                    coordinates: {
                        x: e.clientX,
                        y: e.clientY
                    },
                    element_info: {
                        id: e.target.id,
                        className: e.target.className,
                        href: e.target.href || null
                    }
                });
            });
            
            // 监听输入事件
            document.addEventListener('input', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                    window.recordInput({
                        selector: getSelector(e.target),
                        value: e.target.value,
                        placeholder: e.target.placeholder || '',
                        element_info: {
                            id: e.target.id,
                            name: e.target.name,
                            type: e.target.type
                        }
                    });
                }
            });
            
            // 获取元素选择器
            function getSelector(element) {
                if (element.id) return '#' + element.id;
                if (element.className) return '.' + element.className.split(' ')[0];
                return element.tagName.toLowerCase();
            }
        """)
    
    def _on_click(self, data: Dict[str, Any]) -> None:
        """处理点击事件"""
        action = WebAction(
            type="click",
            timestamp=time.time(),
            url=self.page.url if self.page else "",
            selector=data.get("selector"),
            text=data.get("text"),
            coordinates=data.get("coordinates"),
            element_info=data.get("element_info")
        )
        self._record_action(action)
    
    def _on_input(self, data: Dict[str, Any]) -> None:
        """处理输入事件"""
        action = WebAction(
            type="input",
            timestamp=time.time(),
            url=self.page.url if self.page else "",
            selector=data.get("selector"),
            value=data.get("value"),
            element_info=data.get("element_info")
        )
        self._record_action(action)
    
    def _on_navigate(self, frame) -> None:
        """处理导航事件"""
        if frame == self.page.main_frame:
            action = WebAction(
                type="navigate",
                timestamp=time.time(),
                url=frame.url
            )
            self._record_action(action)
    
    def _record_action(self, action: WebAction) -> None:
        """记录动作"""
        self.actions.append(action)
        print(f"📝 记录动作: {action.type} - {action.text or action.url}")
    
    async def stop_recording(self) -> str:
        """停止录制并保存"""
        if not self.is_recording:
            print("当前没有进行录制")
            return ""
        
        self.is_recording = False
        
        # 生成文件名
        timestamp = int(time.time())
        filename = f"recording_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)
        
        # 保存录制数据
        recording_data = {
            "start_time": self.start_time,
            "end_time": time.time(),
            "duration": time.time() - self.start_time,
            "actions": [asdict(action) for action in self.actions]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(recording_data, f, indent=2, ensure_ascii=False)
        
        # 关闭浏览器
        if self.browser:
            await self.browser.close()
        
        print(f"✅ 录制完成，共记录 {len(self.actions)} 个动作")
        print(f"📁 保存到: {filepath}")
        
        return filepath
    
    async def wait_for_completion(self) -> str:
        """等待用户完成操作"""
        print("⏳ 等待用户操作完成...")
        print("💡 在浏览器中完成操作后，按 Ctrl+C 停止录制")
        
        try:
            while self.is_recording:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 用户中断录制")
        
        return await self.stop_recording()
    
    def get_actions_summary(self) -> str:
        """获取动作摘要"""
        if not self.actions:
            return "暂无录制动作"
        
        summary = []
        for i, action in enumerate(self.actions, 1):
            if action.type == "navigate":
                summary.append(f"{i}. 访问: {action.url}")
            elif action.type == "click":
                summary.append(f"{i}. 点击: {action.text or action.selector}")
            elif action.type == "input":
                summary.append(f"{i}. 输入: {action.value} (在 {action.selector})")
        
        return "\n".join(summary)


# 使用示例
async def demo_recorder():
    """录制器演示"""
    recorder = PlaywrightRecorder(headless=False)
    
    try:
        await recorder.start_recording("https://www.baidu.com")
        filepath = await recorder.wait_for_completion()
        
        print("\n📋 录制摘要:")
        print(recorder.get_actions_summary())
        
        return filepath
    except Exception as e:
        print(f"❌ 录制出错: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(demo_recorder())
