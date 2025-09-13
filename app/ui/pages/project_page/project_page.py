# -*- coding: utf-8 -*-
from PySide6.QtCore import Qt, QPoint, QSettings, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QLabel, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QComboBox, QPushButton, QFileDialog, QMenu, QInputDialog, QApplication,
    QLineEdit, QMessageBox, QCheckBox, QAbstractItemView, QStyledItemDelegate,
    QListWidget, QListWidgetItem
)
from PySide6.QtGui import QUndoStack, QUndoCommand, QAction, QShortcut
from pathlib import Path
from datetime import datetime
import os
import tempfile
import uuid
import json
import re
from utils import logger_sink
import copy as _copy


# ---------- 自定义委托：树节点标题占位提示 ----------
class _TitleEditDelegate(QStyledItemDelegate):
    def __init__(self, placeholder: str = "新节点", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        try:
            if isinstance(editor, QLineEdit):
                editor.setPlaceholderText(self._placeholder)
                try:
                    editor.setClearButtonEnabled(True)
                except Exception:
                    pass
        except Exception:
            pass
        return editor

class ProjectPage(QWidget):
    """
    Project 页面原型（方案A + 方案C细化）
    - 整体为左右两栏：左侧二级Tab，右侧详情栏
    - 左侧包含四个选项卡：资源、节点树、泳道、图谱
    - 右侧为详情（后续将支持MD/附件等）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_project_file = None  # type: Path | None
        self._drag_move_mode = False  # False=复制模式 True=移动模式
        self.undo_stack = QUndoStack(self)
        # 本地会话ID（用于MCP日志审计，会话期间保持不变）
        self._session_id = f"{datetime.now().strftime('%Y-%m-%d')}-{str(uuid.uuid4())[:10]}"
        self._new_id_seed = 1  # 新建节点的自增种子（仅前端）
        # 自动保存定时器（详情内容变更后延迟落盘，防抖）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1200)  # 1.2s 防抖
        self._autosave_timer.timeout.connect(self._autosave_flush)
        # 周期性全量保存（每20秒）
        self._periodic_save_timer = QTimer(self)
        self._periodic_save_timer.setSingleShot(False)
        self._periodic_save_timer.setInterval(20000)
        self._periodic_save_timer.timeout.connect(self._save_all_to_file)
        self._setup_ui()
        # 构建真实节点树
        try:
            self._populate_tree()
            # 恢复分割器状态
            self._restore_splitters()
            # 应用退出时持久化保存
            try:
                QApplication.instance().aboutToQuit.connect(self._on_app_about_to_quit)
            except Exception:
                pass
            # 启动周期性全量保存
            try:
                self._periodic_save_timer.start()
            except Exception:
                pass
        except Exception:
            pass

    def _action_add_to_swimlane(self, item: QTreeWidgetItem | None, include_children: bool = False):
        """将指定节点加入泳道“未开始”。
        - include_children=False: 任意节点项（type=='node'）均可加入；其他类型静默忽略
        - include_children=True: 无条件收集当前项的一层子节点中所有节点项（type=='node'）
        """
        try:
            if item is None:
                return
            fp = getattr(self, '_current_project_file', None)
            if not fp or not Path(fp).exists():
                return
            path = Path(fp)
            root = self._read_json(path)
            if root is None:
                return

            # 无条件收集待加入的节点 ID 及对应的树项：
            # - 单项：若当前项是节点项，则加入；否则静默忽略
            # - 批量：收集当前项的一层子节点中所有节点项
            targets: list[tuple[str, QTreeWidgetItem]] = []
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if include_children:
                try:
                    for i in range(item.childCount()):
                        ch = item.child(i)
                        d = ch.data(0, Qt.ItemDataRole.UserRole) or {}
                        if d.get('type') == 'node' and isinstance(d.get('node'), dict):
                            nid = d.get('node', {}).get('id')
                            if isinstance(nid, str) and nid:
                                targets.append((nid, ch))
                except Exception:
                    pass
            else:
                if data.get('type') == 'node':
                    nid = (data.get('node') or {}).get('id')
                    if isinstance(nid, str) and nid:
                        targets.append((nid, item))

            if not targets:
                return

            # 计算“计划中(planned)”列的下一个排序号
            try:
                children = root.get('children') if isinstance(root, dict) else None
                max_order = -1
                if isinstance(children, list):
                    for n in children:
                        if isinstance(n, dict) and (n.get('status') or 'planned') == 'planned':
                            try:
                                ov = int(n.get('kanban_order'))
                            except Exception:
                                ov = -1
                            if ov > max_order:
                                max_order = ov
                next_order = max_order + 1
            except Exception:
                next_order = 0

            # 写回 JSON：逐个设置 status/kanban_order（默认 status='planned'），不再强制追加任何标签
            for nid, _tree_it in targets:
                try:
                    # 更新 status/kanban_order
                    self._update_node_in_json(root, nid, {'status': 'planned', 'kanban_order': int(next_order)})
                    next_order += 1
                except Exception:
                    pass

            if not self._write_json_atomic(path, root):
                return

            # 同步树项缓存的节点字段
            for nid, tree_it in targets:
                try:
                    d = tree_it.data(0, Qt.ItemDataRole.UserRole) or {}
                    node_obj = d.get('node') or {}
                    if isinstance(node_obj, dict):
                        node_obj['status'] = 'planned'
                        try:
                            node_obj['kanban_order'] = int(node_obj.get('kanban_order', 0))
                        except Exception:
                            node_obj['kanban_order'] = 0
                        d['node'] = node_obj
                        tree_it.setData(0, Qt.ItemDataRole.UserRole, d)
                except Exception:
                    pass

            # 刷新泳道
            try:
                self._swimlane_load()
            except Exception:
                pass

            # 记录撤销与日志
            try:
                self.undo_stack.push(QUndoCommand("加入泳道(计划中)"))
            except Exception:
                pass
            try:
                logger_sink.log_user_message(self._session_id, f"add_to_swimlane: count={len(targets)}")
            except Exception:
                pass
        except Exception:
            pass

    def _format_node_label(self, node: dict) -> str:
        """生成树节点显示文本：仅显示 topic，不再附加短ID。
        - 优先 topic；若为空则显示为空字符串（配合内联编辑器的 placeholder 呈现“新节点”）。
        """
        try:
            if not isinstance(node, dict):
                return str(node)
            topic = node.get('topic')
            return str(topic) if isinstance(topic, str) else ''
        except Exception:
            return str(node)

    def _strip_short_ids_from_title(self, text: str) -> str:
        """移除标题末尾累加的短ID标记，如 '标题 [n-xxxxxxx] [n-yyyyyyy]'.
        规则：剥离结尾处连续的 [xxx] 块，保留主体标题。
        """
        try:
            if not isinstance(text, str):
                return text
            # 去掉末尾连续的方括号片段
            return re.sub(r"(\s*\[[^\]]+\])+$", "", text).strip()
        except Exception:
            return text

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 主分割器：左右两栏（持久化）
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.main_splitter)

        # 左侧：二级Tab容器
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.left_tabs = QTabWidget()
        left_layout.addWidget(self.left_tabs)

        # Tab1：资源
        tab_resources = QWidget()
        tab_resources_layout = QVBoxLayout(tab_resources)
        tab_resources_layout.addWidget(QLabel("资源（占位）：项目文件/配置（含 config/projects）、附件等"))
        self.left_tabs.addTab(tab_resources, "资源")

        # Tab2：节点树
        tab_tree = QWidget()
        tab_tree_layout = QVBoxLayout(tab_tree)
        # 顶部工具栏：文件选择 + 导入/导出/刷新
        toolbar = QHBoxLayout()
        tab_tree_layout.addLayout(toolbar)
        self.file_selector = QComboBox()
        toolbar.addWidget(QLabel("项目树文件:"))
        toolbar.addWidget(self.file_selector, stretch=1)
        self.btn_import = QPushButton("导入")
        self.btn_export = QPushButton("导出")
        self.btn_refresh = QPushButton("刷新")
        toolbar.addWidget(self.btn_import)
        toolbar.addWidget(self.btn_export)
        toolbar.addWidget(self.btn_refresh)
        # 自定义树，支持拖放模式切换
        self.tree = _DragAwareTree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        # Delete 快捷键：删除当前选中节点（仅前端层）
        try:
            QShortcut(Qt.Key.Key_Delete, self.tree, activated=lambda: self._action_delete(self.tree.currentItem()))
        except Exception:
            pass
        # 安装占位提示委托：第0列编辑时显示“新节点”
        try:
            self.tree.setItemDelegateForColumn(0, _TitleEditDelegate("新节点", self.tree))
        except Exception:
            pass
        # 右键菜单
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        # 内容在 _populate_tree 中填充
        tab_tree_layout.addWidget(self.tree)
        self.left_tabs.addTab(tab_tree, "节点树")

        # Tab3：泳道（Kanban/过滤汇总）
        tab_swimlane = QWidget()
        tab_swimlane_layout = QVBoxLayout(tab_swimlane)
        # 顶部工具条：刷新
        swimlane_toolbar = QHBoxLayout()
        self.btn_swimlane_refresh = QPushButton("刷新泳道")
        self.btn_swimlane_clear = QPushButton("清理测试数据")
        swimlane_toolbar.addWidget(self.btn_swimlane_refresh)
        swimlane_toolbar.addWidget(self.btn_swimlane_clear)
        swimlane_toolbar.addStretch(1)
        tab_swimlane_layout.addLayout(swimlane_toolbar)
        # 三列：未开始/进行中/已完成
        swimlane_cols = QHBoxLayout()
        self._swimlane_lists = {}
        def _add_col(title: str, key: str):
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            lw = _SwimlaneList(self, key)
            try:
                lw.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
                lw.setDragEnabled(True)
                lw.setAcceptDrops(True)
                lw.setDropIndicatorShown(True)
                lw.setDefaultDropAction(Qt.DropAction.MoveAction)
                # 允许跨列拖拽
                lw.setDragDropMode(QListWidget.DragDropMode.DragDrop)
                # 点击泳道卡片 -> 联动右侧详情
                try:
                    lw.itemClicked.connect(self._on_swimlane_item_clicked)
                except Exception:
                    pass
            except Exception:
                pass
            col.addWidget(lw)
            swimlane_cols.addLayout(col)
            self._swimlane_lists[key] = lw
        _add_col("计划中", "planned")
        _add_col("已分配", "assigned")
        _add_col("进行中", "doing")
        _add_col("已完成", "done")
        _add_col("已暂停", "paused")
        tab_swimlane_layout.addLayout(swimlane_cols)
        self.left_tabs.addTab(tab_swimlane, "泳道")
        try:
            self.btn_swimlane_refresh.clicked.connect(self._swimlane_load)
        except Exception:
            pass
        try:
            self.btn_swimlane_clear.clicked.connect(self._swimlane_clear)
        except Exception:
            pass
        # 初次加载一次
        try:
            self._swimlane_load()
        except Exception:
            pass

        # Tab4：图谱（关系可视化）
        tab_graph = QWidget()
        tab_graph_layout = QVBoxLayout(tab_graph)
        tab_graph_layout.addWidget(QLabel("图谱（占位）：关系图/投射视图"))
        self.left_tabs.addTab(tab_graph, "图谱")

        # 左上角：设置“默认二级标签”开关（采用头部行，确保可见）
        try:
            self.chk_default_left = QCheckBox("默认")
            self.chk_default_left.setToolTip("将当前二级选项卡设为下次启动默认打开")
            self.chk_default_left.stateChanged.connect(self._on_left_default_toggled)
            # 显式头部栏：在 tabs 上方插入一行，将复选框放入右侧
            header_row = QHBoxLayout()
            header_row.addStretch(1)
            header_row.addWidget(self.chk_default_left)
            left_layout.insertLayout(0, header_row)
            # 切换二级Tab时：若已勾选默认，则持久化当前索引；并同步勾选状态
            self.left_tabs.currentChanged.connect(self._on_left_tab_changed)
        except Exception:
            pass

        # 右侧：详情
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        # 标题编辑
        self.detail_title = QLineEdit()
        self.detail_title.setPlaceholderText("标题（映射节点 topic，前端临时态）")
        # 右侧内部使用垂直分割器，实现“标题/内容”可调整并持久化
        self.detail_splitter = QSplitter(Qt.Orientation.Vertical)
        # 上部：标题
        title_holder = QWidget()
        title_layout = QVBoxLayout(title_holder)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(self.detail_title)
        # 在标题下方添加“节点ID”展示标签（灰色、小号、等宽字体），默认隐藏
        self.detail_node_id_label = QLabel("")
        try:
            self.detail_node_id_label.setStyleSheet("color: #666; font-size: 11px; font-family: Consolas, 'Courier New', monospace;")
        except Exception:
            pass
        try:
            self.detail_node_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        except Exception:
            pass
        self.detail_node_id_label.hide()
        title_layout.addWidget(self.detail_node_id_label)
        self.detail_splitter.addWidget(title_holder)
        # 下部：内容 Markdown 编辑器（可编辑，保存写回JSON）
        self.detail = QTextEdit()
        self.detail.setReadOnly(False)
        self.detail.setPlaceholderText("Markdown 编辑器：编辑并点击保存写回节点 content。为空则保存为 \"\"。")
        self.detail_splitter.addWidget(self.detail)
        right_layout.addWidget(self.detail_splitter)
        # 详情操作条（仅前端占位，不写回）
        toolbar_detail = QHBoxLayout()
        self.btn_detail_copy = QPushButton("复制内容")
        self.btn_detail_paste = QPushButton("粘贴内容")
        self.btn_detail_clear = QPushButton("清空")
        self.btn_detail_save = QPushButton("保存")
        toolbar_detail.addWidget(self.btn_detail_copy)
        toolbar_detail.addWidget(self.btn_detail_paste)
        toolbar_detail.addWidget(self.btn_detail_clear)
        toolbar_detail.addWidget(self.btn_detail_save)
        toolbar_detail.addStretch(1)
        right_layout.addLayout(toolbar_detail)

        # 组装到分割器
        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)

        # 交互占位：点击/选择树节点 -> 右侧详情展示
        try:
            self.tree.itemClicked.connect(self._on_tree_item_clicked)
            # 调试：记录选择变化（与 itemClicked 互补，用于确认是否有隐式触发）
            try:
                self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
            except Exception:
                pass
            # 持久化节点展开/折叠状态
            try:
                self.tree.itemExpanded.connect(self._on_tree_item_expanded)
                self.tree.itemCollapsed.connect(self._on_tree_item_collapsed)
            except Exception:
                pass
            self.file_selector.currentIndexChanged.connect(self._on_project_file_changed)
            self.btn_refresh.clicked.connect(self._on_refresh_clicked)
            self.btn_import.clicked.connect(self._on_import_clicked)
            self.btn_export.clicked.connect(self._on_export_clicked)
            # 详情交互
            self.btn_detail_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.detail.toPlainText()))
            # MD 阅读器为只读：禁用粘贴/清空
            self.btn_detail_paste.setEnabled(True)
            self.btn_detail_clear.setEnabled(True)
            self.btn_detail_paste.clicked.connect(lambda: self.detail.paste())
            self.btn_detail_clear.clicked.connect(lambda: self.detail.clear())
            # 隐藏“保存”按钮（改为自动保存与保存全部）
            try:
                self.btn_detail_save.hide()
            except Exception:
                pass
            # 自动保存：标题结束编辑即保存；内容变更节流保存
            self.detail_title.editingFinished.connect(self._autosave_schedule)
            self.detail.textChanged.connect(self._autosave_schedule)
            # 树内联重命名自动保存
            self.tree.itemChanged.connect(self._on_tree_item_changed)
            # 监听模型插入：用于拖拽“复制”后的去重改ID（拖拽移动不触发插入，不会改ID）
            try:
                self.tree.model().rowsInserted.connect(self._on_rows_inserted)
            except Exception:
                pass
        except Exception:
            pass
        # 恢复默认二级Tab
        try:
            self._restore_default_left_tab()
        except Exception:
            pass

    # ---------- 右键菜单与基础操作 ----------
    def _on_tree_context_menu(self, pos: QPoint):
        """节点树右键菜单：即使发生部分异常也尽量显示最小菜单。"""
        item = None
        global_pos = None
        try:
            item = self.tree.itemAt(pos)
        except Exception:
            item = None
        try:
            global_pos = self.tree.viewport().mapToGlobal(pos)
        except Exception:
            try:
                global_pos = self.mapToGlobal(pos)
            except Exception:
                global_pos = None

        # 记录一次日志，便于诊断是否有事件触发
        try:
            label = item.text(0) if item else '<blank>'
            logger_sink.log_user_message(self._session_id, f"context_menu@tree: target={label}")
        except Exception:
            pass

        menu = QMenu(self)
        try:
            # 主动作
            act_new_child = QAction("新建子节点", self)
            act_new_sibling = QAction("新建同级节点", self)
            act_copy = QAction("复制节点到剪贴板", self)
            act_cut = QAction("剪切节点", self)
            act_paste = QAction("从剪贴板粘贴为子节点", self)
            act_delete = QAction("删除节点(前端层)", self)
            act_rename = QAction("重命名", self)
            act_toggle_drag = QAction("切换为移动模式" if not self._drag_move_mode else "切换为复制模式", self)

            # 绑定
            try:
                act_new_child.triggered.connect(lambda: self._action_new_child(item))
                act_new_sibling.triggered.connect(lambda: self._action_new_sibling(item))
                act_copy.triggered.connect(lambda: self._action_copy(item))
                act_cut.triggered.connect(lambda: self._action_cut(item))
                act_paste.triggered.connect(lambda: self._action_paste(item))
                act_delete.triggered.connect(lambda: self._action_delete(item))
                act_rename.triggered.connect(lambda: self._action_rename(item))
                act_toggle_drag.triggered.connect(self._toggle_drag_mode)
            except Exception:
                pass

            # 组装
            if item is not None:
                menu.addAction(act_new_child)
                menu.addAction(act_new_sibling)
                menu.addSeparator()
                menu.addAction(act_copy)
                menu.addAction(act_cut)
                menu.addAction(act_paste)
                menu.addSeparator()
                menu.addAction(act_rename)
                menu.addAction(act_delete)
                menu.addSeparator()
                # 加入泳道（子菜单）
                try:
                    # 诊断：类型识别 + 回退推断（结构化回退：顶层=文件项，顶层子=根层节点）
                    data = item.data(0, Qt.ItemDataRole.UserRole) or {}
                    typ = data.get('type')
                    is_file = typ == 'file'
                    is_node = typ == 'node'
                    parent_type = None
                    parent_is_file = False
                    p = None
                    try:
                        p = item.parent()
                        if p is not None:
                            pd = p.data(0, Qt.ItemDataRole.UserRole) or {}
                            parent_type = pd.get('type')
                            parent_is_file = parent_type == 'file'
                    except Exception:
                        parent_is_file = False

                    # 结构化回退（当 typ 缺失时）：
                    # - 顶层项（无父）：按文件项处理
                    # - 顶层子项（父为顶层）：按根层节点处理
                    try:
                        is_top_level = (item.parent() is None)
                        is_top_level_child = (item.parent() is not None and item.parent().parent() is None)
                    except Exception:
                        is_top_level = False
                        is_top_level_child = False

                    eff_is_file = is_file or (typ is None and is_top_level)
                    eff_is_node_root = is_node or (typ is None and is_top_level_child)
                    eff_parent_is_file = parent_is_file or (typ is None and is_top_level_child)

                    try:
                        logger_sink.log_user_message(self._session_id, f"context_menu@swimlane_effective: typ={typ} eff_is_file={eff_is_file} eff_is_node_root={eff_is_node_root} eff_parent_is_file={eff_parent_is_file}")
                    except Exception:
                        pass

                    # 子菜单标题包含诊断信息
                    diag = f"type={typ or '∅'}|p={parent_type or ('∅' if p is None else parent_type)}"
                    add_menu = QMenu(f"加入泳道 · 计划中 · [{diag}]", self)
                    act_add_single = QAction("仅此节点 -> 计划中", self)
                    act_add_children = QAction("其一级子节点 -> 计划中", self)
                    # 无条件启用（用户要求）：点击后由实现决定可加入的目标集合
                    enable_single = True
                    enable_children = True

                    act_add_single.setEnabled(enable_single)
                    act_add_children.setEnabled(enable_children)
                    act_add_single.triggered.connect(lambda checked=False, it=item: self._action_add_to_swimlane(it, include_children=False))
                    act_add_children.triggered.connect(lambda checked=False, it=item: self._action_add_to_swimlane(it, include_children=True))

                    add_menu.addAction(act_add_single)
                    add_menu.addAction(act_add_children)
                    menu.addMenu(add_menu)
                except Exception:
                    pass
            # 拖拽模式切换：无论是否命中项都可用
            menu.addAction(act_toggle_drag)
        except Exception:
            # 回退最小菜单
            try:
                act_toggle = QAction("切换拖拽模式", self)
                act_toggle.triggered.connect(self._toggle_drag_mode)
                menu.addAction(act_toggle)
            except Exception:
                pass

        if global_pos is not None:
            try:
                menu.exec(global_pos)
            except Exception:
                try:
                    menu.exec(self.cursor().pos())
                except Exception:
                    pass
        else:
            try:
                menu.exec(self.cursor().pos())
            except Exception:
                pass
    

    
    def _action_new_child(self, item: QTreeWidgetItem | None):
        """在所选节点下创建一个子节点：标题/内容置空，避免继承当前焦点内容。"""
        try:
            if item is None:
                return
            # 解析所属文件路径
            def _resolve_file_path(it: QTreeWidgetItem | None) -> Path:
                cur = it
                while cur is not None:
                    d = cur.data(0, Qt.ItemDataRole.UserRole) or {}
                    if d.get('type') == 'file' and d.get('path'):
                        try:
                            return Path(d.get('path'))
                        except Exception:
                            break
                    cur = cur.parent()
                return Path(self._current_project_file) if self._current_project_file else Path('.')

            file_path = _resolve_file_path(item)
            new_id = self._generate_unique_id(file_path)
            node = {"id": new_id, "topic": "", "content": "", "children": []}
            new_item = self._add_json_node(item, node, file_path)
            try:
                item.setExpanded(True)
            except Exception:
                pass
            self.undo_stack.push(QUndoCommand("新建子节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"new_child: parent={item.text(0)} id={new_id}")
            except Exception:
                pass
            # 关键：切换到新节点并清空右侧详情，防止继承
            try:
                self.tree.setCurrentItem(new_item)
                self._current_node_id = new_id
                try:
                    self.detail_title.clear()
                    self.detail.clear()
                except Exception:
                    pass
                self.tree.editItem(new_item, 0)
            except Exception:
                pass
            # 立即全量保存一次（不冲刷旧详情，避免把旧内容写到新节点）
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _action_new_sibling(self, item: QTreeWidgetItem | None):
        """在同一父节点下创建一个同级节点：标题/内容置空，避免继承。"""
        try:
            if item is None:
                return
            parent = item.parent()
            if parent is None:
                return
            def _resolve_file_path(it: QTreeWidgetItem | None) -> Path:
                cur = it
                while cur is not None:
                    d = cur.data(0, Qt.ItemDataRole.UserRole) or {}
                    if d.get('type') == 'file' and d.get('path'):
                        try:
                            return Path(d.get('path'))
                        except Exception:
                            break
                    cur = cur.parent()
                return Path(self._current_project_file) if self._current_project_file else Path('.')

            file_path = _resolve_file_path(parent)
            new_id = self._generate_unique_id(file_path)
            node = {"id": new_id, "topic": "", "content": "", "children": []}
            new_item = self._add_json_node(parent, node, file_path)
            try:
                parent.setExpanded(True)
            except Exception:
                pass
            self.undo_stack.push(QUndoCommand("新建同级节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"new_sibling: sibling_of={item.text(0)} id={new_id}")
            except Exception:
                pass
            try:
                self.tree.setCurrentItem(new_item)
                self._current_node_id = new_id
                try:
                    self.detail_title.clear()
                    self.detail.clear()
                except Exception:
                    pass
                self.tree.editItem(new_item, 0)
            except Exception:
                pass
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _action_delete(self, item: QTreeWidgetItem | None):
        """删除选中节点（前端层）：确认后从树中移除，并保存。"""
        try:
            if item is None:
                return
            parent = item.parent()
            if parent is None:
                return  # 不删除顶层文件项
            confirm = QMessageBox.question(
                self,
                "确认删除",
                f"确定要删除节点 “{item.text(0)}” 吗？此操作仅影响前端显示。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            idx = parent.indexOfChild(item)
            if idx >= 0:
                parent.takeChild(idx)
            self.undo_stack.push(QUndoCommand("删除节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"delete_node: {item.text(0)}")
            except Exception:
                pass
            try:
                self._autosave_flush()
            except Exception:
                pass
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _action_copy(self, item: QTreeWidgetItem | None):
        """复制所选节点为 JSON 到剪贴板（不含顶层文件项）。"""
        try:
            if item is None:
                return
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get('type') != 'node':
                return
            node = self._collect_node_from_item(item)
            if node is None:
                return
            try:
                text = json.dumps(node, ensure_ascii=False, indent=2)
            except Exception:
                return
            cb = QApplication.clipboard()
            cb.setText(text)
            self.undo_stack.push(QUndoCommand("复制节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"copy_node: id={node.get('id')}")
            except Exception:
                pass
        except Exception:
            pass

    def _action_cut(self, item: QTreeWidgetItem | None):
        """剪切：复制到剪贴板后，从树中移除（不提示）。"""
        try:
            if item is None:
                return
            parent = item.parent()
            if parent is None:
                return  # 顶层文件项不允许
            self._action_copy(item)
            idx = parent.indexOfChild(item)
            if idx >= 0:
                parent.takeChild(idx)
            self.undo_stack.push(QUndoCommand("剪切节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"cut_node: label={item.text(0)}")
            except Exception:
                pass
            try:
                self._autosave_flush()
            except Exception:
                pass
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _action_paste(self, item: QTreeWidgetItem | None):
        """从剪贴板粘贴为“子节点”。为避免ID冲突，将递归重生唯一ID。"""
        try:
            if item is None:
                return
            # 解析剪贴板 JSON
            text = (QApplication.clipboard().text() or '').strip()
            if not text:
                QMessageBox.information(self, "粘贴", "剪贴板为空或不包含有效JSON。")
                return
            try:
                obj = json.loads(text)
            except Exception:
                QMessageBox.information(self, "粘贴", "剪贴板内容不是有效的JSON节点。")
                return
            # 仅接受 dict 节点
            if isinstance(obj, list):
                obj = obj[0] if obj else None
            if not isinstance(obj, dict):
                QMessageBox.information(self, "粘贴", "剪贴板JSON格式不支持（需要单个节点对象）。")
                return

            # 定位目标父项与所属文件路径
            target_parent = item
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get('type') == 'node':
                pass  # 作为此节点的子节点
            else:
                # 若右键在文件项或空白，尝试放到文件根（需要文件项）
                if data.get('type') == 'file':
                    target_parent = item
                else:
                    return

            def _resolve_file_path(it: QTreeWidgetItem | None) -> Path:
                cur = it
                while cur is not None:
                    d = cur.data(0, Qt.ItemDataRole.UserRole) or {}
                    if d.get('type') == 'file' and d.get('path'):
                        try:
                            return Path(d.get('path'))
                        except Exception:
                            break
                    cur = cur.parent()
                return Path(self._current_project_file) if self._current_project_file else Path('.')

            file_path = _resolve_file_path(target_parent)

            # 准备已使用ID集合
            used_ids = self._gather_used_ids(file_path)

            # 递归重生唯一ID
            def regen_ids(n: dict):
                try:
                    n_id = n.get('id')
                    if not isinstance(n_id, str) or not n_id or n_id in used_ids:
                        new_id = self._generate_unique_id(file_path)
                        n['id'] = new_id
                    used_ids.add(n['id'])
                    ch = n.get('children')
                    if isinstance(ch, list):
                        for c in ch:
                            if isinstance(c, dict):
                                regen_ids(c)
                except Exception:
                    pass

            node_obj = json.loads(json.dumps(obj, ensure_ascii=False))  # 深拷贝
            regen_ids(node_obj)

            # 添加到树并进入编辑
            new_item = self._add_json_node(target_parent, node_obj, file_path)
            try:
                target_parent.setExpanded(True)
            except Exception:
                pass
            self.undo_stack.push(QUndoCommand("粘贴节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"paste_node: id={node_obj.get('id')}")
            except Exception:
                pass
            try:
                self.tree.setCurrentItem(new_item)
                self.tree.editItem(new_item, 0)
            except Exception:
                pass
            try:
                self._autosave_flush()
            except Exception:
                pass
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _action_rename(self, item: QTreeWidgetItem | None):
        try:
            if item is None:
                return
            old = item.text(0)
            new_text, ok = QInputDialog.getText(self, "重命名", "新的名称：", text=old)
            if not ok:
                return
            raw = (new_text or "").strip()
            # 剥离已存在的短ID片段，统一以纯标题保存
            new_text = self._strip_short_ids_from_title(raw)
            if not new_text or new_text == old:
                return
            # 更新显示名（格式化：标题 + 短ID）
            try:
                self._suppress_item_changed = True
                data = item.data(0, Qt.ItemDataRole.UserRole) or {}
                node = data.get("node") or {}
                if isinstance(node, dict):
                    safe_node = dict(node)
                    safe_node["topic"] = new_text
                    item.setText(0, self._format_node_label(safe_node))
                else:
                    item.setText(0, new_text)
            finally:
                try:
                    self._suppress_item_changed = False
                except Exception:
                    pass
            # 尝试更新临时节点数据中的 topic（仅前端态，不写回文件）
            try:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and isinstance(data.get("node"), dict):
                    # 避免原地修改引用，使用深拷贝后回写
                    node_copy = _copy.deepcopy(data["node"]) if isinstance(data.get("node"), dict) else {}
                    node_copy["topic"] = new_text
                    data["node"] = node_copy
                    item.setData(0, Qt.ItemDataRole.UserRole, data)
            except Exception:
                pass
            self.undo_stack.push(QUndoCommand("重命名节点(前端层)"))
            try:
                logger_sink.log_user_message(self._session_id, f"rename_node: {old} -> {new_text}")
            except Exception:
                pass
            # 即时持久化
            try:
                self._autosave_flush()
            except Exception:
                pass
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _base_root(self) -> Path:
        """项目根目录（包含 config/、app/ 等）。"""
        p = Path(__file__).resolve()
        # 结构: .../app/ui/pages/project_page/project_page.py -> parents[4] == 项目根
        return p.parents[4]

    def _select_item_and_focus_title(self, item: QTreeWidgetItem | None):
        """选中树节点，并将焦点切到详情标题，且全选标题文本。"""
        try:
            if item is None:
                return
            self.tree.setCurrentItem(item)
            try:
                self._on_tree_item_clicked(item)
            except Exception:
                pass
            try:
                self.detail_title.setFocus()
                self.detail_title.selectAll()
            except Exception:
                pass
        except Exception:
            pass

    # ---------- 分割器持久化 ----------
    def _settings(self) -> QSettings:
        # 组织名/应用名请与项目一致，避免跨模块冲突
        return QSettings("NeuralAgent", "DesktopApp")

    def _restore_splitters(self):
        try:
            s = self._settings()
            main_state = s.value("project_page/main_splitter")
            if main_state is not None:
                try:
                    self.main_splitter.restoreState(main_state)
                except Exception:
                    pass
            detail_state = s.value("project_page/detail_splitter")
            if detail_state is not None:
                try:
                    self.detail_splitter.restoreState(detail_state)
                except Exception:
                    pass
        except Exception:
            pass

    def _save_splitters(self):
        try:
            s = self._settings()
            s.setValue("project_page/main_splitter", self.main_splitter.saveState())
            s.setValue("project_page/detail_splitter", self.detail_splitter.saveState())
        except Exception:
            pass

    # ---------- 二级Tab默认开关/持久化 ----------
    def _restore_default_left_tab(self):
        try:
            s = self._settings()
            idx = s.value("project_page/default_left_tab_index")
            if isinstance(idx, str) and idx.isdigit():
                idx = int(idx)
            # 1) 首选默认索引
            if isinstance(idx, int) and 0 <= idx < self.left_tabs.count():
                self.left_tabs.setCurrentIndex(int(idx))
            else:
                # 2) 回退最近一次索引
                last = s.value("project_page/last_left_tab_index")
                if isinstance(last, str) and last.isdigit():
                    last = int(last)
                if isinstance(last, int) and 0 <= last < self.left_tabs.count():
                    self.left_tabs.setCurrentIndex(int(last))
                else:
                    # 3) 最后回退第一个
                    if self.left_tabs.count() > 0:
                        self.left_tabs.setCurrentIndex(0)
            # 恢复后同步勾选状态
            self._sync_left_default_checkbox()
        except Exception:
            pass

    def _on_left_default_toggled(self, state: int):
        try:
            s = self._settings()
            if state == Qt.CheckState.Checked:
                s.setValue("project_page/default_left_tab_index", self.left_tabs.currentIndex())
                try:
                    s.sync()
                except Exception:
                    pass
            else:
                try:
                    s.remove("project_page/default_left_tab_index")
                except Exception:
                    s.setValue("project_page/default_left_tab_index", -1)
                try:
                    s.sync()
                except Exception:
                    pass
        except Exception:
            pass

    def _sync_left_default_checkbox(self):
        try:
            s = self._settings()
            idx = s.value("project_page/default_left_tab_index")
            if isinstance(idx, str) and idx.isdigit():
                idx = int(idx)
            cur = self.left_tabs.currentIndex()
            if hasattr(self, 'chk_default_left'):
                try:
                    self.chk_default_left.blockSignals(True)
                    self.chk_default_left.setChecked(isinstance(idx, int) and idx == cur)
                finally:
                    try:
                        self.chk_default_left.blockSignals(False)
                    except Exception:
                        pass
        except Exception:
            try:
                # 容错：控件不存在时忽略
                if hasattr(self, 'chk_default_left'):
                    try:
                        self.chk_default_left.blockSignals(True)
                        self.chk_default_left.setChecked(False)
                    finally:
                        try:
                            self.chk_default_left.blockSignals(False)
                        except Exception:
                            pass
            except Exception:
                pass

    def _on_left_tab_changed(self, index: int):
        """当二级Tab变化时：总是记录 last；如勾选默认则写 default；最后同步勾选状态。"""
        try:
            s = self._settings()
            # 记录最近一次索引
            s.setValue("project_page/last_left_tab_index", int(index))
            try:
                s.sync()
            except Exception:
                pass
            # 如勾选默认，则写默认索引
            if hasattr(self, 'chk_default_left') and self.chk_default_left.isChecked():
                s.setValue("project_page/default_left_tab_index", int(index))
                try:
                    s.sync()
                except Exception:
                    pass
            self._sync_left_default_checkbox()
        except Exception:
            pass

    def _populate_tree(self):
        """从 config/projects 选择一个 JSON 节点树文件作为根，递归构建树。"""
        try:
            self.tree.clear()
            base = self._base_root()
            projects_dir = base / 'config' / 'projects'

            if not projects_dir.exists():
                projects_dir.mkdir(parents=True, exist_ok=True)

            # 列举候选并刷新下拉框
            candidates = self._list_project_candidates(projects_dir)
            self._refresh_file_selector(candidates)

            if not candidates:
                # 无项目树文件时，创建一个默认根文件并载入
                try:
                    default_file = self._ensure_default_project_file(projects_dir)
                    candidates = [default_file]
                    self._current_project_file = default_file
                    self._refresh_file_selector(candidates)
                except Exception:
                    # 回退到占位显示
                    placeholder = QTreeWidgetItem(["<无项目树文件>"])
                    self.tree.addTopLevelItem(placeholder)
                    return

            # 选择当前文件
            file_path = self._resolve_current_project_file(candidates)
            with open(file_path, 'r', encoding='utf-8') as f:
                root_node = json.load(f)

            # 根节点以文件名展示
            root_item = QTreeWidgetItem([file_path.name])
            root_item.setExpanded(True)
            # 关键修复：顶层项类型使用 'file'，以匹配 _save_all_to_file 的查找逻辑
            root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "file", "path": str(file_path), "node": root_node})
            self.tree.addTopLevelItem(root_item)

            # 递归添加 JSON 节点树（根节点的 children 作为显示起点，根本身用文件名展示）
            if isinstance(root_node, dict) and isinstance(root_node.get('children'), list):
                for child in root_node['children']:
                    self._add_json_node(root_item, child, file_path)
            else:
                # 若结构异常，直接以整个根节点显示
                self._add_json_node(root_item, root_node, file_path)
        except Exception:
            # 静默失败以免影响UI
            pass

    def _list_project_candidates(self, projects_dir: Path) -> list[Path]:
        """返回候选项目树文件，优先 *.subtree.json，再回退 *.json。"""
        try:
            subtrees = sorted(projects_dir.glob('*.subtree.json'))
            if subtrees:
                return subtrees
            return sorted(projects_dir.glob('*.json'))
        except Exception:
            return []

    def _refresh_file_selector(self, candidates: list[Path]):
        """刷新文件下拉框，不触发递归加载。"""
        try:
            self.file_selector.blockSignals(True)
            self.file_selector.clear()
            for p in candidates:
                self.file_selector.addItem(p.name, str(p))
            # 设置选中项为当前文件
            if self._current_project_file is not None:
                idx = self.file_selector.findData(str(self._current_project_file))
                if idx >= 0:
                    self.file_selector.setCurrentIndex(idx)
            self.file_selector.blockSignals(False)
        except Exception:
            try:
                self.file_selector.blockSignals(False)
            except Exception:
                pass

    def _resolve_current_project_file(self, candidates: list[Path]) -> Path:
        """确定当前项目文件；若未设置或不存在则取第一个。"""
        if not candidates:
            raise FileNotFoundError("无候选项目文件")
        if self._current_project_file and self._current_project_file in candidates:
            return self._current_project_file

        self._current_project_file = candidates[0]
        # 同步到下拉框
        try:
            idx = self.file_selector.findData(str(self._current_project_file))
            if idx >= 0:
                self.file_selector.setCurrentIndex(idx)
        except Exception:
            pass
        return self._current_project_file

    def _ensure_default_project_file(self, projects_dir: Path) -> Path:
        """确保存在一个默认的项目树 JSON 文件，并返回其路径。"""
        file_path = projects_dir / 'default.subtree.json'
        if not file_path.exists():
            try:
                default_root = {
                    "id": "root",
                    "topic": "默认项目",
                    "children": []
                }
                content = json.dumps(default_root, ensure_ascii=False, indent=2)
                file_path.write_text(content, encoding='utf-8')
            except Exception:
                # 如果写入失败则抛出，让上层处理占位
                raise
        return file_path

    def _on_project_file_changed(self, index: int):
        """下拉框切换项目文件。"""
        try:
            # 切换前先冲刷未保存内容
            self._autosave_flush()
            self._save_all_to_file()
            data = self.file_selector.itemData(index)
            if data:
                p = Path(data)
                if p.exists():
                    self._current_project_file = p
                    self._populate_tree()
        except Exception:
            pass

    def _on_refresh_clicked(self):
        try:
            # 刷新前先冲刷未保存内容
            self._autosave_flush()
            self._save_all_to_file()
            self._populate_tree()
        except Exception:
            pass

    def _on_import_clicked(self):
        """从任意位置导入一个项目树 JSON 到 config/projects/ 并选用。"""
        try:
            base = self._base_root()
            projects_dir = base / 'config' / 'projects'
            src_path, _ = QFileDialog.getOpenFileName(self, "选择项目树JSON", str(base), "JSON 文件 (*.json)")
            if not src_path:
                return
            src = Path(src_path)
            if not src.exists():
                return
            # 复制为 projects 目录下同名文件（若冲突则在文件名后追加数字）
            dst = projects_dir / src.name
            i = 1
            while dst.exists():
                stem = src.stem
                suffix = src.suffix
                dst = projects_dir / f"{stem}_{i}{suffix}"
                i += 1
            content = src.read_text(encoding='utf-8')
            dst.write_text(content, encoding='utf-8')
            # 设为当前并刷新
            self._current_project_file = dst
            self._populate_tree()
        except Exception:
            pass

    def _on_export_clicked(self):
        """将当前项目树 JSON 导出到用户选择的位置。"""
        try:
            if not self._current_project_file or not Path(self._current_project_file).exists():
                return
            # 以“根节点的名字”作为默认文件名，回退为当前文件名
            src_path = Path(self._current_project_file)
            root = self._read_json(src_path)
            def _sanitize_filename(name: str) -> str:
                try:
                    # 去除 Windows 非法字符 <>:"/\|?* 与首尾空白
                    import re as _re
                    n = (name or "").strip()
                    n = _re.sub(r"[\\\\/:*?\"<>|]", "_", n)
                    return n or src_path.stem
                except Exception:
                    return src_path.stem
            if isinstance(root, dict):
                root_name = root.get('topic') or root.get('name') or src_path.stem
            else:
                root_name = src_path.stem
            default_name = f"{_sanitize_filename(str(root_name))}.json"
            dst_path, _ = QFileDialog.getSaveFileName(self, "导出项目树JSON", str(src_path.with_name(default_name)), "JSON 文件 (*.json)")
            if not dst_path:
                return
            # 导出应以“当前树的最新状态”为准：重建 root 并写入目标路径
            try:
                # 先冲刷详情自动保存
                self._autosave_flush()
            except Exception:
                pass
            # 重新读取根（或复用上方 root 亦可）
            root = self._read_json(src_path)
            if not isinstance(root, dict):
                return
            # 在顶层查找当前文件项
            file_item = None
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                data = it.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get('type') == 'file' and Path(data.get('path','')) == src_path:
                    file_item = it
                    break
            if file_item is None:
                return
            # 重建 children
            new_children = []
            for i in range(file_item.childCount()):
                ch = file_item.child(i)
                node = self._collect_node_from_item(ch)
                if node is not None:
                    new_children.append(node)
            root['children'] = new_children
            # 原子写入到导出路径
            self._write_json_atomic(Path(dst_path), root)
        except Exception:
            pass

    def _add_json_node(self, parent_item: QTreeWidgetItem, node: dict, file_path: Path):
        """将一个 JSON 节点递归添加到树中。节点显示文本优先 topic 其次 id。"""
        try:
            if not isinstance(node, dict):
                label = str(node)
            else:
                # 统一：标题 + 短ID，避免同名节点被同一化
                label = self._format_node_label(node)
            item = QTreeWidgetItem([label])
            # 确保树节点可内联编辑标题
            try:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            except Exception:
                pass
            # 避免共享引用导致多个节点互相影响：深拷贝 node
            try:
                import copy as _copy
                node_copy = _copy.deepcopy(node)
            except Exception:
                node_copy = dict(node)
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "node", "node": node_copy, "path": str(file_path)})
            # 允许重命名
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            # 展开状态
            try:
                if isinstance(node, dict) and node.get('expanded') is True:
                    item.setExpanded(True)
            except Exception:
                pass
            parent_item.addChild(item)

            # 递归 children
            if isinstance(node, dict) and isinstance(node.get('children'), list):
                for child in node['children']:
                    self._add_json_node(item, child, file_path)
            return item
        except Exception:
            pass

    # 删除未使用的 _add_category_node（历史遗留，现不再需要）

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int = 0):
        try:
            try:
                prev_id = getattr(self, '_current_node_id', None)
                prev_title_box = (self.detail_title.text() or '').strip()
                logger_sink.log_user_message(self._session_id, f"[CLICK] before_flush prev_id={prev_id} prev_title_box='{prev_title_box}' clicked_label='{item.text(0)}'")
            except Exception:
                pass
            # 切换节点前先冲刷未保存内容
            self._autosave_flush()
            # 关键加固：在填充新选择前，先显式清空右侧详情，避免任何残留造成“继承”错觉
            try:
                self.detail_title.clear()
                self.detail.clear()
                self.detail_node_id_label.clear()
                self.detail_node_id_label.hide()
            except Exception:
                pass
            # 读取项数据并根据类型展示
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                # 节点项
                if data.get('type') == 'node':
                    node = data.get('node')
                    if not isinstance(node, dict):
                        return
                    # 更新当前选中节点ID
                    self._current_node_id = node.get('id')
                    # 显示标题和内容（content 缺失或为 None 则视为 ""）
                    try:
                        self.detail_title.setText(node.get('topic') or '')
                        content = node.get('content')
                        if content is None:
                            content = ''
                        self.detail.setPlainText(content)
                        self.detail_node_id_label.setText(f"ID: {node.get('id') or ''}")
                        self.detail_node_id_label.show()
                    except Exception:
                        pass
                    return
                # 文件项
                if data.get('type') == 'file':
                    path = data.get('path')
                    if path and Path(path).exists():
                        try:
                            with open(path, 'r', encoding='utf-8') as f:
                                content_obj = json.load(f)
                            formatted = json.dumps(content_obj, indent=4, ensure_ascii=False)
                            self.detail_title.setText(Path(path).name)
                            self.detail.setMarkdown(f"```json\n{formatted}\n```")
                            try:
                                self.detail_node_id_label.clear()
                                self.detail_node_id_label.hide()
                            except Exception:
                                pass
                            return
                        except Exception as e:
                            self.detail_title.setText("")
                            self.detail.setMarkdown(f"[错误] 读取文件失败：{e}")
                            try:
                                self.detail_node_id_label.clear()
                                self.detail_node_id_label.hide()
                            except Exception:
                                pass
                            return
            # 兜底：展示名称
            name = item.text(0)
            self.detail_title.setText(name)
            self.detail.setMarkdown(f"[信息] {name}")
            try:
                self.detail_node_id_label.clear()
                self.detail_node_id_label.hide()
            except Exception:
                pass
        except Exception:
            pass

    def _on_tree_selection_changed(self):
        try:
            items = self.tree.selectedItems()
            cur = items[0] if items else None
            cur_data = cur.data(0, Qt.ItemDataRole.UserRole) if cur else None
            cur_id = (cur_data.get('node') or {}).get('id') if isinstance(cur_data, dict) else None
            cur_topic = (cur_data.get('node') or {}).get('topic') if isinstance(cur_data, dict) else None
            cur_label = cur.text(0) if cur else None
            logger_sink.log_user_message(self._session_id, f"[SELECTION] cur_id={cur_id} cur_topic='{cur_topic}' cur_label='{cur_label}' detail_title='{(self.detail_title.text() or '').strip()}'")
        except Exception:
            pass

    def _on_tree_item_expanded(self, item: QTreeWidgetItem):
        try:
            self._persist_item_expansion(item, True)
        except Exception:
            pass

    def _on_tree_item_collapsed(self, item: QTreeWidgetItem):
        try:
            self._persist_item_expansion(item, False)
        except Exception:
            pass

    def _persist_item_expansion(self, item: QTreeWidgetItem, expanded: bool):
        """将指定树节点的展开状态写回对应 JSON 节点的 `expanded` 字段。仅针对 type=='node' 的项。"""
        try:
            if item is None:
                return
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get('type') != 'node':
                return
            node_obj = data.get('node') or {}
            node_id = node_obj.get('id') if isinstance(node_obj, dict) else None
            if not node_id:
                return
            # 解析所属文件路径（向上寻找最近的 file 顶层项）
            def _resolve_file_path(it: QTreeWidgetItem | None) -> Path | None:
                cur = it
                while cur is not None:
                    d = cur.data(0, Qt.ItemDataRole.UserRole) or {}
                    if d.get('type') == 'file' and d.get('path'):
                        try:
                            return Path(d.get('path'))
                        except Exception:
                            break
                    cur = cur.parent()
                return Path(self._current_project_file) if self._current_project_file else None

            fp = _resolve_file_path(item)
            if fp is None or not Path(fp).exists():
                return
            root = self._read_json(Path(fp))
            if root is None:
                return
            if not self._update_node_in_json(root, node_id, {"expanded": bool(expanded)}):
                return
            if not self._write_json_atomic(Path(fp), root):
                return
            # 同步树项缓存
            try:
                if isinstance(node_obj, dict):
                    node_obj['expanded'] = bool(expanded)
                    data['node'] = node_obj
                    item.setData(0, Qt.ItemDataRole.UserRole, data)
            except Exception:
                pass
            try:
                logger_sink.log_user_message(self._session_id, f"[EXPAND_PERSIST] id={node_id} expanded={bool(expanded)}")
            except Exception:
                pass
        except Exception:
            pass

    def _on_swimlane_item_clicked(self, item: QListWidgetItem):
        """泳道列表项点击 -> 联动树选择与右侧详情。
        步骤：
        1) 读取泳道项 data(UserRole).id
        2) 用 `_find_item_by_node_id()` 定位树节点
        3) 选中并滚动可见，调用 `_on_tree_item_clicked()` 复用详情展示逻辑
        """
        try:
            if item is None:
                return
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            nid = data.get('id')
            if not nid:
                return
            tree_it = self._find_item_by_node_id(nid)
            if tree_it is None:
                try:
                    logger_sink.log_user_message(self._session_id, f"[SWIMLANE_CLICK] node_not_found id={nid}")
                except Exception:
                    pass
                return
            # 切换到对应的树节点
            try:
                self.tree.setCurrentItem(tree_it)
                self.tree.scrollToItem(tree_it)
            except Exception:
                pass
            # 复用树节点的点击处理，刷新详情
            try:
                self._on_tree_item_clicked(tree_it, 0)
            except Exception:
                pass
            try:
                logger_sink.log_user_message(self._session_id, f"[SWIMLANE_CLICK] id={nid} label='{tree_it.text(0)}'")
            except Exception:
                pass
        except Exception:
            pass

    # ---------- 节点详情保存与自动保存 ----------
    def _on_detail_save_clicked(self):
        """显式保存按钮：立即写回并提示。"""
        ok = self._save_current_detail()
        try:
            if ok:
                QMessageBox.information(self, "已保存", "节点详情已写回项目文件。")
            else:
                msg = getattr(self, '_last_save_error', None) or "未选中有效节点或项目文件不存在/未找到该节点。"
                QMessageBox.warning(self, "无法保存", msg)
        except Exception:
            pass

    def _autosave_schedule(self):
        """内容变更后延迟保存（防抖）。"""
        try:
            self._autosave_timer.start()
        except Exception:
            pass

    def _autosave_flush(self):
        """若定时器在等待中则立即保存一次（静默）。"""
        try:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            # 静默保存：不弹窗
            self._save_current_detail(silent=True)
        except Exception:
            pass

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """树节点内联重命名联动：
        - 同步到节点 JSON 数据的 topic
        - 若为当前选中项，则同步右侧标题
        - 立即持久化保存（仅更新标题 + 全量保存兜底）
        """
        try:
            # 防止程序化 setText 造成的回环
            if getattr(self, '_suppress_item_changed', False):
                return
            if column != 0 or item is None:
                return
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get('type') != 'node':
                return
            node_obj = data.get('node') or {}
            if not isinstance(node_obj, dict):
                return
            node_id = node_obj.get('id')
            if not node_id:
                return
            raw_title = (item.text(0) or '').strip()
            # 剥离已存在的短ID片段，确保保存与显示基础为纯标题
            new_title = self._strip_short_ids_from_title(raw_title)
            try:
                logger_sink.log_user_message(self._session_id, f"item_changed: id={node_id} -> '{new_title}'")
            except Exception:
                pass
            # 更新树项缓存的节点标题
            node_obj = dict(node_obj)
            node_obj['topic'] = new_title
            # 回写到树项缓存时使用深拷贝，避免多个项共享引用
            data['node'] = _copy.deepcopy(node_obj)
            item.setData(0, Qt.ItemDataRole.UserRole, data)

            # 若为当前项，同步详情标题（不触发编辑完成，仅setText）
            try:
                if self.tree.currentItem() is item:
                    self.detail_title.setText(new_title)
            except Exception:
                pass

            # 更新当前定位，确保写回使用正确文件
            d_path = data.get('path') or getattr(self, '_current_project_file', None)
            if d_path:
                self._current_project_file = Path(d_path)
            self._current_node_id = node_id

            # 使用“标题+短ID”格式回写树项文本，避免同名同一化
            try:
                self._suppress_item_changed = True
                # 使用剥离后的纯标题生成显示文本
                safe_node = dict(node_obj)
                safe_node['topic'] = new_title
                item.setText(0, self._format_node_label(safe_node))
            finally:
                try:
                    self._suppress_item_changed = False
                except Exception:
                    pass

            # 先仅更新该节点标题至 JSON；失败则放弃（不弹框），随后全量保存兜底
            try:
                ok_inline = self._save_node_title(node_id, new_title, item_hint=item)
                try:
                    logger_sink.log_user_message(self._session_id, f"save_node_title: id={node_id} ok={ok_inline}")
                except Exception:
                    pass
            except Exception as e:
                try:
                    logger_sink.log_user_message(self._session_id, f"save_node_title_error: id={node_id} err={e}")
                except Exception:
                    pass
            # 全量保存，确保children结构一致
            try:
                self._save_all_to_file()
            except Exception:
                pass
        except Exception:
            pass

    def _on_app_about_to_quit(self):
        try:
            self._autosave_flush()
            self._save_all_to_file()
            self._save_splitters()
        except Exception:
            pass

    def _save_current_detail(self, silent: bool = False) -> bool:
        """将当前详情（标题、内容）保存到当前项目文件对应节点。
        返回 True 表示已写回；False 表示无法保存或失败。
        """
        try:
            self._last_save_error = None
            node_id = getattr(self, '_current_node_id', None)
            file_path = getattr(self, '_current_project_file', None)
            if not node_id or not file_path or not Path(file_path).exists():
                self._last_save_error = "未选中有效节点，或项目文件不存在。"
                return False
            # 仅支持 *.subtree.json / *.json
            fp = Path(file_path)
            if not (str(fp.name).endswith('.subtree.json') or str(fp.name).endswith('.json')):
                self._last_save_error = f"不支持的文件类型：{fp.name}"
                return False
            title = (self.detail_title.text() or '').strip()
            content = self.detail.toPlainText()
            # 诊断埋点：若本次写入标题或内容为空，记录长度与上下文
            try:
                logger_sink.log_user_message(self._session_id, f"[AUDIT] detail_before_update: id={node_id} title_len={len(title)} content_len={(len(content) if isinstance(content, str) else 0)} file={fp.name}")
            except Exception:
                pass
            root = self._read_json(fp)
            if root is None:
                self._last_save_error = "读取项目文件失败。"
                return False
            updated = self._update_node_in_json(root, node_id, {"topic": title, "content": content})
            if not updated:
                # 若 JSON 中未找到该 id，尝试根据当前树的父节点进行“插入或更新”
                try:
                    cur_item = self.tree.currentItem()
                    if cur_item is not None:
                        data_cur = cur_item.data(0, Qt.ItemDataRole.UserRole) or {}
                        # 仅当当前项是“节点”时才尝试 upsert，避免把文件/目录/根项写入为子节点
                        if data_cur.get('type') != 'node':
                            self._last_save_error = "当前选中项不是节点，无法写回。请选中具体节点后再保存。"
                            return False
                        node_obj = data_cur.get('node') or {}
                        if isinstance(node_obj, dict):
                            # 合并标题与内容
                            node_obj['id'] = node_id
                            node_obj['topic'] = title
                            node_obj['content'] = content
                            # 禁止把根节点作为子节点写回
                            if node_obj.get('id') == 'root':
                                self._last_save_error = "根节点不支持作为子节点写回。请选中具体普通节点后再保存。"
                                return False
                            parent_item = cur_item.parent()
                            parent_id = None
                            if parent_item is not None:
                                data_parent = parent_item.data(0, Qt.ItemDataRole.UserRole) or {}
                                parent_node = data_parent.get('node')
                                if isinstance(parent_node, dict):
                                    parent_id = parent_node.get('id') or None
                            # 执行 upsert：parent_id 为 None 表示落到根节点
                            if not self._upsert_node_in_json(root, parent_id, node_obj):
                                # 最终兜底：直接附加到根节点 children
                                try:
                                    root_node = root[0] if isinstance(root, list) and root else root
                                    if isinstance(root_node, dict):
                                        if 'children' not in root_node or not isinstance(root_node['children'], list):
                                            root_node['children'] = []
                                        root_node['children'].append(node_obj)
                                        try:
                                            logger_sink.log_user_message(self._session_id, f"[AUDIT] detail_upsert_append_to_root: id={node_id} title_len={len(title)} content_len={(len(content) if isinstance(content, str) else 0)}")
                                        except Exception:
                                            pass
                                    else:
                                        self._last_save_error = "项目根结构异常，无法追加节点。"
                                        return False
                                except Exception:
                                    self._last_save_error = "无法将节点追加到根。"
                                    return False
                        else:
                            self._last_save_error = "当前树节点数据异常。"
                            return False
                    else:
                        self._last_save_error = "未选中任何树节点。"
                        return False
                except Exception:
                    self._last_save_error = "节点插入或更新过程中发生异常。"
                    return False
            if not self._write_json_atomic(fp, root):
                self._last_save_error = "写入项目文件失败。"
                return False
            # 同步树中与 node_id 对应的项（避免 currentItem 已切换导致误写）
            try:
                target_item = None
                cur_item = self.tree.currentItem()
                try:
                    data_cur = cur_item.data(0, Qt.ItemDataRole.UserRole) if cur_item else None
                    cur_id = (data_cur.get('node') or {}).get('id') if isinstance(data_cur, dict) else None
                    if cur_id == node_id:
                        target_item = cur_item
                except Exception:
                    target_item = None
                if target_item is None:
                    target_item = self._find_item_by_node_id(node_id)
                if target_item is not None:
                    # 使用“标题+短ID”格式，避免同名同一化
                    try:
                        self._suppress_item_changed = True
                        data_tmp = target_item.data(0, Qt.ItemDataRole.UserRole) or {}
                        node_tmp = data_tmp.get('node') or {}
                        if isinstance(node_tmp, dict):
                            node_tmp['topic'] = title
                            node_tmp['content'] = content
                            target_item.setText(0, self._format_node_label(node_tmp))
                        else:
                            target_item.setText(0, title or "")
                    finally:
                        try:
                            self._suppress_item_changed = False
                        except Exception:
                            pass
                    data = target_item.data(0, Qt.ItemDataRole.UserRole) or {}
                    node_obj = data.get('node') or {}
                    if isinstance(node_obj, dict):
                        # 深拷贝后更新，避免潜在共享引用
                        node_copy = _copy.deepcopy(node_obj)
                        node_copy['topic'] = title
                        node_copy['content'] = content
                        data['node'] = node_copy
                        target_item.setData(0, Qt.ItemDataRole.UserRole, data)
                        try:
                            if (title or '').strip() == '' or (content or '') == '':
                                logger_sink.log_user_message(self._session_id, f"[AUDIT] detail_tree_sync_empty_values: id={node_id} title_len={len(title)} content_len={(len(content) if isinstance(content, str) else 0)}")
                        except Exception:
                            pass
            except Exception:
                pass
            # 日志
            try:
                if not silent:
                    logger_sink.log_user_message(self._session_id, f"detail_saved: id={node_id} file={fp.name}")
            except Exception:
                pass
            return True
        except Exception:
            self._last_save_error = "保存过程中发生异常。"
            return False

    # ---------- ID 唯一化与拖拽复制处理 ----------
    def _generate_unique_id(self, file_path: Path, prefix: str = "n-") -> str:
        """基于当前文件与树中已占用的ID生成唯一ID。"""
        try:
            used = self._gather_used_ids(file_path)
            import uuid as _uuid
            while True:
                cand = f"{prefix}{_uuid.uuid4().hex[:8]}"
                if cand not in used:
                    return cand
        except Exception:
            # 回退：仍返回一次性ID，碰撞概率极低
            import uuid as _uuid
            return f"{prefix}{_uuid.uuid4().hex[:8]}"

    def _gather_used_ids(self, file_path: Path) -> set[str]:
        """收集当前树/文件中所有已使用的ID。"""
        used: set[str] = set()
        try:
            # 1) 来自树（优先，包含未写回的前端态）
            # 定位该文件顶层项
            file_item = None
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                data = it.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get('type') == 'file' and Path(data.get('path','')) == file_path:
                    file_item = it
                    break
            def walk(item: QTreeWidgetItem | None):
                if item is None:
                    return
                data = item.data(0, Qt.ItemDataRole.UserRole) or {}
                node = data.get('node') if isinstance(data, dict) else None
                if isinstance(node, dict):
                    nid = node.get('id')
                    if isinstance(nid, str) and nid:
                        used.add(nid)
                for j in range(item.childCount()):
                    walk(item.child(j))
            if file_item is not None:
                for j in range(file_item.childCount()):
                    walk(file_item.child(j))
            # 2) 来自磁盘（兜底）
            try:
                root = self._read_json(file_path)
                def walk_json(n):
                    if isinstance(n, dict):
                        nid = n.get('id')
                        if isinstance(nid, str) and nid:
                            used.add(nid)
                        ch = n.get('children')
                        if isinstance(ch, list):
                            for c in ch:
                                walk_json(c)
                    elif isinstance(n, list):
                        for c in n:
                            walk_json(c)
                walk_json(root)
            except Exception:
                pass
        except Exception:
            pass
        return used

    def _find_item_by_node_id(self, node_id: str) -> QTreeWidgetItem | None:
        """在当前树中查找指定 node_id 的项。若未找到返回 None。"""
        try:
            if not isinstance(node_id, str) or not node_id:
                return None
            # 遍历所有顶层文件项
            for i in range(self.tree.topLevelItemCount()):
                root_it = self.tree.topLevelItem(i)
                # 深度优先遍历
                stack = [root_it]
                while stack:
                    it = stack.pop()
                    if it is None:
                        continue
                    data = it.data(0, Qt.ItemDataRole.UserRole) or {}
                    node = data.get('node') if isinstance(data, dict) else None
                    if isinstance(node, dict):
                        if node.get('id') == node_id:
                            return it
                    # 入栈子节点
                    for j in range(it.childCount()-1, -1, -1):
                        stack.append(it.child(j))
        except Exception:
            pass
        return None

    def _remap_ids_unique(self, node: dict | list, file_path: Path, used_ids: set[str] | None = None) -> dict | list:
        """递归将节点/子树的ID重写为唯一ID（仅在创建新节点的场景使用）。"""
        try:
            if used_ids is None:
                used_ids = self._gather_used_ids(file_path)
            if isinstance(node, dict):
                new_node = dict(node)
                old_id = new_node.get('id')
                # 为根节点也生成新ID（新建/复制的子树）
                new_id = self._generate_unique_id(file_path)
                new_node['id'] = new_id
                used_ids.add(new_id)
                ch = new_node.get('children')
                if isinstance(ch, list):
                    new_children = []
                    for sub in ch:
                        new_children.append(self._remap_ids_unique(sub, file_path, used_ids))
                    new_node['children'] = new_children
                return new_node
            elif isinstance(node, list):
                return [self._remap_ids_unique(n, file_path, used_ids) for n in node]
            else:
                # 基本类型：包裹为新节点
                return {
                    'id': self._generate_unique_id(file_path),
                    'topic': str(node),
                    'children': []
                }
        except Exception:
            # 失败则原样返回，后续由保存兜底
            return node

    def _on_rows_inserted(self, parent_index, first: int, last: int):
        """拖拽复制后会触发 rowsInserted：对新增项执行去重改ID。拖拽移动不触发插入。"""
        try:
            # 定位所属文件路径（向上找到最近的 file 顶层项或使用当前文件）
            def get_file_path_of_item(it: QTreeWidgetItem | None):
                while it is not None:
                    data = it.data(0, Qt.ItemDataRole.UserRole) or {}
                    if data.get('type') == 'file':
                        p = data.get('path')
                        return Path(p) if p else None
                    it = it.parent()
                return Path(self._current_project_file) if self._current_project_file else None

            parent_item = self.tree.itemFromIndex(parent_index) if parent_index and parent_index.isValid() else None
            # 若 parent 无效，表示顶层插入（通常不会发生于我们的树），逐个处理
            for row in range(first, last + 1):
                if parent_item is None:
                    item = self.tree.topLevelItem(row)
                else:
                    item = parent_item.child(row)
                fp = get_file_path_of_item(item)
                if fp is None:
                    continue
                # 对插入的整个子树去重改ID
                data = item.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get('type') == 'node':
                    node_obj = data.get('node') or {}
                    unique_node = self._remap_ids_unique(node_obj, Path(fp))
                    # 更新树项缓存
                    # 使用深拷贝，避免后续同步时共享引用
                    data['node'] = _copy.deepcopy(unique_node)
                    item.setData(0, Qt.ItemDataRole.UserRole, data)
                    # 同步显示名：使用“标题+短ID”格式，避免同名同一化
                    try:
                        self._suppress_item_changed = True
                        item.setText(0, self._format_node_label(unique_node))
                    finally:
                        try:
                            self._suppress_item_changed = False
                        except Exception:
                            pass
                    # 递归对子项应用（在 _remap_ids_unique 已处理，这里仅同步到每个子 TreeItem 的缓存）
                    def sync_children(node_dict: dict, tree_item: QTreeWidgetItem):
                        ch_list = node_dict.get('children') if isinstance(node_dict, dict) else []
                        for i in range(min(len(ch_list), tree_item.childCount())):
                            sub_item = tree_item.child(i)
                            sub_data = sub_item.data(0, Qt.ItemDataRole.UserRole) or {}
                            if sub_data.get('type') == 'node':
                                sub_node = ch_list[i]
                                # 深拷贝写回，切断潜在共享
                                sub_data['node'] = _copy.deepcopy(sub_node)
                                sub_item.setData(0, Qt.ItemDataRole.UserRole, sub_data)
                                sync_children(sub_node, sub_item)
                    if isinstance(unique_node, dict):
                        sync_children(unique_node, item)
        except Exception:
            pass

    # ---------- JSON 工具 ----------
    def _save_node_title(self, node_id: str, new_title: str, item_hint: QTreeWidgetItem | None = None) -> bool:
        """仅更新指定节点的 topic（标题）。"""
        try:
            fp = getattr(self, '_current_project_file', None)
            if not fp or not Path(fp).exists():
                return False
            if not (str(fp.name).endswith('.subtree.json') or str(fp.name).endswith('.json')):
                return False
            root = self._read_json(Path(fp))
            if root is None:
                return False
            if not self._update_node_in_json(root, node_id, {"topic": new_title}):
                # upsert 到 hint 的父节点
                if item_hint is not None:
                    data_cur = item_hint.data(0, Qt.ItemDataRole.UserRole) or {}
                    if data_cur.get('type') == 'node':
                        node_obj = data_cur.get('node') or {}
                        if isinstance(node_obj, dict):
                            node_obj['id'] = node_id
                            node_obj['topic'] = new_title
                            parent_item = item_hint.parent()
                            parent_id = None
                            if parent_item is not None:
                                data_parent = parent_item.data(0, Qt.ItemDataRole.UserRole) or {}
                                parent_node = data_parent.get('node')
                                if isinstance(parent_node, dict):
                                    parent_id = parent_node.get('id') or None
                            if not self._upsert_node_in_json(root, parent_id, node_obj):
                                return False
                        else:
                            return False
                    else:
                        return False
                else:
                    return False
            if not self._write_json_atomic(Path(fp), root):
                return False
            return True
        except Exception:
            return False

    def _save_all_to_file(self):
        """从当前树结构重建完整 JSON，并全量写回当前项目文件。静默失败。"""
        try:
            fp = getattr(self, '_current_project_file', None)
            if not fp or not Path(fp).exists():
                return False
            path = Path(fp)
            if not (str(path.name).endswith('.subtree.json') or str(path.name).endswith('.json')):
                return False
            # 读取原始根，保持其除 children 外的字段
            root = self._read_json(path)
            if not isinstance(root, dict):
                return False
            # 定位该文件的顶层项
            file_item = None
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                data = it.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get('type') == 'file' and Path(data.get('path','')) == path:
                    file_item = it
                    break
            if file_item is None:
                return False
            # 从 file_item 的直接子项（节点）重建 children
            new_children = []
            for i in range(file_item.childCount()):
                ch = file_item.child(i)
                node = self._collect_node_from_item(ch)
                if node is not None:
                    new_children.append(node)
            root['children'] = new_children
            # 诊断埋点：统计空 topic 的节点数量
            try:
                def _cnt_empty_topic(n):
                    c = 0
                    if isinstance(n, dict):
                        if (n.get('topic') or '').strip() == '':
                            c += 1
                        for s in (n.get('children') or []):
                            c += _cnt_empty_topic(s)
                    elif isinstance(n, list):
                        for s in n:
                            c += _cnt_empty_topic(s)
                    return c
                empty_cnt = _cnt_empty_topic(root.get('children') or [])
                logger_sink.log_user_message(self._session_id, f"[AUDIT] save_all_children_rebuilt: total={len(new_children)} empty_topic_count={empty_cnt}")
            except Exception:
                pass
            return self._write_json_atomic(path, root)
        except Exception:
            return False

    def _collect_node_from_item(self, item: QTreeWidgetItem) -> dict | None:
        """从树项递归提取节点 dict（仅处理 type=='node' 的项）。"""
        try:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get('type') != 'node':
                return None
            node = data.get('node') or {}
            if not isinstance(node, dict):
                return None
            # 覆盖标题为当前显示文本（但写回前剥离短ID，保证JSON中为纯标题）
            node = dict(node)
            display_text = item.text(0) or node.get('topic') or ''
            node['topic'] = self._strip_short_ids_from_title(display_text)
            # 写回展开状态（用于下次启动时还原树展开）
            try:
                node['expanded'] = bool(item.isExpanded())
            except Exception:
                pass
            # 诊断埋点：若剥离后 topic 为空，记录来源与原始显示文本
            try:
                if isinstance(node, dict):
                    prev_topic = (data.get('node') or {}).get('topic') if isinstance(data.get('node'), dict) else None
                    if (node.get('topic') or '').strip() == '':
                        logger_sink.log_user_message(self._session_id, f"[AUDIT] collect_node_empty_topic: id={(node.get('id') or '<unknown>')} prev_topic_len={(len(prev_topic) if isinstance(prev_topic, str) else 'n/a')} display='{display_text}'")
            except Exception:
                pass
            # 递归 children
            children = []
            for i in range(item.childCount()):
                ch = item.child(i)
                sub = self._collect_node_from_item(ch)
                if sub is not None:
                    children.append(sub)
            node['children'] = children
            return node
        except Exception:
            return None

    def _find_node_by_id(self, node: dict | list, node_id: str) -> dict | None:
        try:
            if isinstance(node, dict):
                if node.get('id') == node_id:
                    return node
                children = node.get('children')
                if isinstance(children, list):
                    for ch in children:
                        found = self._find_node_by_id(ch, node_id)
                        if found is not None:
                            return found
            elif isinstance(node, list):
                for ch in node:
                    found = self._find_node_by_id(ch, node_id)
                    if found is not None:
                        return found
        except Exception:
            pass
        return None

    def _find_node_by_topic(self, node: dict | list, topic: str) -> dict | None:
        """按 topic 精确匹配查找首个节点。"""
        try:
            if isinstance(node, dict):
                if node.get('topic') == topic:
                    return node
                ch = node.get('children')
                if isinstance(ch, list):
                    for c in ch:
                        f = self._find_node_by_topic(c, topic)
                        if f is not None:
                            return f
            elif isinstance(node, list):
                for c in node:
                    f = self._find_node_by_topic(c, topic)
                    if f is not None:
                        return f
        except Exception:
            pass
        return None

    def _walk_nodes(self, node: dict | list, include_root: bool = False) -> list[dict]:
        """深度优先遍历，返回所有节点 dict 列表。"""
        out: list[dict] = []
        try:
            def walk(n: dict | list, is_root=False):
                if isinstance(n, dict):
                    if include_root or (not is_root):
                        out.append(n)
                    ch = n.get('children')
                    if isinstance(ch, list):
                        for c in ch:
                            walk(c, False)
                elif isinstance(n, list):
                    for c in n:
                        walk(c, False)
            walk(node, True)
        except Exception:
            pass
        return out

    def _upsert_node_in_json(self, root: dict | list, parent_id: str | None, node_obj: dict) -> bool:
        """将 node_obj 追加/更新到 parent_id 指定的父节点 children 下；
        parent_id 为 None 表示根节点 root。
        """
        try:
            # 定位父节点
            if isinstance(root, list) and root:
                # 如果根是列表，取第一个作为树根（兼容性处理）
                root_node = root[0]
            else:
                root_node = root
            if not isinstance(root_node, dict):
                return False

            parent_node = root_node if parent_id is None else self._find_node_by_id(root_node, parent_id)
            if not isinstance(parent_node, dict):
                return False

            if 'children' not in parent_node or not isinstance(parent_node['children'], list):
                parent_node['children'] = []

            # 先尝试根据 id 更新
            for ch in parent_node['children']:
                if isinstance(ch, dict) and ch.get('id') == node_obj.get('id'):
                    try:
                        # 诊断埋点：记录可能的空值覆盖
                        for k in ("topic", "content"):
                            new_v = (node_obj.get(k) or '') if isinstance(node_obj, dict) else ''
                            old_v = (ch.get(k) or '')
                            if new_v == '' and old_v != '':
                                logger_sink.log_user_message(self._session_id, f"[AUDIT] upsert_overwrite_empty: id={node_obj.get('id')} key={k} old_len={len(old_v)} -> new_len=0")
                    except Exception:
                        pass
                    ch.update(node_obj)
                    return True
            # 否则追加
            parent_node['children'].append(node_obj)
            try:
                if (node_obj.get('topic') or '').strip() == '':
                    logger_sink.log_user_message(self._session_id, f"[AUDIT] upsert_append_empty_topic: id={node_obj.get('id')} parent={parent_id}")
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _read_json(self, path: Path) -> dict | list | None:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _write_json_atomic(self, path: Path, data: dict | list) -> bool:
        """原子写入：先写入临时文件，再替换目标。"""
        try:
            dir_path = path.parent
            fd, tmp_path = tempfile.mkstemp(prefix=path.stem + '_', suffix='.tmp', dir=str(dir_path))
            os.close(fd)
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
                return True
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
        except Exception:
            return False

    def _update_node_in_json(self, node: dict | list, node_id: str, updates: dict) -> bool:
        """根据 id 递归更新节点的键值。返回是否更新成功。"""
        try:
            if isinstance(node, dict):
                if node.get('id') == node_id:
                    for k, v in updates.items():
                        try:
                            # 诊断埋点：若将非空旧值覆盖为空字符串，记录一次
                            old_v = node.get(k)
                            if isinstance(old_v, str) and old_v != '' and isinstance(v, str) and v == '':
                                logger_sink.log_user_message(self._session_id, f"[AUDIT] update_overwrite_empty: id={node_id} key={k} old_len={len(old_v)} -> new_len=0")
                        except Exception:
                            pass
                        node[k] = v
                    return True
                children = node.get('children')
                if isinstance(children, list):
                    for ch in children:
                        if self._update_node_in_json(ch, node_id, updates):
                            return True
            elif isinstance(node, list):
                for ch in node:
                    if self._update_node_in_json(ch, node_id, updates):
                        return True
        except Exception:
            pass
        return False

    # ---------- 泳道（Kanban）方法 ----------
    def _swimlane_load(self):
        """从当前项目文件加载节点到泳道。
    - 状态模式：五列（planned/assigned/doing/done/paused）。status 缺省 -> 'planned'
    - 同列内按 kanban_order 升序显示（缺省视为 999999）
    - 可选锚点：若存在 topic 为“用到的数据”的节点，仅加载其子树中的节点；否则加载全树
    """
        try:
            # 清空所有已注册列（避免硬编码）
            for k in list(self._swimlane_lists.keys()):
                lw = self._swimlane_lists.get(k)
                if lw is not None:
                    lw.clear()
            fp = getattr(self, '_current_project_file', None)
            if not fp or not Path(fp).exists():
                return
            root = self._read_json(Path(fp))
            if root is None:
                return
            # 选择锚点：优先“用到的数据”子树，否则全树
            anchor = self._find_node_by_topic(root, "用到的数据")
            scope_nodes = []
            if isinstance(anchor, dict):
                try:
                    for c in anchor.get('children') or []:
                        scope_nodes.extend(self._walk_nodes(c, include_root=True))
                except Exception:
                    pass
            else:
                scope_nodes = self._walk_nodes(root, include_root=False)

            buckets = {"planned": [], "assigned": [], "doing": [], "done": [], "paused": []}
            for n in scope_nodes:
                if not isinstance(n, dict):
                    continue
                # 仅装载显式标注了已知状态的节点；缺省状态不再视为 planned
                status = n.get('status')
                if status not in buckets:
                    continue
                # 仅接纳具有有效 id 的节点，避免把文件/分组等无 id 的项加入
                nid = n.get('id')
                if not (isinstance(nid, str) and nid):
                    continue
                order = n.get('kanban_order')
                try:
                    order = int(order)
                except Exception:
                    order = 999999
                buckets[status].append({
                    'id': nid,
                    'title': n.get('topic') or '',
                    'order': order
                })

            # 渲染已存在的列（不强制创建未知列）
            for key, arr in buckets.items():
                lw = self._swimlane_lists.get(key)
                if lw is None:
                    continue
                try:
                    arr.sort(key=lambda x: x.get('order', 999999))
                except Exception:
                    pass
                for it in arr:
                    text = it.get('title') or ''
                    item = QListWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, {
                        'id': it.get('id'),
                        'status': key
                    })
                    lw.addItem(item)
            try:
                logger_sink.log_user_message(self._session_id, "swimlane_load")
            except Exception:
                pass
        except Exception:
            pass

    def _swimlane_clear(self):
        """清理泳道UI数据（仅前端显示，不写回JSON、不更改任何节点状态）。
        - 弹窗确认；确认后清空所有已注册列的 QListWidget 项。
        - 记录撤销栈与日志，便于审计。
        """
        try:
            confirm = QMessageBox.question(
                self,
                "确认清理",
                "仅清空泳道UI中的卡片显示，不会修改任何节点状态或排序。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            # 清空所有已注册列
            try:
                for k, lw in list(self._swimlane_lists.items()):
                    if lw is not None:
                        lw.clear()
            except Exception:
                pass
            # 记录撤销与日志（仅前端层，无持久化）
            try:
                self.undo_stack.push(QUndoCommand("清理泳道UI(前端层)"))
            except Exception:
                pass
            try:
                logger_sink.log_user_message(self._session_id, "swimlane_clear_ui_only")
            except Exception:
                pass
        except Exception:
            pass

    def _swimlane_collect_state(self) -> dict:
        """采集当前已创建列中每个卡片的顺序，返回 {key: [(node_id, order), ...]}"""
        state = {}
        try:
            for key, lw in self._swimlane_lists.items():
                if lw is None:
                    continue
                col = []
                for idx in range(lw.count()):
                    item = lw.item(idx)
                    data = item.data(Qt.ItemDataRole.UserRole) or {}
                    nid = data.get('id')
                    col.append((nid, idx))
                state[key] = col
        except Exception:
            pass
        return state

    def _swimlane_persist(self, state: dict) -> bool:
        """将 state 写回 JSON：为每个节点更新 status 与 kanban_order。"""
        try:
            fp = getattr(self, '_current_project_file', None)
            if not fp or not Path(fp).exists():
                return False
            path = Path(fp)
            root = self._read_json(path)
            if root is None:
                return False
            # 扫描三列写回
            for key, arr in state.items():
                for nid, order in arr:
                    if not nid:
                        continue
                    self._update_node_in_json(root, nid, {'status': key, 'kanban_order': int(order)})
            if not self._write_json_atomic(path, root):
                return False
            return True
        except Exception:
            return False

    def _swimlane_after_drop(self):
        """拖拽完成后的统一收集和持久化，并同步树缓存。"""
        try:
            state = self._swimlane_collect_state()
            ok = self._swimlane_persist(state)
            # 同步树中缓存的节点字段（status、kanban_order）
            if ok:
                try:
                    for key, arr in state.items():
                        for nid, order in arr:
                            it = self._find_item_by_node_id(nid)
                            if it is None:
                                continue
                            data = it.data(0, Qt.ItemDataRole.UserRole) or {}
                            if data.get('type') == 'node':
                                node_obj = data.get('node') or {}
                                if isinstance(node_obj, dict):
                                    node_obj['status'] = key
                                    node_obj['kanban_order'] = int(order)
                                    data['node'] = node_obj
                                    it.setData(0, Qt.ItemDataRole.UserRole, data)
                except Exception:
                    pass
            try:
                logger_sink.log_user_message(self._session_id, "swimlane_drop_persist")
            except Exception:
                pass
        except Exception:
            pass

# ---------- 内部类：拖拽行为感知 ----------
class _DragAwareTree(QTreeWidget):
    def __init__(self, page: ProjectPage):
        super().__init__()
        self._page = page

    def keyPressEvent(self, event):
        try:
            item = self.currentItem()
            key = event.key()
            mods = event.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            alt = bool(mods & Qt.KeyboardModifier.AltModifier)

            # 正在内联编辑标题时，不拦截回车键，让默认编辑器处理（提交编辑而不创建新节点）
            try:
                if self.state() == QAbstractItemView.State.EditingState:
                    super().keyPressEvent(event)
                    return
            except Exception:
                pass

            # Ctrl+Enter -> 新建子节点
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ctrl:
                self._page._action_new_child(item)
                event.accept()
                return
            # Alt+Enter -> 新建同级节点
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and alt:
                self._page._action_new_sibling(item)
                event.accept()
                return
            # Ctrl+C -> 复制
            if ctrl and key == Qt.Key.Key_C:
                self._page._action_copy(item)
                event.accept()
                return
            # Ctrl+V -> 粘贴为子节点
            if ctrl and key == Qt.Key.Key_V:
                self._page._action_paste(item)
                event.accept()
                return
            # Ctrl+X -> 剪切
            if ctrl and key == Qt.Key.Key_X:
                self._page._action_cut(item)
                event.accept()
                return
            # Delete -> 删除所选节点（前端层，带确认），并触发持久化
            if key == Qt.Key.Key_Delete:
                self._page._action_delete(item)
                # 删除后立即全量保存，避免20秒窗口内误差
                try:
                    self._page._save_all_to_file()
                except Exception:
                    pass
                event.accept()
                return
        except Exception:
            pass
        # 回退默认处理
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        try:
            # Ctrl 强制复制
            if event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                event.setDropAction(Qt.DropAction.CopyAction)
            elif self._page._drag_move_mode:
                event.setDropAction(Qt.DropAction.MoveAction)
            else:
                event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
        except Exception:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        try:
            if event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                event.setDropAction(Qt.DropAction.CopyAction)
            elif self._page._drag_move_mode:
                event.setDropAction(Qt.DropAction.MoveAction)
            else:
                event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
        except Exception:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        try:
            # 让默认内部移动先执行；复制模式下强制为复制
            if event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                self.setDefaultDropAction(Qt.DropAction.CopyAction)
            elif self._page._drag_move_mode:
                self.setDefaultDropAction(Qt.DropAction.MoveAction)
            else:
                self.setDefaultDropAction(Qt.DropAction.CopyAction)
            super().dropEvent(event)
            self._page.undo_stack.push(QUndoCommand("拖拽(前端层)"))
            try:
                logger_sink.log_user_message(self._page._session_id, "drag_drop")
            except Exception:
                pass
            # 即时持久化：拖拽完成后立即保存
            try:
                self._page._autosave_flush()
            except Exception:
                pass
            try:
                self._page._save_all_to_file()
            except Exception:
                pass
        except Exception:
            try:
                super().dropEvent(event)
            except Exception:
                pass


class _SwimlaneList(QListWidget):
    """泳道列：承载某个 swimlane key（状态或管理标签）。
    支持跨列与列内拖拽排序。"""
    def __init__(self, page: ProjectPage, status_key: str):
        super().__init__()
        self._page = page
        self._status_key = status_key

    def dropEvent(self, event):
        """先执行默认的接收/移动，再触发统一收集与持久化。"""
        try:
            super().dropEvent(event)
            try:
                # 记录一次操作
                self._page.undo_stack.push(QUndoCommand("泳道拖拽"))
            except Exception:
                pass
            # 拖拽完成后：收集 -> 持久化 -> 同步树缓存
            try:
                self._page._swimlane_after_drop()
            except Exception:
                pass
            # 立即刷新一次显示（可选）
            try:
                self._page._swimlane_load()
            except Exception:
                pass
            try:
                logger_sink.log_user_message(self._page._session_id, f"swimlane_drop@{self._status_key}")
            except Exception:
                pass
        except Exception:
            try:
                super().dropEvent(event)
            except Exception:
                pass
