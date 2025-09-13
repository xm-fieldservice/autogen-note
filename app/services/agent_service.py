# -*- coding: utf-8 -*-
"""
Agent管理服务
从app.py中提取的Agent相关业务逻辑
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from config.constants import Paths, Files, Messages, AgentConfig
from utils.error_handler import ErrorHandler, ValidationError, ConfigError
from autogen_client.autogen_backends import AutogenAgentBackend
from autogen_client.config_loader import load_agent_json


class AgentService:
    """Agent管理服务"""
    
    def __init__(self):
        self.logger = ErrorHandler.setup_logging("agent_service")
    
    def validate_agent_config(self, config: Dict[str, Any]) -> None:
        """验证Agent配置"""
        if not isinstance(config, dict):
            raise ValidationError("Agent配置必须是字典格式")
            
        # 检查基本字段
        if not config.get("name"):
            raise ValidationError("Agent名称不能为空")
            
        # 检查模型客户端配置
        model_client = config.get("model_client")
        if model_client and not isinstance(model_client, dict):
            raise ValidationError("model_client必须是字典格式")
            
        # 检查工具配置
        tools = config.get("tools", [])
        if not isinstance(tools, list):
            raise ValidationError("tools必须是列表格式")
            
        # 检查内存配置
        memory = config.get("memory", [])
        if not isinstance(memory, list):
            raise ValidationError("memory必须是列表格式")
    
    def _flatten_component_agent(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """兼容 AutoGen ComponentModel Agent 配置，扁平化为本地后端需要的顶层结构。

        输入可能是：
        {
          "provider": "autogen_agentchat.agents.AssistantAgent",
          "component_type": "agent",
          "label": "...",
          "config": {
            "name": "...",
            "model_client": { ... },
            "memory": [ ... ],
            "workbench": [ { "config": { "tools": [ ... ] } } ]
          }
        }

        返回：
        { "name": ..., "model_client": ..., "tools": [...], "memory": [...] , ... }
        """
        if not isinstance(config, dict):
            return config
        if config.get("component_type") != "agent" or not isinstance(config.get("config"), dict):
            return config

        inner = dict(config.get("config", {}))
        flat: Dict[str, Any] = {}

        # 基本字段直接拷贝
        for key in (
            "name",
            "system_message",
            "description",
            "model_client",
            "reflect_on_tool_use",
            "tool_call_summary_format",
            "max_tool_iterations",
            "model_client_stream",
            "model_context",
            "metadata",
        ):
            if key in inner:
                flat[key] = inner[key]

        # memory 直接映射
        mem = inner.get("memory")
        if isinstance(mem, list):
            flat["memory"] = mem

        # 从 workbench[0].config.tools 提取工具
        tools: List[Any] = []
        wb = inner.get("workbench")
        if isinstance(wb, list) and wb:
            wb0 = wb[0] or {}
            wb0_cfg = wb0.get("config") if isinstance(wb0, dict) else None
            if isinstance(wb0_cfg, dict):
                t = wb0_cfg.get("tools")
                if isinstance(t, list):
                    tools = t
        flat["tools"] = tools

        # 兜底名称：可用 label 作为 name
        if not flat.get("name"):
            label = config.get("label") or ""
            if label:
                flat["name"] = label

        return flat
    
    def normalize_agent_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """规范化Agent配置"""
        normalized = dict(config)
        
        # 确保基本字段存在
        if "tools" not in normalized:
            normalized["tools"] = []
        if "memory" not in normalized:
            normalized["memory"] = []
        if "capabilities" not in normalized:
            normalized["capabilities"] = []
            
        # 规范化系统消息
        system_message = normalized.get("system_message", "")
        if system_message and not system_message.endswith(AgentConfig.TOOL_CONSTRAINT):
            # 自动添加工具约束
            normalized["system_message"] = system_message + AgentConfig.TOOL_CONSTRAINT
            
        return normalized
    
    def load_agent_from_file(self, file_path: str) -> Dict[str, Any]:
        """从文件加载Agent配置"""
        path = Path(file_path)
        if not path.exists():
            raise ConfigError(f"Agent配置文件不存在: {file_path}")
            
        try:
            config = load_agent_json(file_path)
        except Exception as e:
            raise ConfigError(f"加载Agent配置失败: {e}")
            
        # 若为 ComponentModel，先扁平化
        config_or_flat = self._flatten_component_agent(config)
        # 验证和规范化
        self.validate_agent_config(config_or_flat)
        normalized_config = self.normalize_agent_config(config_or_flat)
        
        self.logger.info(f"Agent配置加载成功: {normalized_config.get('name', '')}")
        return normalized_config
    
    def save_agent_to_file(self, config: Dict[str, Any], file_path: str) -> None:
        """保存Agent配置到文件"""
        # 验证配置
        self.validate_agent_config(config)
        
        # 确保目录存在
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Agent配置保存成功: {file_path}")
        except Exception as e:
            raise ConfigError(f"保存Agent配置失败: {e}")
    
    def create_backend(self, config: Dict[str, Any]) -> AutogenAgentBackend:
        """创建Agent后端"""
        try:
            # 兼容 ComponentModel：必要时先扁平化
            cfg = self._flatten_component_agent(config)
            # 验证配置
            self.validate_agent_config(cfg)
            
            # 创建日志目录
            log_dir = str(Paths.get_absolute_path(Paths.AGENT_LOGS_DIR))
            
            # 创建后端
            backend = AutogenAgentBackend(agent_config=cfg, log_dir=log_dir)
            
            self.logger.info(f"Agent后端创建成功: {cfg.get('name', '')}")
            return backend
            
        except Exception as e:
            raise ConfigError(f"创建Agent后端失败: {e}")
    
    def get_mounted_tool_ids(self, config: Dict[str, Any]) -> List[str]:
        """获取已挂载的工具ID列表"""
        tools = config.get("tools", [])
        tool_ids = []
        
        for tool in tools:
            if isinstance(tool, dict):
                tool_id = tool.get("id")
                if tool_id:
                    tool_ids.append(tool_id)
            elif isinstance(tool, str):
                tool_ids.append(tool)
                
        return tool_ids
    
    def get_mounted_memory_ids(self, config: Dict[str, Any]) -> List[str]:
        """获取已挂载的内存ID列表"""
        memory = config.get("memory", [])
        memory_ids = []
        
        for mem in memory:
            if isinstance(mem, dict):
                mem_id = mem.get("id")
                if mem_id:
                    memory_ids.append(mem_id)
            elif isinstance(mem, str):
                memory_ids.append(mem)
                
        return memory_ids
    
    def mount_tool(self, config: Dict[str, Any], tool_id: str, tool_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """挂载工具到Agent"""
        updated_config = dict(config)
        tools = updated_config.setdefault("tools", [])
        
        # 检查是否已挂载
        for tool in tools:
            if isinstance(tool, dict) and tool.get("id") == tool_id:
                # 更新现有工具配置
                if tool_config:
                    tool.update(tool_config)
                return updated_config
            elif isinstance(tool, str) and tool == tool_id:
                return updated_config
                
        # 添加新工具
        if tool_config:
            tools.append({"id": tool_id, **tool_config})
        else:
            tools.append(tool_id)
            
        self.logger.info(f"工具挂载成功: {tool_id}")
        return updated_config
    
    def unmount_tool(self, config: Dict[str, Any], tool_id: str) -> Dict[str, Any]:
        """卸载工具"""
        updated_config = dict(config)
        tools = updated_config.get("tools", [])
        
        # 移除工具
        updated_tools = []
        for tool in tools:
            if isinstance(tool, dict) and tool.get("id") != tool_id:
                updated_tools.append(tool)
            elif isinstance(tool, str) and tool != tool_id:
                updated_tools.append(tool)
                
        updated_config["tools"] = updated_tools
        self.logger.info(f"工具卸载成功: {tool_id}")
        return updated_config
    
    def mount_memory(self, config: Dict[str, Any], memory_id: str, memory_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """挂载内存到Agent"""
        updated_config = dict(config)
        memory = updated_config.setdefault("memory", [])
        
        # 检查是否已挂载
        for mem in memory:
            if isinstance(mem, dict) and mem.get("id") == memory_id:
                # 更新现有内存配置
                if memory_config:
                    mem.update(memory_config)
                return updated_config
            elif isinstance(mem, str) and mem == memory_id:
                return updated_config
                
        # 添加新内存
        if memory_config:
            memory.append({"id": memory_id, **memory_config})
        else:
            memory.append(memory_id)
            
        self.logger.info(f"内存挂载成功: {memory_id}")
        return updated_config
    
    def unmount_memory(self, config: Dict[str, Any], memory_id: str) -> Dict[str, Any]:
        """卸载内存"""
        updated_config = dict(config)
        memory = updated_config.get("memory", [])
        
        # 移除内存
        updated_memory = []
        for mem in memory:
            if isinstance(mem, dict) and mem.get("id") != memory_id:
                updated_memory.append(mem)
            elif isinstance(mem, str) and mem != memory_id:
                updated_memory.append(mem)
                
        updated_config["memory"] = updated_memory
        self.logger.info(f"内存卸载成功: {memory_id}")
        return updated_config
    
    def preflight_check(self, config: Dict[str, Any]) -> tuple[bool, str]:
        """运行前环境检查"""
        try:
            # 检查模型客户端环境变量
            model_client = config.get("model_client", {})
            provider = model_client.get("provider", "").lower()
            
            if provider == "dashscope":
                if not os.environ.get("DASHSCOPE_API_KEY"):
                    return False, "缺少环境变量: DASHSCOPE_API_KEY"
            elif provider == "openai":
                if not os.environ.get("OPENAI_API_KEY"):
                    return False, "缺少环境变量: OPENAI_API_KEY"
            elif provider == "anthropic":
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    return False, "缺少环境变量: ANTHROPIC_API_KEY"
            
            # 检查工具依赖的环境变量
            tool_ids = self.get_mounted_tool_ids(config)
            
            if "google.search" in tool_ids:
                if not os.environ.get("GOOGLE_API_KEY"):
                    return False, "缺少环境变量: GOOGLE_API_KEY (google.search工具需要)"
                if not os.environ.get("GOOGLE_CSE_CX"):
                    return False, "缺少环境变量: GOOGLE_CSE_CX (google.search工具需要)"
                    
            if "bing.search" in tool_ids:
                if not os.environ.get("BING_SEARCH_KEY"):
                    return False, "缺少环境变量: BING_SEARCH_KEY (bing.search工具需要)"
            
            return True, "环境检查通过"
            
        except Exception as e:
            return False, f"环境检查失败: {e}"
    
    def export_agent_params(self, config: Dict[str, Any], output_path: str = None) -> str:
        """导出Agent参数到JSON文件"""
        if output_path is None:
            output_path = str(Paths.get_absolute_path(Paths.OUT_DIR) / Files.AGENT_EXPORT_PARAMS)
        
        # 确保输出目录存在
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"Agent参数导出成功: {output_path}")
            return output_path
            
        except Exception as e:
            raise ConfigError(f"导出Agent参数失败: {e}")
