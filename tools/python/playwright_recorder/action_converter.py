"""
操作转换器 - 将录制的操作转换为中文指令
"""

import json
from typing import List, Dict, Any
from .recorder import WebAction


class ActionConverter:
    """将录制的操作转换为中文指令"""
    
    def __init__(self):
        self.action_templates = {
            "navigate": "访问 {url}",
            "click": "点击 {target}",
            "input": "在 {target} 输入 '{value}'",
            "scroll": "滚动页面",
            "wait": "等待 {duration} 秒"
        }
    
    def convert_recording_to_chinese(self, recording_file: str) -> str:
        """将录制文件转换为中文指令"""
        with open(recording_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        actions = data.get('actions', [])
        instructions = []
        
        for i, action_data in enumerate(actions, 1):
            action = WebAction(**action_data)
            instruction = self._convert_action_to_chinese(action, i)
            if instruction:
                instructions.append(instruction)
        
        return self._format_instructions(instructions)
    
    def _convert_action_to_chinese(self, action: WebAction, step_num: int) -> str:
        """将单个操作转换为中文指令"""
        if action.type == "navigate":
            return f"{step_num}. 访问 {action.url}"
        
        elif action.type == "click":
            target = self._get_click_target_description(action)
            return f"{step_num}. 点击 {target}"
        
        elif action.type == "input":
            target = self._get_input_target_description(action)
            return f"{step_num}. 在 {target} 输入 '{action.value}'"
        
        return ""
    
    def _get_click_target_description(self, action: WebAction) -> str:
        """获取点击目标的中文描述"""
        if action.text and action.text.strip():
            return f"'{action.text.strip()}'"
        
        if action.element_info:
            element_info = action.element_info
            if element_info.get('id'):
                return f"ID为'{element_info['id']}'的元素"
            elif element_info.get('className'):
                return f"类名为'{element_info['className']}'的元素"
            elif element_info.get('href'):
                return f"链接'{element_info['href']}'"
        
        if action.selector:
            return f"选择器'{action.selector}'的元素"
        
        return "页面元素"
    
    def _get_input_target_description(self, action: WebAction) -> str:
        """获取输入目标的中文描述"""
        if action.element_info:
            element_info = action.element_info
            if element_info.get('placeholder'):
                return f"'{element_info['placeholder']}'输入框"
            elif element_info.get('name'):
                return f"'{element_info['name']}'字段"
            elif element_info.get('id'):
                return f"ID为'{element_info['id']}'的输入框"
        
        if action.selector:
            return f"选择器'{action.selector}'的输入框"
        
        return "输入框"
    
    def _format_instructions(self, instructions: List[str]) -> str:
        """格式化指令列表"""
        if not instructions:
            return "暂无有效操作指令"
        
        formatted = "# 录制的操作指令\n\n"
        formatted += "请按以下步骤执行网页操作：\n\n"
        formatted += "\n".join(instructions)
        formatted += "\n\n# 使用方法\n"
        formatted += "将上述指令复制到MultimodalWebSurfer中执行即可重现录制的操作。"
        
        return formatted
    
    def convert_to_multimodal_task(self, recording_file: str) -> str:
        """转换为MultimodalWebSurfer任务格式"""
        chinese_instructions = self.convert_recording_to_chinese(recording_file)
        
        task_template = f"""
请帮我执行以下网页操作任务：

{chinese_instructions}

注意事项：
- 每步操作间隔1-2秒
- 如果页面加载较慢，请等待加载完成
- 如果遇到弹窗或验证码，请告知我
"""
        return task_template
    
    def generate_agent_script(self, recording_file: str, model_name: str = "qwen-turbo-latest") -> str:
        """生成完整的Agent执行脚本"""
        task = self.convert_to_multimodal_task(recording_file)
        
        script = f'''"""
基于录制操作生成的MultimodalWebSurfer执行脚本
"""

import asyncio
import os
from dotenv import load_dotenv
from autogen_agentchat.agents import MultimodalWebSurfer, UserProxyAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_core.models import OpenAIChatCompletionClient

# 加载环境变量
load_dotenv()

async def run_recorded_task():
    """执行录制的任务"""
    
    # 创建模型客户端
    model_client = OpenAIChatCompletionClient(
        model="{model_name}",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    # 创建MultimodalWebSurfer
    web_surfer = MultimodalWebSurfer(
        name="WebSurfer",
        model_client=model_client,
        headless=False,  # 可视化执行
        animate_actions=True  # 动画效果
    )
    
    # 创建用户代理
    user_proxy = UserProxyAgent(name="User")
    
    # 创建团队
    termination = TextMentionTermination("任务完成") | MaxMessageTermination(20)
    team = RoundRobinGroupChat([web_surfer, user_proxy], termination_condition=termination)
    
    # 执行任务
    task = """{task}"""
    
    print("🚀 开始执行录制的任务...")
    result = await team.run(task=task)
    
    print("✅ 任务执行完成")
    return result

if __name__ == "__main__":
    asyncio.run(run_recorded_task())
'''
        return script


# 使用示例
def demo_converter():
    """转换器演示"""
    converter = ActionConverter()
    
    # 假设有录制文件
    recording_file = "./recordings/recording_1234567890.json"
    
    if os.path.exists(recording_file):
        # 转换为中文指令
        chinese_instructions = converter.convert_recording_to_chinese(recording_file)
        print("中文指令:")
        print(chinese_instructions)
        
        # 生成Agent脚本
        script = converter.generate_agent_script(recording_file)
        print("\nAgent脚本:")
        print(script[:500] + "...")
    else:
        print("录制文件不存在，请先进行录制")


if __name__ == "__main__":
    demo_converter()
