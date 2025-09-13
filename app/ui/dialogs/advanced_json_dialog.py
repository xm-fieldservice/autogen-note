# -*- coding: utf-8 -*-
"""
高级JSON编辑对话框
从app.py中提取的AdvancedJsonDialog类
"""
import json
from typing import Optional, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, 
    QDialogButtonBox, QWidget, QMessageBox
)

from utils.error_handler import ErrorHandler


class AdvancedJsonDialog(QDialog):
    """高级参数编辑对话框：默认不显示实体内容，仅用占位符提示；
    用户主动加载或直接粘贴后再保存。保存时仅在内容非空时覆盖原配置，避免空值覆盖持久化内容。
    """
    
    def __init__(self, title: str, current: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 560)
        self._current = current or {}
        self._loaded = False
        self.logger = ErrorHandler.setup_logging("advanced_json")
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """设置UI界面"""
        layout = QVBoxLayout(self)
        
        # 提示信息
        tip = QLabel("为保护敏感信息，默认不显示实体内容。可点击'加载当前内容'查看/编辑，或直接粘贴新内容保存。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        
        # 编辑器
        self.editor = QTextEdit()
        saved_len = len(json.dumps(self._current, ensure_ascii=False)) if self._current else 0
        self.editor.setPlaceholderText(
            f"已保存 {saved_len} 字内容（点击下方'加载当前内容'以查看/修改，或直接粘贴新内容）"
        )
        layout.addWidget(self.editor, 1)
        
        # 加载按钮行
        row = QHBoxLayout()
        self.btn_load = QPushButton("加载当前内容")
        self.btn_load.clicked.connect(self._load_current)
        row.addWidget(self.btn_load)
        row.addStretch(1)
        layout.addLayout(row)
        
        # 对话框按钮
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
    
    def _load_current(self) -> None:
        """加载当前内容到编辑器"""
        try:
            text = json.dumps(self._current, ensure_ascii=False, indent=2)
            self.editor.setPlainText(text)
            self._loaded = True
            self.logger.info("当前内容已加载到编辑器")
        except Exception as e:
            self.logger.exception(f"加载当前内容失败: {e}")
            ErrorHandler.handle_ui_error(self, "加载失败", e)
    
    def get_result(self) -> Optional[Dict[str, Any]]:
        """获取编辑结果"""
        text = (self.editor.toPlainText() or "").strip()
        if not text:
            return None  # 不覆盖原配置
        
        try:
            result = json.loads(text)
            self.logger.info("JSON解析成功")
            return result
        except json.JSONDecodeError as e:
            self.logger.exception(f"JSON解析失败: {e}")
            ErrorHandler.handle_ui_error(self, "解析失败", Exception(f"JSON 解析错误：{e}"))
            return None
        except Exception as e:
            self.logger.exception(f"获取结果失败: {e}")
            ErrorHandler.handle_ui_error(self, "获取结果失败", e)
            return None
    
    def validate_json(self) -> bool:
        """验证JSON格式"""
        text = (self.editor.toPlainText() or "").strip()
        if not text:
            return True  # 空内容视为有效
        
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError as e:
            ErrorHandler.handle_warning(
                self, "JSON格式错误", 
                f"第{e.lineno}行，第{e.colno}列：{e.msg}"
            )
            return False
        except Exception as e:
            ErrorHandler.handle_warning(self, "验证失败", str(e))
            return False
    
    def accept(self) -> None:
        """接受对话框"""
        if self.validate_json():
            super().accept()
        # 如果验证失败，不关闭对话框
