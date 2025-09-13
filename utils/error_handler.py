# -*- coding: utf-8 -*-
"""
错误处理工具模块
统一管理应用程序的错误处理和用户提示
"""
import logging
import traceback
from typing import Optional, Any
from PySide6.QtWidgets import QMessageBox, QWidget
from PySide6.QtCore import QObject

from config.constants import Messages, LogConfig

class ErrorHandler:
    """统一错误处理器"""
    
    @staticmethod
    def setup_logging(logger_name: str = "autogen_desktop", level: str = LogConfig.DEFAULT_LEVEL) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger(logger_name)
        if not logger.handlers:  # 避免重复添加handler
            handler = logging.StreamHandler()
            formatter = logging.Formatter(LogConfig.DEFAULT_FORMAT)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(getattr(logging, level.upper()))
        return logger
    
    @staticmethod
    def handle_ui_error(parent: Optional[QWidget], title: str, error: Exception, 
                       show_details: bool = False) -> None:
        """处理UI相关错误"""
        logger = ErrorHandler.setup_logging()
        
        # 记录详细错误信息
        logger.exception(f"{title}: {error}")
        
        # 准备用户显示的错误信息
        error_msg = str(error)
        if show_details:
            error_msg += f"\n\n详细信息:\n{traceback.format_exc()}"
        
        # 显示错误对话框
        QMessageBox.critical(parent, title, error_msg)
    
    @staticmethod
    def handle_warning(parent: Optional[QWidget], title: str, message: str) -> None:
        """处理警告信息"""
        logger = ErrorHandler.setup_logging()
        logger.warning(f"{title}: {message}")
        QMessageBox.warning(parent, title, message)
    
    @staticmethod
    def handle_info(parent: Optional[QWidget], title: str, message: str) -> None:
        """处理信息提示"""
        logger = ErrorHandler.setup_logging()
        logger.info(f"{title}: {message}")
        QMessageBox.information(parent, title, message)
    
    @staticmethod
    def handle_success(parent: Optional[QWidget], title: str, message: str = Messages.SAVE_SUCCESS) -> None:
        """处理成功信息"""
        logger = ErrorHandler.setup_logging()
        logger.info(f"{title}: {message}")
        QMessageBox.information(parent, title, message)
    
    @staticmethod
    def confirm_action(parent: Optional[QWidget], title: str, message: str) -> bool:
        """确认操作对话框"""
        result = QMessageBox.question(
            parent, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        return result == QMessageBox.StandardButton.Yes
    
    @staticmethod
    def log_exception(logger_name: str, operation: str, error: Exception) -> None:
        """记录异常但不显示UI"""
        logger = ErrorHandler.setup_logging(logger_name)
        logger.exception(f"{operation} failed: {error}")
    
    @staticmethod
    def safe_execute(func, *args, error_title: str = "操作失败", 
                    parent: Optional[QWidget] = None, **kwargs) -> tuple[bool, Any]:
        """安全执行函数，自动处理异常"""
        try:
            result = func(*args, **kwargs)
            return True, result
        except Exception as e:
            ErrorHandler.handle_ui_error(parent, error_title, e)
            return False, None

class ValidationError(Exception):
    """验证错误异常"""
    pass

class ConfigError(Exception):
    """配置错误异常"""
    pass

class ServiceError(Exception):
    """服务错误异常"""
    pass

class Validator:
    """数据验证器"""
    
    @staticmethod
    def validate_not_empty(value: str, field_name: str) -> None:
        """验证字段不为空"""
        if not value or not value.strip():
            raise ValidationError(f"{field_name}不能为空")
    
    @staticmethod
    def validate_file_exists(file_path: str, field_name: str = "文件") -> None:
        """验证文件存在"""
        import os
        if not os.path.exists(file_path):
            raise ValidationError(f"{field_name}不存在: {file_path}")
    
    @staticmethod
    def validate_json_format(json_str: str, field_name: str = "JSON") -> dict:
        """验证JSON格式"""
        import json
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValidationError(f"{field_name}格式错误: {e}")
    
    @staticmethod
    def validate_positive_number(value: Any, field_name: str) -> float:
        """验证正数"""
        try:
            num = float(value)
            if num <= 0:
                raise ValidationError(f"{field_name}必须是正数")
            return num
        except (ValueError, TypeError):
            raise ValidationError(f"{field_name}必须是有效数字")

class ProgressHandler:
    """进度处理器"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        self.parent = parent
        self.logger = ErrorHandler.setup_logging()
    
    def start_operation(self, message: str = Messages.PROCESSING) -> None:
        """开始操作"""
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        
        self.logger.info(f"开始操作: {message}")
        QApplication.setOverrideCursor(Qt.WaitCursor)
    
    def finish_operation(self, success: bool = True, message: str = "") -> None:
        """结束操作"""
        from PySide6.QtWidgets import QApplication
        
        QApplication.restoreOverrideCursor()
        
        if success:
            self.logger.info(f"操作完成: {message}")
        else:
            self.logger.error(f"操作失败: {message}")
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start_operation()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        success = exc_type is None
        if not success and exc_val:
            self.logger.exception(f"操作异常: {exc_val}")
        self.finish_operation(success)
