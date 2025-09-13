# -*- coding: utf-8 -*-
"""
历史记录对话框
从app.py中提取的HistoryDialog类
"""
import json
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, 
    QTextEdit, QDialogButtonBox, QWidget, QMessageBox
)
from PySide6.QtCore import Qt

from config.constants import Paths
from utils.error_handler import ErrorHandler


class HistoryDialog(QDialog):
    """简易历史查看器：按域读取 logs/<domain> 下的 JSONL 历史文件并展示内容（只读）"""
    
    def __init__(self, domain: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"查看历史 - {domain}")
        self.resize(800, 600)
        self.domain = domain
        self.logger = ErrorHandler.setup_logging("history_dialog")
        
        self._setup_ui()
        self._load_file_list()
    
    def _setup_ui(self) -> None:
        """设置UI界面"""
        layout = QVBoxLayout(self)
        
        # 主要内容区域
        row = QHBoxLayout()
        
        # 文件列表
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        row.addWidget(self.list, 1)
        
        # 内容查看器
        self.viewer = QTextEdit()
        self.viewer.setReadOnly(True)
        row.addWidget(self.viewer, 2)
        
        layout.addLayout(row, 1)
        
        # 按钮
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)
    
    def _load_file_list(self) -> None:
        """加载文件列表"""
        try:
            # 获取日志目录
            logs_dir = Paths.get_absolute_path(Paths.LOGS_DIR)
            domain_dir = logs_dir / self.domain
            
            if not domain_dir.exists():
                self.logger.warning(f"历史目录不存在: {domain_dir}")
                return
            
            # 查找JSONL文件
            jsonl_files = list(domain_dir.glob("*.jsonl"))
            log_files = list(domain_dir.glob("*.log"))
            
            # 添加到列表
            all_files = sorted(jsonl_files + log_files, key=lambda f: f.stat().st_mtime, reverse=True)
            
            for file_path in all_files:
                item = QListWidgetItem(file_path.name)
                item.setData(Qt.ItemDataRole.UserRole, str(file_path))
                self.list.addItem(item)
            
            # 默认选择第一个文件
            if self.list.count() > 0:
                self.list.setCurrentRow(0)
                
            self.logger.info(f"加载了 {len(all_files)} 个历史文件")
            
        except Exception as e:
            self.logger.exception(f"加载文件列表失败: {e}")
            ErrorHandler.handle_ui_error(self, "加载失败", e)
    
    def _on_select(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        """选择文件时的处理"""
        if not current:
            self.viewer.clear()
            return
        
        file_path = current.data(Qt.ItemDataRole.UserRole)
        if not file_path:
            return
        
        try:
            path = Path(file_path)
            if not path.exists():
                self.viewer.setPlainText(f"文件不存在：{file_path}")
                return
            
            # 读取文件内容
            with path.open("r", encoding="utf-8") as f:
                content = f.read()
            
            # 如果是JSONL文件，尝试格式化显示
            if path.suffix.lower() == ".jsonl":
                formatted_content = self._format_jsonl_content(content)
                self.viewer.setPlainText(formatted_content)
            else:
                self.viewer.setPlainText(content)
                
            self.logger.info(f"显示文件内容: {path.name}")
            
        except Exception as e:
            self.logger.exception(f"读取文件失败: {e}")
            self.viewer.setPlainText(f"读取失败：{e}")
    
    def _format_jsonl_content(self, content: str) -> str:
        """格式化JSONL内容为可读格式"""
        try:
            lines = content.strip().split('\n')
            formatted_lines = []
            
            for i, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # 解析JSON
                    obj = json.loads(line)
                    
                    # 格式化显示
                    timestamp = obj.get("ts", "")
                    model = obj.get("model", "")
                    prompt = obj.get("prompt", "")
                    reply = obj.get("reply", "")
                    
                    formatted_lines.append(f"=== 记录 {i} ===")
                    if timestamp:
                        formatted_lines.append(f"时间: {timestamp}")
                    if model:
                        formatted_lines.append(f"模型: {model}")
                    if prompt:
                        formatted_lines.append(f"问题: {prompt}")
                    if reply:
                        formatted_lines.append(f"回答: {reply}")
                    formatted_lines.append("")
                    
                except json.JSONDecodeError:
                    # 如果不是有效JSON，直接显示原文
                    formatted_lines.append(f"第{i}行: {line}")
                    formatted_lines.append("")
            
            return '\n'.join(formatted_lines)
            
        except Exception as e:
            self.logger.exception(f"格式化JSONL内容失败: {e}")
            return content  # 返回原始内容


class LegacyHistoryDialog(QDialog):
    """兼容旧版本的历史对话框"""
    
    def __init__(self, parent: Optional[QWidget], history_path: Path):
        super().__init__(parent)
        self.setWindowTitle("会话历史")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        
        try:
            if history_path.exists():
                with history_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            ts = obj.get("ts", "")
                            model = obj.get("model", "")
                            prompt = obj.get("prompt", "")
                            reply = obj.get("reply", "")
                            item = QListWidgetItem(f"[{ts}] model={model}\nQ: {prompt}\nA: {reply}\n")
                            self.list.addItem(item)
                        except Exception:
                            continue
        except Exception as e:
            QMessageBox.warning(self, "历史读取失败", str(e))
