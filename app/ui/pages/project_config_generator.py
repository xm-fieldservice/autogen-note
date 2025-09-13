# -*- coding: utf-8 -*-
"""
项目配置生成器（配置即功能）
- 可视化创建/编辑 `config/projects/*.json`
- 最小字段：project、memory、embedding、retrieval_profiles、archive、security、governance、agent
- 仅进行基本校验与保存，不引入后端依赖
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QFileDialog, QGroupBox, QFormLayout, QMessageBox, QComboBox,
    QSpinBox, QCheckBox, QApplication, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from ui.pages.shared.layout import TwoOrThreeColumn

_DEFAULT_TEMPLATE: Dict[str, Any] = {
    "project": "vector_demo",
    "memory": {
        "backend": "chromadb",
        "persist_directory": "data/autogen_official_memory/vector_demo/",
        "collection_name": "vector_demo_assistant",
        "distance_metric": "cosine",
        "k": 8,
        "score_threshold": 0.25,
        "embedding": "sentence-transformers/all-MiniLM-L6-v2"
    },
    "embedding": {
        "provider": "st",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": 384,
        "normalize": True,
        "api_profile": "default"
    },
    "retrieval_profiles": {
        "qa_default": { "k": 8, "score_threshold": 0.25 },
        "long_doc": { "k": 15, "score_threshold": 0.15, "rerank": True },
        "log_search": { "k": 5, "score_threshold": 0.35 }
    },
    "archive": {
        "root": "data/archive/vector_demo/",
        "retention_days": 365,
        "versioning": True
    },
    "security": {
        "allow_download": True,
        "require_signed_url": True
    },
    "governance": {
        "pii_in_metadata": False,
        "notes": "敏感信息仅保留在原始库域"
    },
    "agent": {
        "name": "assistant",
        "model": "gpt-4o-mini",
        "tools": [],
        "memory_attached": True
    }
}


class ProjectConfigGeneratorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg: Dict[str, Any] = json.loads(json.dumps(_DEFAULT_TEMPLATE, ensure_ascii=False))
        self._cfg_path: Optional[str] = None
        self._setup_ui()
        self._bind_param_change_signals()

    def _setup_ui(self):
        # 根布局 + 三栏容器
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("向量库"))
        header.addStretch(1)
        layout.addLayout(header)

        self.columns = TwoOrThreeColumn()
        self.columns.set_always_show_right(True)
        self.columns.set_persist_key("project_cfg_generator_splitter")
        layout.addWidget(self.columns, 1)

        # 左栏：项目列表 + 搜索（可选增强）
        left = QWidget(); l = QVBoxLayout(left)
        l.setContentsMargins(8, 8, 8, 8)
        self.ed_search = QLineEdit(); self.ed_search.setPlaceholderText("搜索向量库（文件名）")
        self.lst_projects = QListWidget()
        l.addWidget(self.ed_search)
        l.addWidget(self.lst_projects, 1)

        # 中栏：原有表单与操作区
        center = QWidget(); c = QVBoxLayout(center)
        c.setContentsMargins(8, 8, 8, 8)

        # 顶部：基本字段
        box_basic = QGroupBox("基本信息")
        form = QFormLayout()
        self.txt_project = QLineEdit(self._cfg.get("project", ""))
        self.txt_project.setToolTip("项目标识；同时作为默认集合与归档目录的命名参考")
        form.addRow("项目:", self.txt_project)

        # memory 段
        self.txt_mem_dir = QLineEdit(self._cfg["memory"].get("persist_directory", ""))
        self.txt_mem_dir.setToolTip("向量库持久化目录（Chroma 本地数据目录）。建议放置于 data/ 路径下")
        btn_pick_mem_dir = QPushButton("选择…")
        btn_pick_mem_dir.setMaximumWidth(70)
        row_mem_dir = QHBoxLayout(); row_mem_dir.addWidget(self.txt_mem_dir); row_mem_dir.addWidget(btn_pick_mem_dir)

        self.txt_mem_collection = QLineEdit(self._cfg["memory"].get("collection_name", ""))
        self.txt_mem_collection.setToolTip("Chroma 集合名称（对应一个独立的向量集合）")

        self.cmb_metric = QComboBox(); self.cmb_metric.addItems(["cosine", "l2", "ip"]) 
        self.cmb_metric.setCurrentText(self._cfg["memory"].get("distance_metric", "cosine"))
        self.cmb_metric.setToolTip("相似度度量：cosine（余弦）、l2（欧氏）、ip（内积）")

        self.spn_k = QSpinBox(); self.spn_k.setRange(1, 100); self.spn_k.setValue(int(self._cfg["memory"].get("k", 8)))
        self.spn_k.setToolTip("每次检索返回的候选向量条数")

        self.txt_threshold = QLineEdit(str(self._cfg["memory"].get("score_threshold", 0.25)))
        self.txt_threshold.setToolTip("相似度分数阈值（过滤低相关结果）")

        form.addRow("持久化目录:", row_mem_dir)
        form.addRow("集合名称:", self.txt_mem_collection)
        form.addRow("距离度量:", self.cmb_metric)
        form.addRow("候选数量k:", self.spn_k)
        form.addRow("分数阈值:", self.txt_threshold)
        box_basic.setLayout(form)
        c.addWidget(box_basic)

        # 嵌入与归档
        box_emb = QGroupBox("嵌入与归档")
        emb_form = QFormLayout()
        self.cmb_provider = QComboBox(); self.cmb_provider.addItems(["st", "openai", "azure"]) 
        self.cmb_provider.setCurrentText(self._cfg["embedding"].get("provider", "st"))
        self.cmb_provider.setToolTip("嵌入提供方：st(Open-Source)、openai、azure")
        self.txt_emb_model = QLineEdit(self._cfg["embedding"].get("model", ""))
        self.txt_emb_model.setToolTip("嵌入模型名称，如 sentence-transformers/all-MiniLM-L6-v2")
        self.txt_emb_dim = QLineEdit(str(self._cfg["embedding"].get("dim", 384)))
        self.txt_emb_dim.setToolTip("嵌入向量维度")
        self.chk_norm = QCheckBox("标准化"); self.chk_norm.setChecked(bool(self._cfg["embedding"].get("normalize", True)))
        self.chk_norm.setToolTip("是否对嵌入向量进行归一化处理")
        self.txt_api_profile = QLineEdit(self._cfg["embedding"].get("api_profile", "default"))
        self.txt_api_profile.setToolTip("调用外部API时使用的配置档案名（本地知识库内定义）")

        self.txt_archive_root = QLineEdit(self._cfg["archive"].get("root", ""))
        self.txt_archive_root.setToolTip("归档根目录：用于存放项目归档/版本快照/导出数据，不影响在线检索库")
        btn_pick_archive_root = QPushButton("选择…")
        btn_pick_archive_root.setMaximumWidth(70)
        row_archive_root = QHBoxLayout(); row_archive_root.addWidget(self.txt_archive_root); row_archive_root.addWidget(btn_pick_archive_root)

        self.txt_retention = QLineEdit(str(self._cfg["archive"].get("retention_days", 365)))
        self.txt_retention.setToolTip("归档文件保留天数；超期可由外部任务清理")

        emb_form.addRow("嵌入提供方:", self.cmb_provider)
        emb_form.addRow("嵌入模型:", self.txt_emb_model)
        emb_form.addRow("向量维度:", self.txt_emb_dim)
        emb_form.addRow("向量标准化:", self.chk_norm)
        emb_form.addRow("API配置档案:", self.txt_api_profile)
        emb_form.addRow("归档根目录:", row_archive_root)
        emb_form.addRow("归档保留天数:", self.txt_retention)
        box_emb.setLayout(emb_form)
        c.addWidget(box_emb)

        # 操作按钮
        row = QHBoxLayout()
        btn_new = QPushButton("从模板新建")
        btn_load = QPushButton("加载现有配置…")
        btn_save = QPushButton("保存配置")
        btn_save_as = QPushButton("另存为…")
        self.btn_generate_override = QPushButton("生成配置文件(覆盖)")
        self.btn_copy = QPushButton("复制")
        self.chk_auto_generate = QCheckBox("参数变更自动生成")
        btn_new.clicked.connect(self._on_new)
        btn_load.clicked.connect(self._on_load)
        btn_save.clicked.connect(self._on_save)
        btn_save_as.clicked.connect(self._on_save_as)
        self.btn_generate_override.clicked.connect(self._on_generate_override)
        self.btn_copy.clicked.connect(self._on_copy_to_clipboard)
        # 路径选择器
        btn_pick_mem_dir.clicked.connect(self._on_pick_mem_dir)
        btn_pick_archive_root.clicked.connect(self._on_pick_archive_root)
        row.addWidget(btn_new)
        row.addWidget(btn_load)
        row.addWidget(btn_save)
        row.addWidget(btn_save_as)
        row.addWidget(self.btn_generate_override)
        row.addWidget(self.btn_copy)
        row.addWidget(self.chk_auto_generate)
        row.addStretch(1)
        c.addLayout(row)

        # 右栏：只读预览
        right = QWidget(); r = QVBoxLayout(right)
        r.setContentsMargins(8, 8, 8, 8)
        self.txt_out = QTextEdit(); self.txt_out.setReadOnly(True); self.txt_out.setMinimumHeight(160)
        r.addWidget(self.txt_out, 1)

        # 三栏装配
        self.columns.set_left(left)
        self.columns.set_center(center)
        self.columns.set_right(right)

        # 左栏数据与搜索绑定
        self._load_project_list()
        self.ed_search.returnPressed.connect(self._load_project_list)
        self.lst_projects.currentItemChanged.connect(self._on_select_project)

        # 初始化右侧预览
        self._refresh_out()

    def _on_pick_mem_dir(self):
        """选择向量库持久化目录（文件夹）。"""
        base_dir = str((Path.cwd() / 'data').resolve())
        path = QFileDialog.getExistingDirectory(self, "选择持久化目录", base_dir)
        if path:
            self.txt_mem_dir.setText(path.replace('\\', '/'))

    def _on_pick_archive_root(self):
        """选择归档根目录（文件夹）。"""
        base_dir = str((Path.cwd() / 'data' / 'archive').resolve())
        path = QFileDialog.getExistingDirectory(self, "选择归档根目录", base_dir)
        if path:
            self.txt_archive_root.setText(path.replace('\\', '/'))

    def _bind_param_change_signals(self):
        """参数变更 -> 自动生成（当勾选 且 已有路径）"""
        def _try_auto_gen():
            if not getattr(self, 'chk_auto_generate', None) or not self.chk_auto_generate.isChecked():
                return
            if not self._cfg_path:
                return
            self._on_generate_override(silent=True)

        # 基本字段
        self.txt_project.textChanged.connect(lambda *_: _try_auto_gen())
        # memory 段
        self.txt_mem_dir.textChanged.connect(lambda *_: _try_auto_gen())
        self.txt_mem_collection.textChanged.connect(lambda *_: _try_auto_gen())
        self.cmb_metric.currentIndexChanged.connect(lambda *_: _try_auto_gen())
        self.spn_k.valueChanged.connect(lambda *_: _try_auto_gen())
        self.txt_threshold.textChanged.connect(lambda *_: _try_auto_gen())
        # 嵌入与归档
        self.cmb_provider.currentIndexChanged.connect(lambda *_: _try_auto_gen())
        self.txt_emb_model.textChanged.connect(lambda *_: _try_auto_gen())
        self.txt_emb_dim.textChanged.connect(lambda *_: _try_auto_gen())
        self.chk_norm.stateChanged.connect(lambda *_: _try_auto_gen())
        self.txt_api_profile.textChanged.connect(lambda *_: _try_auto_gen())
        self.txt_archive_root.textChanged.connect(lambda *_: _try_auto_gen())
        self.txt_retention.textChanged.connect(lambda *_: _try_auto_gen())

    # =============== 新增：生成配置（覆盖写入） ===============
    def _on_generate_override(self, silent: bool = False):
        """标准化当前参数并更新底部阅读框；若已设置目标路径则同步覆盖写入。
        - 始终在阅读框显示“标准化后的最终 JSON”；
        - 若未设置路径：仅更新阅读框（不弹警告、不写盘）；
        - 若已设置路径：覆盖写入并在非 silent 情况下提示成功。
        """
        try:
            # 延迟导入 standardize，避免顶层导入失败影响页面加载
            try:
                from scripts.agent_config_gen import standardize  # type: ignore
            except Exception:
                import sys
                from pathlib import Path as _Path
                root = _Path(__file__).resolve().parents[3]
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                from scripts.agent_config_gen import standardize  # type: ignore

            raw_cfg = self._collect_cfg()
            std_cfg = standardize(raw_cfg)

            # 刷新内存与展示（阅读框显示标准化后的最终内容）
            self._cfg = std_cfg
            self.txt_out.setPlainText(json.dumps(std_cfg, ensure_ascii=False, indent=2))

            # 若已有路径，则覆盖写入
            if self._cfg_path:
                try:
                    Path(self._cfg_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(self._cfg_path, 'w', encoding='utf-8') as f:
                        json.dump(std_cfg, f, ensure_ascii=False, indent=2)
                    if not silent:
                        QMessageBox.information(self, "提示", f"已生成并覆盖：{self._cfg_path}")
                except Exception as _e:
                    if not silent:
                        QMessageBox.critical(self, "错误", f"写入文件失败: {_e}")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "错误", f"生成失败: {e}")

    def _refresh_out(self):
        self.txt_out.setPlainText(json.dumps(self._collect_cfg(), ensure_ascii=False, indent=2))

    # =============== 左栏项目列表（新增） ===============
    def _load_project_list(self):
        """加载 config/projects 下的 JSON 列表，按搜索关键字过滤。"""
        try:
            self.lst_projects.clear()
            proj_dir = Path.cwd() / 'config' / 'vectorstores'
            proj_dir.mkdir(parents=True, exist_ok=True)
            keyword = (self.ed_search.text() or '').strip().lower()
            for p in sorted(proj_dir.glob('*.json')):
                name = p.stem
                if keyword and keyword not in name.lower():
                    continue
                it = QListWidgetItem(name)
                it.setData(Qt.UserRole, str(p))
                self.lst_projects.addItem(it)
        except Exception:
            pass

    def _on_select_project(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None):  # noqa: ARG002
        """选择列表项即加载该配置到表单与右侧预览（静默失败）。"""
        try:
            if not cur:
                return
            path = cur.data(Qt.UserRole)
            if not path:
                return
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            self._cfg_path = path
            self._cfg = data
            self._fill_form_from_config(data)
            self._refresh_out()
        except Exception:
            pass

    def _fill_form_from_config(self, data: Dict[str, Any]):
        """将配置数据回填到表单控件（与 _on_load 的回填逻辑一致）。"""
        try:
            self.txt_project.setText(str(data.get('project', '')))
            mem = data.get('memory', {}) if isinstance(data.get('memory'), dict) else {}
            self.txt_mem_dir.setText(str(mem.get('persist_directory', '')))
            self.txt_mem_collection.setText(str(mem.get('collection_name', '')))
            self.cmb_metric.setCurrentText(str(mem.get('distance_metric', 'cosine')))
            try:
                self.spn_k.setValue(int(mem.get('k', 8)))
            except Exception:
                self.spn_k.setValue(8)
            self.txt_threshold.setText(str(mem.get('score_threshold', 0.25)))
            emb = data.get('embedding', {}) if isinstance(data.get('embedding'), dict) else {}
            self.cmb_provider.setCurrentText(str(emb.get('provider', 'st')))
            self.txt_emb_model.setText(str(emb.get('model', '')))
            self.txt_emb_dim.setText(str(emb.get('dim', 384)))
            self.chk_norm.setChecked(bool(emb.get('normalize', True)))
            self.txt_api_profile.setText(str(emb.get('api_profile', 'default')))
            arch = data.get('archive', {}) if isinstance(data.get('archive'), dict) else {}
            self.txt_archive_root.setText(str(arch.get('root', '')))
            self.txt_retention.setText(str(arch.get('retention_days', 365)))
        except Exception:
            pass

    def _collect_cfg(self) -> Dict[str, Any]:
        cfg = json.loads(json.dumps(_DEFAULT_TEMPLATE, ensure_ascii=False))
        cfg["project"] = self.txt_project.text().strip() or "vector_demo"
        mem = cfg["memory"]
        mem["persist_directory"] = self.txt_mem_dir.text().strip() or mem["persist_directory"]
        mem["collection_name"] = self.txt_mem_collection.text().strip() or mem["collection_name"]
        mem["distance_metric"] = self.cmb_metric.currentText().strip()
        mem["k"] = int(self.spn_k.value())
        try:
            mem["score_threshold"] = float(self.txt_threshold.text().strip())
        except Exception:
            mem["score_threshold"] = 0.25
        emb = cfg["embedding"]
        emb["provider"] = self.cmb_provider.currentText().strip()
        emb["model"] = self.txt_emb_model.text().strip() or emb["model"]
        try:
            emb["dim"] = int(float(self.txt_emb_dim.text().strip()))
        except Exception:
            emb["dim"] = 384
        emb["normalize"] = bool(self.chk_norm.isChecked())
        emb["api_profile"] = self.txt_api_profile.text().strip() or "default"
        arch = cfg["archive"]
        arch["root"] = self.txt_archive_root.text().strip() or arch["root"]
        try:
            arch["retention_days"] = int(float(self.txt_retention.text().strip()))
        except Exception:
            arch["retention_days"] = 365
        return cfg

    def _on_copy_to_clipboard(self):
        try:
            text = self.txt_out.toPlainText() or ""
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "提示", "已复制到剪贴板")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"复制失败: {e}")

    def _on_new(self):
        self._cfg = json.loads(json.dumps(_DEFAULT_TEMPLATE, ensure_ascii=False))
        self._cfg_path = None
        # 重置输入框
        self.txt_project.setText(self._cfg.get("project", "vector_demo"))
        self.txt_mem_dir.setText(self._cfg["memory"].get("persist_directory", ""))
        self.txt_mem_collection.setText(self._cfg["memory"].get("collection_name", ""))
        self.cmb_metric.setCurrentText(self._cfg["memory"].get("distance_metric", "cosine"))
        self.spn_k.setValue(int(self._cfg["memory"].get("k", 8)))
        self.txt_threshold.setText(str(self._cfg["memory"].get("score_threshold", 0.25)))
        self.cmb_provider.setCurrentText(self._cfg["embedding"].get("provider", "st"))
        self.txt_emb_model.setText(self._cfg["embedding"].get("model", ""))
        self.txt_emb_dim.setText(str(self._cfg["embedding"].get("dim", 384)))
        self.chk_norm.setChecked(bool(self._cfg["embedding"].get("normalize", True)))
        self.txt_api_profile.setText(self._cfg["embedding"].get("api_profile", "default"))
        self.txt_archive_root.setText(self._cfg["archive"].get("root", ""))
        self.txt_retention.setText(str(self._cfg["archive"].get("retention_days", 365)))
        self._refresh_out()

    def _on_load(self):
        proj_dir = str(Path.cwd() / 'config' / 'vectorstores')
        path, _ = QFileDialog.getOpenFileName(self, "选择配置", proj_dir, "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSON 根必须是对象")
            self._cfg = data
            self._cfg_path = path
            # 回填到UI
            self.txt_project.setText(str(data.get('project', '')))
            mem = data.get('memory', {})
            self.txt_mem_dir.setText(str(mem.get('persist_directory', '')))
            self.txt_mem_collection.setText(str(mem.get('collection_name', '')))
            self.cmb_metric.setCurrentText(str(mem.get('distance_metric', 'cosine')))
            try:
                self.spn_k.setValue(int(mem.get('k', 8)))
            except Exception:
                self.spn_k.setValue(8)
            self.txt_threshold.setText(str(mem.get('score_threshold', 0.25)))
            emb = data.get('embedding', {})
            self.cmb_provider.setCurrentText(str(emb.get('provider', 'st')))
            self.txt_emb_model.setText(str(emb.get('model', '')))
            self.txt_emb_dim.setText(str(emb.get('dim', 384)))
            self.chk_norm.setChecked(bool(emb.get('normalize', True)))
            self.txt_api_profile.setText(str(emb.get('api_profile', 'default')))
            arch = data.get('archive', {})
            self.txt_archive_root.setText(str(arch.get('root', '')))
            self.txt_retention.setText(str(arch.get('retention_days', 365)))
            self._refresh_out()
            try:
                from PySide6.QtCore import QSettings
                s = QSettings("NeuralAgent", "DesktopApp")
                s.setValue("vector/last_project_config_path", path)
                s.sync()
            except Exception:
                pass
            QMessageBox.information(self, "提示", f"已加载：{os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败: {e}")

    def _on_save(self):
        if not self._cfg_path:
            return self._on_save_as()
        self._save_to(self._cfg_path)

    def _on_save_as(self):
        proj_dir = Path.cwd() / 'config' / 'vectorstores'
        proj_dir.mkdir(parents=True, exist_ok=True)
        default_name = (self.txt_project.text().strip() or 'vector_demo') + '.json'
        path, _ = QFileDialog.getSaveFileName(self, "另存为", str(proj_dir / default_name), "JSON Files (*.json)")
        if not path:
            return
        self._save_to(path)

    def _save_to(self, path: str):
        try:
            cfg = self._collect_cfg()
            # 持久化
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self._cfg_path = path
            self._cfg = cfg
            self._refresh_out()
            # 记忆最近路径
            try:
                from PySide6.QtCore import QSettings
                s = QSettings("NeuralAgent", "DesktopApp")
                s.setValue("vector/last_project_config_path", path)
                s.sync()
            except Exception:
                pass
            QMessageBox.information(self, "提示", f"已保存：{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
