"""
Playwright录制器Agent集成接口
"""

import asyncio
import json
import os
from typing import Dict, Any, List
from .recorder import PlaywrightRecorder
from .action_converter import ActionConverter


class PlaywrightRecorderTool:
    """Playwright录制器工具类"""
    
    def __init__(self):
        self.recorder = None
        self.converter = ActionConverter()
        self.recordings_dir = "./recordings"
        os.makedirs(self.recordings_dir, exist_ok=True)
    
    async def start_recording(self, start_url: str = "https://www.baidu.com", headless: bool = False) -> Dict[str, Any]:
        """开始录制网页操作"""
        try:
            if self.recorder and self.recorder.is_recording:
                return {
                    "success": False,
                    "message": "录制已在进行中，请先停止当前录制"
                }
            
            self.recorder = PlaywrightRecorder(headless=headless)
            await self.recorder.start_recording(start_url)
            
            return {
                "success": True,
                "message": f"录制已开始，访问: {start_url}",
                "instructions": "在浏览器中进行操作，完成后调用 stop_recording() 停止录制"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"启动录制失败: {str(e)}"
            }
    
    async def stop_recording(self) -> Dict[str, Any]:
        """停止录制并保存"""
        try:
            if not self.recorder or not self.recorder.is_recording:
                return {
                    "success": False,
                    "message": "当前没有进行录制"
                }
            
            filepath = await self.recorder.stop_recording()
            summary = self.recorder.get_actions_summary()
            
            return {
                "success": True,
                "message": "录制完成",
                "filepath": filepath,
                "actions_count": len(self.recorder.actions),
                "summary": summary
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"停止录制失败: {str(e)}"
            }
    
    def convert_to_chinese(self, recording_file: str) -> Dict[str, Any]:
        """将录制转换为中文指令"""
        try:
            if not os.path.exists(recording_file):
                return {
                    "success": False,
                    "message": "录制文件不存在"
                }
            
            chinese_instructions = self.converter.convert_recording_to_chinese(recording_file)
            task = self.converter.convert_to_multimodal_task(recording_file)
            
            return {
                "success": True,
                "chinese_instructions": chinese_instructions,
                "multimodal_task": task
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"转换失败: {str(e)}"
            }
    
    def generate_script(self, recording_file: str, model_name: str = "qwen-turbo-latest") -> Dict[str, Any]:
        """生成执行脚本"""
        try:
            if not os.path.exists(recording_file):
                return {
                    "success": False,
                    "message": "录制文件不存在"
                }
            
            script = self.converter.generate_agent_script(recording_file, model_name)
            
            # 保存脚本文件
            script_filename = f"script_{os.path.basename(recording_file).replace('.json', '.py')}"
            script_path = os.path.join(self.recordings_dir, script_filename)
            
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script)
            
            return {
                "success": True,
                "script": script,
                "script_path": script_path,
                "message": f"脚本已生成: {script_path}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"生成脚本失败: {str(e)}"
            }
    
    def list_recordings(self) -> Dict[str, Any]:
        """列出所有录制文件"""
        try:
            recordings = []
            for filename in os.listdir(self.recordings_dir):
                if filename.endswith('.json') and filename.startswith('recording_'):
                    filepath = os.path.join(self.recordings_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    recordings.append({
                        "filename": filename,
                        "filepath": filepath,
                        "duration": data.get('duration', 0),
                        "actions_count": len(data.get('actions', [])),
                        "start_time": data.get('start_time', 0)
                    })
            
            # 按时间排序
            recordings.sort(key=lambda x: x['start_time'], reverse=True)
            
            return {
                "success": True,
                "recordings": recordings,
                "count": len(recordings)
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"获取录制列表失败: {str(e)}"
            }
    
    async def replay_recording(self, recording_file: str, model_name: str = "qwen-turbo-latest") -> Dict[str, Any]:
        """重放录制的操作"""
        try:
            # 生成并执行脚本
            script_result = self.generate_script(recording_file, model_name)
            if not script_result["success"]:
                return script_result
            
            script_path = script_result["script_path"]
            
            # 这里可以集成到MultimodalWebSurfer执行
            return {
                "success": True,
                "message": f"重放脚本已准备: {script_path}",
                "instructions": f"运行: python {script_path}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"重放失败: {str(e)}"
            }


# Agent调用接口
async def record_web_actions(start_url: str = "https://www.baidu.com", headless: bool = False) -> str:
    """开始录制网页操作"""
    tool = PlaywrightRecorderTool()
    result = await tool.start_recording(start_url, headless)
    return json.dumps(result, ensure_ascii=False, indent=2)


async def stop_web_recording() -> str:
    """停止录制网页操作"""
    tool = PlaywrightRecorderTool()
    result = await tool.stop_recording()
    return json.dumps(result, ensure_ascii=False, indent=2)


def convert_recording_to_chinese(recording_file: str) -> str:
    """将录制转换为中文指令"""
    tool = PlaywrightRecorderTool()
    result = tool.convert_to_chinese(recording_file)
    return json.dumps(result, ensure_ascii=False, indent=2)


def list_all_recordings() -> str:
    """列出所有录制"""
    tool = PlaywrightRecorderTool()
    result = tool.list_recordings()
    return json.dumps(result, ensure_ascii=False, indent=2)


async def replay_web_recording(recording_file: str, model_name: str = "qwen-turbo-latest") -> str:
    """重放录制的操作"""
    tool = PlaywrightRecorderTool()
    result = await tool.replay_recording(recording_file, model_name)
    return json.dumps(result, ensure_ascii=False, indent=2)
