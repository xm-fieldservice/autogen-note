# -*- coding: utf-8 -*-
"""
高级设置对话框
从app.py中提取的AdvancedSettingsDialog类
"""
import logging
from typing import Optional, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox, QWidget
)

from config.constants import Messages
from utils.error_handler import ErrorHandler, Validator


class AdvancedSettingsDialog(QDialog):
    """高级参数配置对话框：支持模型/基础参数编辑，不暴露 api_key"""
    
    def __init__(self, parent: Optional[QWidget], model_data: Dict[str, Any]):
        super().__init__(parent)
        self.setWindowTitle("高级参数设置")
        self.model_data = model_data or {}
        self.logger = ErrorHandler.setup_logging("advanced_settings")
        
        # 获取配置数据
        cfg = dict(self.model_data.get("config") or {})
        params = dict(cfg.get("parameters") or {})
        
        self._setup_ui(cfg, params)
    
    def _setup_ui(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> None:
        """设置UI界面"""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        # 创建输入字段
        self.ed_model = QLineEdit(str(cfg.get("model", self.model_data.get("name", ""))))
        self.ed_base_url = QLineEdit(str(self.model_data.get("base_url", cfg.get("base_url", ""))))
        self.ed_temperature = QLineEdit(str(params.get("temperature", "")))
        self.ed_top_p = QLineEdit(str(params.get("top_p", "")))
        self.ed_max_tokens = QLineEdit(str(params.get("max_tokens", "")))
        self.ed_timeout = QLineEdit(str(cfg.get("timeout", "")))
        
        # 处理stop参数
        stop_val = cfg.get("stop") or params.get("stop")
        if isinstance(stop_val, list):
            stop_str = ", ".join(str(s) for s in stop_val)
        else:
            stop_str = str(stop_val or "")
        self.ed_stop = QLineEdit(stop_str)
        
        # 添加到表单
        form.addRow("模型(model)", self.ed_model)
        form.addRow("Base URL", self.ed_base_url)
        form.addRow("temperature", self.ed_temperature)
        form.addRow("top_p", self.ed_top_p)
        form.addRow("max_tokens", self.ed_max_tokens)
        form.addRow("timeout(s)", self.ed_timeout)
        form.addRow("stop(逗号分隔)", self.ed_stop)
        
        layout.addLayout(form)
        
        # 按钮
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
    
    def _to_number(self, value: str) -> Any:
        """转换字符串为数字"""
        value = value.strip()
        if value == "":
            return None
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
    
    def apply(self) -> None:
        """应用设置到模型数据"""
        try:
            # 获取配置结构
            cfg = dict(self.model_data.get("config") or {})
            params = dict(cfg.get("parameters") or {})
            
            # 更新模型名称
            if self.ed_model.text().strip():
                cfg["model"] = self.ed_model.text().strip()
            
            # 更新Base URL
            base_url = self.ed_base_url.text().strip()
            if base_url:
                # 顶层与config同步一份，减少兼容问题
                self.model_data["base_url"] = base_url
                cfg["base_url"] = base_url
            
            # 更新数值参数
            temperature = self._to_number(self.ed_temperature.text())
            if temperature is not None:
                # 验证温度范围
                if isinstance(temperature, (int, float)) and not (0 <= temperature <= 2):
                    raise ValueError("temperature必须在0-2之间")
                params["temperature"] = temperature
            
            top_p = self._to_number(self.ed_top_p.text())
            if top_p is not None:
                # 验证top_p范围
                if isinstance(top_p, (int, float)) and not (0 <= top_p <= 1):
                    raise ValueError("top_p必须在0-1之间")
                params["top_p"] = top_p
            
            max_tokens = self._to_number(self.ed_max_tokens.text())
            if max_tokens is not None:
                # 验证max_tokens
                if isinstance(max_tokens, int) and max_tokens <= 0:
                    raise ValueError("max_tokens必须是正整数")
                params["max_tokens"] = max_tokens
            
            timeout = self._to_number(self.ed_timeout.text())
            if timeout is not None:
                cfg["timeout"] = timeout
            
            # 处理stop参数
            stop_str = self.ed_stop.text().strip()
            if stop_str:
                stop_list = [s.strip() for s in stop_str.split(",") if s.strip()]
                cfg["stop"] = stop_list
            
            # 更新配置
            if params:
                cfg["parameters"] = params
            self.model_data["config"] = cfg
            
            self.logger.info("高级参数已应用到模型配置")
            
        except Exception as e:
            self.logger.exception(f"应用高级参数失败: {e}")
            raise
    
    def validate(self) -> bool:
        """验证输入数据"""
        try:
            # 验证temperature
            temp_text = self.ed_temperature.text().strip()
            if temp_text:
                temp = self._to_number(temp_text)
                if isinstance(temp, (int, float)) and not (0 <= temp <= 2):
                    ErrorHandler.handle_warning(self, "验证失败", "temperature必须在0-2之间")
                    return False
            
            # 验证top_p
            top_p_text = self.ed_top_p.text().strip()
            if top_p_text:
                top_p = self._to_number(top_p_text)
                if isinstance(top_p, (int, float)) and not (0 <= top_p <= 1):
                    ErrorHandler.handle_warning(self, "验证失败", "top_p必须在0-1之间")
                    return False
            
            # 验证max_tokens
            max_tokens_text = self.ed_max_tokens.text().strip()
            if max_tokens_text:
                max_tokens = self._to_number(max_tokens_text)
                if isinstance(max_tokens, int) and max_tokens <= 0:
                    ErrorHandler.handle_warning(self, "验证失败", "max_tokens必须是正整数")
                    return False
            
            return True
            
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "验证失败", e)
            return False
    
    def accept(self) -> None:
        """接受对话框"""
        if self.validate():
            try:
                self.apply()
                super().accept()
            except Exception as e:
                ErrorHandler.handle_ui_error(self, "应用设置失败", e)
