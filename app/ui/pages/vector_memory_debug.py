# -*- coding: utf-8 -*-
"""
向量内存调试页面（本地选项卡）
- 目的：在不破坏现有流程的前提下，提供一个独立的UI用于加载项目配置、进行参数预检、路径检查，并为后续接入
  Autogen 0.7.1 内生 Memory（如 ChromaDBVectorMemory）预留挂点。
- 原则：
  1) 不引入数据库依赖；
  2) 不直接实现自定义检索管线；
  3) 先完成UI与配置预检，后续再接入冒烟测试与真实 add/query；
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
import sys
import subprocess
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QFileDialog, QGroupBox, QFormLayout, QMessageBox, QSpinBox,
    QCheckBox
)
from PySide6.QtCore import Qt


class VectorMemoryDebugPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg_path: Optional[str] = None
        self._cfg: Optional[Dict[str, Any]] = None
        self._setup_ui()
        # 启动时自动读取最近保存/加载的配置路径
        try:
            from PySide6.QtCore import QSettings
            s = QSettings("NeuralAgent", "DesktopApp")
            last = s.value("vector/last_project_config_path")
            if isinstance(last, str) and last.strip():
                self.txt_cfg_path.setText(last.strip())
        except Exception:
            pass

    # UI 构造
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 顶部：配置选择
        box_cfg = QGroupBox("项目配置（config/projects/*.json）")
        form = QFormLayout()
        self.txt_cfg_path = QLineEdit()
        self.txt_cfg_path.setPlaceholderText("选择一个项目配置文件 …")
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._on_browse_cfg)
        row = QHBoxLayout()
        row.addWidget(self.txt_cfg_path)
        row.addWidget(btn_browse)
        form.addRow("配置文件：", row)
        box_cfg.setLayout(form)
        layout.addWidget(box_cfg)

        # 中部：操作按钮
        btn_row = QHBoxLayout()
        self.btn_load = QPushButton("加载/预检配置")
        self.btn_load.clicked.connect(self._on_load_cfg)
        self.btn_check_paths = QPushButton("检查路径并创建(如需)")
        self.btn_check_paths.clicked.connect(self._on_check_paths)
        self.btn_open_mem_dir = QPushButton("打开向量库目录")
        self.btn_open_mem_dir.clicked.connect(self._on_open_mem_dir)
        self.chk_verbose = QCheckBox("详细日志")
        btn_row.addWidget(self.btn_load)
        btn_row.addWidget(self.btn_check_paths)
        btn_row.addWidget(self.btn_open_mem_dir)
        btn_row.addStretch(1)
        btn_row.addWidget(self.chk_verbose)
        layout.addLayout(btn_row)

        # 结果输出
        self.txt_output = QTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setMinimumHeight(220)
        layout.addWidget(self.txt_output)

        # 预留：后续接入 Autogen 内生 Memory 的按钮（先占位禁用）
        btn_row2 = QHBoxLayout()
        self.btn_init_memory = QPushButton("初始化/写入样本")
        self.btn_add_sample = QPushButton("追加样本")
        self.btn_query_once = QPushButton("运行查询")
        self.btn_init_memory.clicked.connect(lambda: self._run_smoke("add"))
        self.btn_add_sample.clicked.connect(lambda: self._run_smoke("add"))
        self.btn_query_once.clicked.connect(lambda: self._run_smoke("query"))
        btn_row2.addWidget(self.btn_init_memory)
        btn_row2.addWidget(self.btn_add_sample)
        btn_row2.addWidget(self.btn_query_once)
        btn_row2.addStretch(1)
        layout.addLayout(btn_row2)

        # 提示
        tip = QLabel("说明：当前页面仅完成配置加载与预检。真实 Memory 调用将在冒烟测试与CI接入后启用。")
        tip.setStyleSheet("color: #888;")
        layout.addWidget(tip)

    # 事件
    def _on_browse_cfg(self):
        proj_dir = str(Path.cwd() / 'config' / 'projects')
        path, _ = QFileDialog.getOpenFileName(self, "选择项目配置", proj_dir, "JSON Files (*.json)")
        if path:
            self.txt_cfg_path.setText(path)

    def _append_out(self, text: str):
        try:
            if self.chk_verbose.isChecked():
                self.txt_output.append(text)
            else:
                # 非详细模式，限制输出行数
                lines = self.txt_output.toPlainText().splitlines()
                if len(lines) > 800:
                    self.txt_output.clear()
                self.txt_output.append(text)
        except Exception:
            pass

    def _on_load_cfg(self):
        path = self.txt_cfg_path.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择配置文件")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "提示", "配置文件不存在")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._cfg_path = path
            self._cfg = data if isinstance(data, dict) else {}
            self._append_out(f"[OK] 已加载配置: {os.path.basename(path)}")
            self._append_out(self._summarize_cfg(self._cfg))
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载配置失败: {e}")

    def _summarize_cfg(self, cfg: Dict[str, Any]) -> str:
        try:
            mem = cfg.get('memory', {}) if isinstance(cfg, dict) else {}
            arch = cfg.get('archive', {}) if isinstance(cfg, dict) else {}
            emb = cfg.get('embedding', cfg.get('memory', {}).get('embedding'))
            profiles = cfg.get('retrieval_profiles', {})
            lines = [
                "[配置摘要]",
                f"- backend: {mem.get('backend', '-')} | collection: {mem.get('collection_name', '-')}",
                f"- persist: {mem.get('persist_directory', '-')}",
                f"- metric: {mem.get('distance_metric', '-')}",
                f"- k/threshold: {mem.get('k', '-')}/{mem.get('score_threshold', '-')}",
                f"- embedding: {emb}",
                f"- archive.root: {arch.get('root', '-')}",
                f"- retrieval_profiles: {list(profiles.keys()) if isinstance(profiles, dict) else '-'}",
            ]
            return "\n".join(lines)
        except Exception:
            return "[WARN] 配置摘要生成失败"

    def _on_check_paths(self):
        cfg = self._cfg or {}
        mem = cfg.get('memory', {}) if isinstance(cfg, dict) else {}
        arch = cfg.get('archive', {}) if isinstance(cfg, dict) else {}
        created = []
        for p in [mem.get('persist_directory'), arch.get('root')]:
            if not p:
                continue
            try:
                abs_path = Path(p)
                if not abs_path.is_absolute():
                    abs_path = Path.cwd() / p
                if not abs_path.exists():
                    abs_path.mkdir(parents=True, exist_ok=True)
                    created.append(str(abs_path))
            except Exception as e:
                self._append_out(f"[ERR] 路径处理失败 {p}: {e}")
        if created:
            self._append_out("[OK] 已创建目录:\n- " + "\n- ".join(created))
        else:
            self._append_out("[OK] 目录已存在或未配置，无需创建")

    def _on_open_mem_dir(self):
        cfg = self._cfg or {}
        mem = cfg.get('memory', {}) if isinstance(cfg, dict) else {}
        p = mem.get('persist_directory')
        if not p:
            QMessageBox.information(self, "提示", "未配置 persist_directory")
            return
        path = Path(p)
        if not path.is_absolute():
            path = Path.cwd() / p
        try:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            # Windows 平台打开资源管理器
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as e:
            QMessageBox.warning(self, "提示", f"打开目录失败: {e}")

    # 运行冒烟脚本
    def _run_smoke(self, mode: str):
        cfg_path = (self.txt_cfg_path.text() or "").strip()
        if not cfg_path or not os.path.exists(cfg_path):
            QMessageBox.warning(self, "提示", "请先选择并加载有效的配置文件")
            return

        script_path = str(Path.cwd() / "scripts" / "smoke_vector_memory.py")
        if not os.path.exists(script_path):
            QMessageBox.critical(self, "错误", f"未找到脚本: {script_path}")
            return

        def worker():
            try:
                cmd = [sys.executable, script_path, "--config", cfg_path, "--mode", mode]
                self._append_out(f"[RUN] {' '.join(cmd)}")
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.stdout:
                    self._append_out(p.stdout.strip())
                if p.stderr:
                    self._append_out("[STDERR]\n" + p.stderr.strip())
                self._append_out(f"[DONE] exit={p.returncode}")
            except Exception as e:
                self._append_out(f"[ERR] 运行失败: {e}")

        threading.Thread(target=worker, daemon=True).start()
