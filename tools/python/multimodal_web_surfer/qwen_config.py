"""
Qwen模型配置加载器 - 用于MultimodalWebSurfer
"""

import json
import os
from typing import Dict, Any
from autogen_ext.models.openai import OpenAIChatCompletionClient


def load_qwen_model_client() -> OpenAIChatCompletionClient:
    """
    从配置文件加载Qwen-VL-Plus模型客户端
    
    Returns:
        配置好的OpenAIChatCompletionClient实例
    """
    # 加载模型配置
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "config", "models", "qwen_vl_plus_latest.json"
    )
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    model_config = config["config"]
    
    # 获取API密钥
    api_key = os.getenv(model_config["api_key_env"])
    if not api_key:
        raise ValueError(f"请在.env文件中设置 {model_config['api_key_env']} 环境变量")
    
    # 创建客户端
    client = OpenAIChatCompletionClient(
        model=model_config["model"],
        api_key=api_key,
        base_url=model_config["base_url"],
        **model_config.get("parameters", {})
    )
    
    return client


def create_qwen_web_surfer(**kwargs):
    """
    创建使用Qwen模型的MultimodalWebSurfer
    
    Args:
        **kwargs: MultimodalWebSurfer的其他配置参数
        
    Returns:
        配置好的MultimodalWebSurfer实例
    """
    from autogen_ext.agents.web_surfer import MultimodalWebSurfer
    
    # 加载Qwen模型客户端
    model_client = load_qwen_model_client()
    
    # 默认配置
    default_config = {
        "headless": True,
        "start_page": "https://www.bing.com/",
        "animate_actions": False,
        "to_save_screenshots": True,  # 利用Qwen的视觉能力
        "downloads_folder": "./downloads",
        "debug_dir": "./debug",
        "use_ocr": False,  # Qwen-VL本身有视觉能力
        "to_resize_viewport": True
    }
    
    # 合并用户配置
    config = {**default_config, **kwargs}
    
    # 创建WebSurfer
    web_surfer = MultimodalWebSurfer(
        name="QwenWebSurfer",
        model_client=model_client,
        description="""我是一个使用Qwen-VL-Plus模型的智能网页浏览助手。
我具备强大的中文理解和视觉分析能力，可以：
- 理解网页的视觉布局和内容
- 智能分析图片和文本信息
- 执行复杂的网页交互任务
- 提供详细的中文页面分析和总结""",
        **config
    )
    
    return web_surfer


# 简化的工具函数
def qwen_web_search(query: str) -> str:
    """使用Qwen模型执行网页搜索"""
    import asyncio
    
    async def _search():
        web_surfer = create_qwen_web_surfer()
        try:
            from autogen_agentchat.messages import TextMessage
            message = TextMessage(content=f"请搜索: {query}", source="user")
            response = await web_surfer.on_messages([message])
            await web_surfer.close()
            return response.chat_message.content if response.chat_message else "搜索完成"
        except Exception as e:
            await web_surfer.close()
            return f"搜索失败: {str(e)}"
    
    return asyncio.run(_search())


def qwen_visit_url(url: str) -> str:
    """使用Qwen模型访问网页"""
    import asyncio
    
    async def _visit():
        web_surfer = create_qwen_web_surfer()
        try:
            from autogen_agentchat.messages import TextMessage
            message = TextMessage(content=f"请访问并分析这个网页: {url}", source="user")
            response = await web_surfer.on_messages([message])
            await web_surfer.close()
            return response.chat_message.content if response.chat_message else "访问完成"
        except Exception as e:
            await web_surfer.close()
            return f"访问失败: {str(e)}"
    
    return asyncio.run(_visit())
