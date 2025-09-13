# -*- coding: utf-8 -*-
"""
共享配置表单组件（适配 model / agent / team）
- ConfigFormParser: 解析 JSON 配置为统一的字段描述
- ConfigFormWidget: 动态渲染参数表单、支持回填与取值

设计原则：
- 不做隐式归一化写回磁盘；仅用于 UI 层的展示与编辑
- 尽量兼容不同布局：
  - model: 顶层 或 model_client.config.* 结构
  - agent: 顶层固定字段 + model_client.config.*
  - team: 顶层固定字段 + agents / model_client.config.*
- 字段类型推断：bool -> QCheckBox；int -> QSpinBox；float -> QDoubleSpinBox；其他 -> QLineEdit
- 字段路径以点号表示（只用于组件内部映射），例如：model_client.config.parameters.temperature

注意：
- 最终写回 dict 的路径遵循原始结构（best-effort），不会发明新字段名
- 可通过 set_readonly(True) 将所有控件设为只读
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QCheckBox,
    QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt


class ConfigFormParser:
    """将不同类型配置解析为统一字段描述"""

    def __init__(self, kind: str):
        self.kind = (kind or '').lower()  # 'model' | 'agent' | 'team'

    def parse(self, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
        """
        返回字段列表 [(path, value)]
        path 仅用于 UI 命名/分组，真实写回仍以原始结构为准（由 ConfigFormWidget 完成）。
        """
        data = data or {}
        items: List[Tuple[str, Any]] = []
        try:
            if self.kind == 'model':
                items.extend(self._parse_model(data))
            elif self.kind == 'agent':
                items.extend(self._parse_agent(data))
            elif self.kind == 'team':
                items.extend(self._parse_team(data))
            else:
                # 未知类型：直接平铺顶层
                for k, v in (data.items() if isinstance(data, dict) else []):
                    items.append((k, v))
        except Exception:
            # 失败回退：平铺顶层
            for k, v in (data.items() if isinstance(data, dict) else []):
                items.append((k, v))
        return items

    def _parse_model(self, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
        items: List[Tuple[str, Any]] = []
        # 顶层常见字段
        for key in ("name", "provider"):
            if key in data:
                items.append((key, data.get(key)))
        # 兼容 model_client.config 与 顶层 config
        mc = data.get('model_client') if isinstance(data.get('model_client'), dict) else {}
        cfg = mc.get('config') if isinstance(mc.get('config'), dict) else (data.get('config') if isinstance(data.get('config'), dict) else {})
        if isinstance(cfg, dict):
            for key in ("model", "base_url", "api_key_env", "timeout"):
                if key in cfg:
                    items.append((f"config.{key}", cfg.get(key)))
            params = cfg.get('parameters') if isinstance(cfg.get('parameters'), dict) else {}
            for k, v in params.items():
                items.append((f"config.parameters.{k}", v))
        return items

    def _parse_agent(self, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
        items: List[Tuple[str, Any]] = []
        # 顶层常见字段
        for key in ("type", "name", "role", "description", "system_message"):
            if key in data:
                items.append((key, data.get(key)))
        # 兼容 agent 的 model_client.config
        mc = data.get('model_client') if isinstance(data.get('model_client'), dict) else {}
        cfg = mc.get('config') if isinstance(mc.get('config'), dict) else {}
        if isinstance(cfg, dict):
            for key in ("model", "base_url", "api_key_env", "timeout"):
                if key in cfg:
                    items.append((f"model_client.config.{key}", cfg.get(key)))
            params = cfg.get('parameters') if isinstance(cfg.get('parameters'), dict) else {}
            for k, v in params.items():
                items.append((f"model_client.config.parameters.{k}", v))
        return items

    def _parse_team(self, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
        items: List[Tuple[str, Any]] = []
        # 顶层常见字段
        for key in ("type", "name", "description"):
            if key in data:
                items.append((key, data.get(key)))
        # team 自身若也有 model_client（极少见），同样兼容
        mc = data.get('model_client') if isinstance(data.get('model_client'), dict) else {}
        cfg = mc.get('config') if isinstance(mc.get('config'), dict) else {}
        if isinstance(cfg, dict):
            for key in ("model", "base_url", "api_key_env", "timeout"):
                if key in cfg:
                    items.append((f"model_client.config.{key}", cfg.get(key)))
            params = cfg.get('parameters') if isinstance(cfg.get('parameters'), dict) else {}
            for k, v in params.items():
                items.append((f"model_client.config.parameters.{k}", v))
        return items


class ConfigFormWidget(QWidget):
    """动态参数表单控件：根据数据渲染、支持回填和读取"""

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = (kind or '').lower()
        self._parser = ConfigFormParser(self._kind)
        self._data: Dict[str, Any] = {}
        self._controls: Dict[str, QWidget] = {}

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(self._title_text())
        self._title.setStyleSheet("font-weight: bold;")
        self._form = QFormLayout()
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._root.addWidget(self._title)
        self._root.addLayout(self._form)

    def _title_text(self) -> str:
        return {
            'model': '模型参数（共享组件）',
            'agent': 'Agent 参数（共享组件）',
            'team': 'Team 参数（共享组件）',
        }.get(self._kind, '参数（共享组件）')

    # API
    def set_data(self, data: Dict[str, Any]):
        """渲染/回填配置"""
        self._data = data or {}
        # 清空旧控件
        while self._form.rowCount():
            self._form.removeRow(0)
        self._controls.clear()

        items = self._parser.parse(self._data)
        for path, value in items:
            label = QLabel(path)
            editor = self._create_editor(value)
            self._set_editor_value(editor, value)
            self._form.addRow(label, editor)
            self._controls[path] = editor

    def get_data(self) -> Dict[str, Any]:
        """读取表单为 dict（保持原始结构 best-effort 写回）"""
        # 从原始数据拷贝，避免破坏未知结构
        import copy
        result = copy.deepcopy(self._data) if isinstance(self._data, dict) else {}

        def write_by_path(base: Dict[str, Any], path: str, val: Any):
            parts = path.split('.') if path else []
            if not parts:
                return
            cur = base
            for i, p in enumerate(parts):
                if i == len(parts) - 1:
                    cur[p] = val
                else:
                    nxt = cur.get(p)
                    if not isinstance(nxt, dict):
                        nxt = {}
                        cur[p] = nxt
                    cur = nxt

        # 将控件值按 path 写回
        for path, editor in self._controls.items():
            val = self._get_editor_value(editor)
            # 针对不同类型做路径修正（尽量保持原始结构）
            if self._kind == 'model':
                # 允许 path 前缀 "config." 直接写入到 model_client.config
                if path.startswith('config.'):
                    mc = result.get('model_client') if isinstance(result.get('model_client'), dict) else {}
                    cfg = mc.get('config') if isinstance(mc.get('config'), dict) else {}
                    mc['config'] = cfg
                    result['model_client'] = mc
                    write_by_path(cfg, path[len('config.'):], val)
                else:
                    write_by_path(result, path, val)
            else:
                write_by_path(result, path, val)
        return result

    def set_readonly(self, ro: bool):
        for w in self._controls.values():
            if isinstance(w, QLineEdit):
                w.setReadOnly(ro)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setEnabled(not ro)
            elif isinstance(w, QCheckBox):
                w.setEnabled(not ro)

    # 工具方法
    def _create_editor(self, value: Any) -> QWidget:
        if isinstance(value, bool):
            return QCheckBox()
        if isinstance(value, int) and not isinstance(value, bool):
            sp = QSpinBox(); sp.setRange(-10_000_000, 10_000_000)
            return sp
        if isinstance(value, float):
            dsp = QDoubleSpinBox(); dsp.setDecimals(6); dsp.setRange(-1e12, 1e12)
            return dsp
        return QLineEdit()

    def _set_editor_value(self, editor: QWidget, value: Any):
        if isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, QSpinBox):
            try:
                editor.setValue(int(value))
            except Exception:
                editor.setValue(0)
        elif isinstance(editor, QDoubleSpinBox):
            try:
                editor.setValue(float(value))
            except Exception:
                editor.setValue(0.0)
        elif isinstance(editor, QLineEdit):
            editor.setText('' if value is None else str(value))

    def _get_editor_value(self, editor: QWidget) -> Any:
        if isinstance(editor, QCheckBox):
            return bool(editor.isChecked())
        if isinstance(editor, QSpinBox):
            return int(editor.value())
        if isinstance(editor, QDoubleSpinBox):
            return float(editor.value())
        if isinstance(editor, QLineEdit):
            return editor.text()
        return None
