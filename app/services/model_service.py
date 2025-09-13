# -*- coding: utf-8 -*-
"""
模型管理服务
从app.py中提取的模型相关业务逻辑
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from config.constants import Paths, Files, Messages
from utils.error_handler import ErrorHandler, ValidationError, ConfigError
from autogen_client.agents import AgentBackend


class ModelService:
    """模型管理服务"""
    
    def __init__(self):
        self.logger = ErrorHandler.setup_logging("model_service")
        self._capability_registry: Optional[Dict] = None
    
    def load_capability_registry(self) -> Dict[str, Any]:
        """加载能力注册表"""
        if self._capability_registry is not None:
            return self._capability_registry
            
        try:
            registry_path = Paths.get_absolute_path(Paths.MODELS_DIR) / Files.CAPABILITY_REGISTRY
            if registry_path.exists():
                with registry_path.open("r", encoding="utf-8") as f:
                    self._capability_registry = json.load(f)
                    self.logger.info(f"加载能力注册表成功: {registry_path}")
            else:
                self._capability_registry = {"schema": 1, "models": {}}
                self.logger.warning(f"能力注册表不存在，使用默认: {registry_path}")
        except Exception as e:
            self.logger.exception(f"加载能力注册表失败: {e}")
            self._capability_registry = {"schema": 1, "models": {}}
            
        return self._capability_registry
    
    def validate_model_config(self, config: Dict[str, Any]) -> None:
        """验证模型配置"""
        if not isinstance(config, dict):
            raise ValidationError("模型配置必须是字典格式")
            
        # 检查基本字段
        if not config.get("name"):
            raise ValidationError("模型名称不能为空")
            
        if not config.get("provider"):
            raise ValidationError("模型提供商不能为空")
            
        # 检查配置结构
        model_config = config.get("config", {})
        if not isinstance(model_config, dict):
            raise ValidationError("config字段必须是字典格式")
            
        # 检查参数
        parameters = model_config.get("parameters", {})
        if parameters and not isinstance(parameters, dict):
            raise ValidationError("parameters字段必须是字典格式")
            
        # 验证数值参数
        if "temperature" in parameters:
            temp = parameters["temperature"]
            if not isinstance(temp, (int, float)) or not (0 <= temp <= 2):
                raise ValidationError("temperature必须在0-2之间")
                
        if "top_p" in parameters:
            top_p = parameters["top_p"]
            if not isinstance(top_p, (int, float)) or not (0 <= top_p <= 1):
                raise ValidationError("top_p必须在0-1之间")
                
        if "max_tokens" in parameters:
            max_tokens = parameters["max_tokens"]
            if not isinstance(max_tokens, int) or max_tokens <= 0:
                raise ValidationError("max_tokens必须是正整数")
    
    def normalize_model_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """规范化模型配置"""
        normalized = dict(config)
        
        # 确保基本结构
        if "config" not in normalized:
            normalized["config"] = {}
        if "parameters" not in normalized["config"]:
            normalized["config"]["parameters"] = {}
            
        # 规范化provider
        provider = normalized.get("provider", "").lower()
        if provider in ["openai", "gpt"]:
            normalized["provider"] = "openai"
        elif provider in ["anthropic", "claude"]:
            normalized["provider"] = "anthropic"
        elif provider in ["dashscope", "qwen"]:
            normalized["provider"] = "dashscope"
            
        # 设置默认值
        if not normalized["config"].get("model"):
            normalized["config"]["model"] = normalized.get("name", "")
            
        # 规范化参数
        params = normalized["config"]["parameters"]
        if "temperature" in params and isinstance(params["temperature"], str):
            try:
                params["temperature"] = float(params["temperature"])
            except ValueError:
                del params["temperature"]
                
        if "top_p" in params and isinstance(params["top_p"], str):
            try:
                params["top_p"] = float(params["top_p"])
            except ValueError:
                del params["top_p"]
                
        if "max_tokens" in params and isinstance(params["max_tokens"], str):
            try:
                params["max_tokens"] = int(params["max_tokens"])
            except ValueError:
                del params["max_tokens"]
        
        # —— api_key_env 缺省推断 ——
        # 严格只读：不进行任何 api_key_env 的缺省推断，完全依赖原始配置
        
        return normalized
    
    def load_model_from_file(self, file_path: str) -> Dict[str, Any]:
        """从文件加载模型配置"""
        path = Path(file_path)
        if not path.exists():
            raise ConfigError(f"模型配置文件不存在: {file_path}")
            
        try:
            with path.open("r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"模型配置文件格式错误: {e}")
        except Exception as e:
            raise ConfigError(f"读取模型配置文件失败: {e}")
            
        # 类型检查：避免在Model页读入Agent/Team文件
        config_type = config.get("type", "").lower() if isinstance(config, dict) else ""
        if config_type in ("agent", "team"):
            raise ConfigError(f"此文件是{config_type}配置，请在对应页面导入")
            
        # 兜底：老配置可能缺少 name，这里在校验前根据 label 或 config.model 推断
        try:
            if isinstance(config, dict) and not config.get("name"):
                inferred_name = None
                # 优先使用 label，其次使用 config.model
                inferred_name = config.get("label") or (
                    config.get("config", {}).get("model") if isinstance(config.get("config", {}), dict) else None
                )
                if inferred_name:
                    config["name"] = inferred_name
        except Exception:
            # 忽略兜底过程中的任何异常，交由后续校验统一处理
            pass

        # 验证和规范化
        self.validate_model_config(config)
        normalized_config = self.normalize_model_config(config)
        
        self.logger.info(f"模型配置加载成功: {normalized_config.get('name', '')}")
        return normalized_config
    
    def save_model_to_file(self, config: Dict[str, Any], file_path: str) -> None:
        """保存模型配置到文件"""
        # 验证配置
        self.validate_model_config(config)
        
        # 确保目录存在
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.logger.info(f"模型配置保存成功: {file_path}")
        except Exception as e:
            raise ConfigError(f"保存模型配置失败: {e}")
    
    def create_backend(self, config: Dict[str, Any], system_message: str = "") -> AgentBackend:
        """创建模型后端"""
        try:
            # 验证配置
            self.validate_model_config(config)
            
            # 运行前信息：仅记录 name/model/base_url/api_key_env 与目标变量是否存在（精简输出）
            try:
                import os
                name = str(config.get('name') or '')
                provider = str(config.get('provider') or '')
                cc = dict(config.get('config') or {})
                model = str(cc.get('model') or '')
                base_url = str(cc.get('base_url') or config.get('base_url') or '')
                api_key_env = str(cc.get('api_key_env') or '')
                target_present = bool(api_key_env and os.environ.get(api_key_env))
                masked = ((os.environ.get(api_key_env) or '')[:4] + '...') if target_present else '未设置'
                # 精简日志（不再输出 env_snapshot）
                self.logger.info(
                    f"模型后端创建参数 | name={name} provider={provider} model={model} base_url={base_url} env={api_key_env}={masked}"
                )
                if api_key_env and not os.environ.get(api_key_env):
                    self.logger.error(f"[DEBUG] 缺少必要环境变量: {api_key_env}；请在数据库 env_keys 或系统环境中设置后重试")
            except Exception:
                pass

            # 创建后端
            backend = AgentBackend(config)
            if system_message:
                backend.system_message = system_message
                
            self.logger.info(f"模型后端创建成功: {config.get('name', '')}")
            return backend
            
        except Exception as e:
            raise ConfigError(f"创建模型后端失败: {e}")
    
    def get_model_capabilities(self, model_name: str) -> Dict[str, Any]:
        """获取模型能力信息"""
        registry = self.load_capability_registry()
        models = registry.get("models", {})
        
        # 精确匹配
        if model_name in models:
            return models[model_name]
            
        # 模糊匹配
        for name, capabilities in models.items():
            if model_name.lower() in name.lower() or name.lower() in model_name.lower():
                return capabilities
                
        # 返回默认能力
        return {
            "max_tokens": 4096,
            "supports_functions": False,
            "supports_vision": False,
            "context_window": 4096
        }
    
    def update_capability_registry(self, model_name: str, capabilities: Dict[str, Any]) -> None:
        """更新能力注册表"""
        registry = self.load_capability_registry()
        if "models" not in registry:
            registry["models"] = {}
            
        registry["models"][model_name] = capabilities
        
        # 保存到文件
        try:
            registry_path = Paths.get_absolute_path(Paths.MODELS_DIR) / Files.CAPABILITY_REGISTRY
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            
            with registry_path.open("w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
                
            self.logger.info(f"能力注册表更新成功: {model_name}")
            
        except Exception as e:
            self.logger.exception(f"更新能力注册表失败: {e}")
            raise ConfigError(f"更新能力注册表失败: {e}")
