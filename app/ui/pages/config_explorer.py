from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import os
import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QTextEdit, 
    QLabel, QHeaderView, QPushButton, QApplication
)
from PySide6.QtCore import Qt, Signal

from app.ui.widgets.collapsible_panel import CollapsiblePanel
from utils.error_handler import ErrorHandler
from services.config_service import ConfigService


class ConfigExplorerPage(QWidget):
    """实验性配置目录树页面，显示配置文件结构和详情。"""
    
    def __init__(self):
        super().__init__()
        self.logger = ErrorHandler.setup_logging("config_explorer")
        self._setup_ui()
        self._populate_tree()
        
    def _setup_ui(self):
        """设置UI布局"""
        layout = QHBoxLayout(self)
        
        # 使用分割器创建左右两栏
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：目录树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["配置目录"])
        self.tree.setColumnCount(1)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemClicked.connect(self._on_item_clicked)
        
        # 右侧：配置详情
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # 添加按钮行
        buttons_layout = QHBoxLayout()
        self.refresh_button = QPushButton("刷新配置树")
        self.refresh_button.clicked.connect(self.refresh_tree)
        buttons_layout.addWidget(self.refresh_button)
        
        buttons_layout.addStretch()
        
        self.file_path_label = QLabel("未选择文件")
        self.detail_editor = QTextEdit()
        self.detail_editor.setReadOnly(True)
        
        right_layout.addLayout(buttons_layout)
        right_layout.addWidget(self.file_path_label)
        right_layout.addWidget(self.detail_editor)
        
        # 添加到分割器
        splitter.addWidget(self.tree)
        splitter.addWidget(right_panel)
        splitter.setSizes([200, 400])  # 初始分割比例
        
        layout.addWidget(splitter)
        
    def refresh_tree(self):
        """刷新配置树，重新加载所有节点"""
        self.logger.info("[调试] 开始刷新配置树")
        
        # 清空树
        self.tree.clear()
        
        # 重新填充
        self._populate_tree()
        
        # 重置详情面板
        self.file_path_label.setText("未选择文件")
        self.detail_editor.setPlainText("请选择文件查看内容")
        
        # 刷新UI
        self.tree.viewport().update()
        self.tree.update()
        QApplication.processEvents()
        
        self.logger.info("[调试] 配置树刷新完成")
        
    def _populate_tree(self):
        """填充配置目录树"""
        try:
            # 获取config根目录
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            config_dir = base_dir / 'config'
            
            # 创建根节点
            root = QTreeWidgetItem(self.tree)
            root.setText(0, "config")
            root.setExpanded(True)
            
            # 创建子节点
            self._add_category_node(root, "agents", config_dir / "agents")
            # 新增 teams 分类（与 agents 同级）
            self._add_category_node(root, "teams", config_dir / "teams")
            self._add_category_node(root, "models", config_dir / "models")
            self._add_category_node(root, "tools", config_dir / "tools")
            self._add_category_node(root, "mcp", config_dir / "mcp")
            self._add_category_node(root, "vectorstores", config_dir / "vectorstores", False)
            
            # 强制刷新UI
            self.tree.viewport().update()
            
        except Exception as e:
            self.logger.error(f"填充配置树失败: {e}")
    
    def _add_category_node(self, parent: QTreeWidgetItem, name: str, dir_path: Path, scan_files: bool = True):
        """添加一个分类节点，如agents、models等"""
        if not dir_path.exists():
            return
            
        category = QTreeWidgetItem(parent)
        category.setText(0, name)
        category.setData(0, Qt.ItemDataRole.UserRole, str(dir_path))
        
        # 特殊处理：agents和teams节点
        if name.lower() == "agents" or name.lower() == "teams":
            category.setData(0, Qt.ItemDataRole.UserRole + 1, "expandable")
        
        # 扫描目录添加文件
        if scan_files and dir_path.is_dir():
            try:
                for p in sorted(dir_path.glob('*.json')):
                    file_item = QTreeWidgetItem(category)
                    file_item.setText(0, p.name)
                    file_item.setData(0, Qt.ItemDataRole.UserRole, str(p))
                    # 立即为 agents 与 teams 填充子节点，避免用户必须点击分类节点
                    if name.lower() == "agents":
                        self._populate_agent_file_node(file_item, p)
                    elif name.lower() == "teams":
                        self._populate_team_file_node(file_item, p)
            except Exception as e:
                self.logger.warning(f"扫描目录{dir_path}失败: {e}")
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """处理目录树项目点击事件"""
        try:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            item_text = item.text(0)
            role_value = item.data(0, Qt.ItemDataRole.UserRole + 1)
            component_type = item.data(0, Qt.ItemDataRole.UserRole + 2)
            
            self.logger.info(f"[调试] 点击节点: {item_text}, 路径: {path}, 角色值: {role_value}, 组件类型: {component_type}")

            # 处理 Team participant 节点本身（显示该 participant 的 config 片段）
            if role_value == "team_participant":
                try:
                    idx = int(component_type) if component_type is not None else -1
                    if not path:
                        self.logger.warning("[调试] team_participant 节点未携带有效路径")
                        return
                    self._load_team_participant_config(Path(path), idx)
                except Exception as e:
                    self.logger.error(f"解析 team_participant 失败: {e}")
                return

            # 优先处理 Team participant 组件节点
            if role_value == "team_part_component":
                try:
                    comp_str = str(component_type) if component_type is not None else ""
                    comp, idx_str = comp_str.split("|", 1)
                    idx = int(idx_str)
                    if not path:
                        self.logger.warning("[调试] team_part_component 节点未携带有效路径")
                        return
                    self._load_team_participant_component(Path(path), idx, comp)
                except Exception as e:
                    self.logger.error(f"解析 team_part_component 失败: {e}")
                return
            
            # 检查是否是组件节点（工具、MCP、向量库、模型）
            if component_type in ['tools', 'mcp', 'vectorstores', 'model']:
                self.logger.info(f"[调试] 检测到组件节点点击: {item_text}, 类型: {component_type}")
                parent = item.parent()  # 获取父节点（agent配置文件节点）
                if parent:
                    agent_path = parent.data(0, Qt.ItemDataRole.UserRole)
                    if agent_path:
                        self.logger.info(f"[调试] 加载组件配置: {component_type}, 路径: {agent_path}")
                        self._load_component_config(Path(agent_path), component_type)
                    else:
                        self.logger.warning(f"[调试] 父节点没有有效路径")
                else:
                    self.logger.warning(f"[调试] 未找到组件节点的父节点")
                return
                
            # 处理普通路径
            if not path:
                return
                
            path_obj = Path(path)
            
            # 处理文件点击 - 显示内容
            if path_obj.is_file() and path_obj.suffix.lower() == '.json':
                self._load_file_content(path_obj)
                
            # 特殊处理：agents/teams点击 - 展开子组件
            elif item.data(0, Qt.ItemDataRole.UserRole + 1) == "expandable":
                self.logger.info(f"[调试] 点击展开节点 {item.text(0)}")
                # 强制清除子项并重新展开
                while item.childCount() > 0:
                    item.removeChild(item.child(0))
                self._expand_component_details(item, path_obj)
                self.tree.update()
                
        except Exception as e:
            self.logger.error(f"处理点击事件失败: {e}")
    
    def _load_file_content(self, file_path: Path):
        """加载并显示文件内容"""
        try:
            self.file_path_label.setText(str(file_path))
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
                
            # 格式化JSON并显示
            formatted_json = json.dumps(content, indent=4, ensure_ascii=False)
            self.detail_editor.setPlainText(formatted_json)
            
        except Exception as e:
            self.detail_editor.setPlainText(f"加载文件失败: {e}")
            self.logger.error(f"加载文件内容失败: {e}")
    
    def _analyze_agent_config(self, file_path: Path) -> Dict[str, bool]:
        """分析agent配置文件，确定包含哪些组件
        
        返回:
            Dict[str, bool]: 包含各组件存在状态的字典，如 {'tools': True, 'mcp': False, 'vectorstores': False, 'model': False}
        """
        components = {
            'tools': False,
            'mcp': False,
            'vectorstores': False,
            'model': False
        }
        
        try:
            if file_path.is_file() and file_path.suffix.lower() == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 检查工具组件
                if 'tools' in data and isinstance(data['tools'], list) and len(data['tools']) > 0:
                    components['tools'] = True
                    
                # 检查capabilities中的工具配置
                if 'capabilities' in data and 'tools' in data['capabilities']:
                    # 只要存在工具配置结构就认为有工具组件
                    if data['capabilities']['tools']:
                        components['tools'] = True
                
                # 检查MCP组件
                if 'capabilities' in data and 'mcp' in data['capabilities'] and data['capabilities']['mcp']:
                    components['mcp'] = True
                
                # 检查向量库组件
                if 'capabilities' in data and 'vectorstores' in data['capabilities'] and data['capabilities']['vectorstores']:
                    components['vectorstores'] = True
                    
                # 另一种向量库表示方式检查
                if 'vector_db' in data or 'vector_config' in data:
                    components['vectorstores'] = True
                    
                # 检查模型组件
                if 'model_client' in data or 'model' in data:
                    components['model'] = True
                    
                self.logger.info(f"[调试] 分析文件 {file_path.name} 组件检测结果: {components}")
        except Exception as e:
            self.logger.error(f"分析配置文件失败: {e}")
            
        return components
                
    def _expand_component_details(self, item: QTreeWidgetItem, dir_path: Path):
        """展开组件详情节点（agents/teams目录下的文件组件节点）"""
        self.logger.info(f"[调试] 开始展开节点细节: {item.text(0)}, 路径: {dir_path}, 当前子项数: {item.childCount()}")
        
        # 检查是否已经展开过组件节点
        if item.childCount() > 0:
            has_component = False
            for i in range(item.childCount()):
                child = item.child(i)
                child_text = child.text(0)
                self.logger.info(f"[调试] 检查子项 {i}: {child_text}")
                if child_text in ["工具", "MCP", "向量库", "模型", "participants"]:
                    has_component = True
            
            if has_component:
                self.logger.info(f"[调试] 节点 {item.text(0)} 已经展开组件节点，不重复操作")
                return
            else:
                self.logger.info(f"[调试] 节点 {item.text(0)} 虽有子项但无组件节点，继续处理")
        
        try:
            is_teams_dir = isinstance(dir_path, Path) and ("teams" in str(dir_path).lower())
            # 获取所有子文件
            files = []
            if dir_path.is_dir():
                files = list(sorted(dir_path.glob('*.json')))
                
            # 首先添加JSON文件作为配置选项
            for file_path in files:
                file_item = QTreeWidgetItem(item)
                file_item.setText(0, file_path.name)
                file_item.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                
                if is_teams_dir:
                    # 为 team 配置文件添加 participants 列表及每个 participant 的组件
                    self._expand_team_participants(file_item, file_path)
                else:
                    # 维持原有 agent 文件的组件生成逻辑
                    components = self._analyze_agent_config(file_path)
                    self.logger.info(f"[调试] 分析文件 {file_path.name} 组件结果: {components}")
                    # 模型（始终添加）
                    model_node = QTreeWidgetItem(file_item)
                    model_label = self._make_label("模型", self._extract_agent_component_names(file_path, 'model'))
                    model_node.setText(0, model_label)
                    model_node.setData(0, Qt.ItemDataRole.UserRole + 2, "model")
                    model_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                    model_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
                    file_item.setExpanded(True)
                    # 工具
                    if components['tools']:
                        tools_node = QTreeWidgetItem(file_item)
                        tools_label = self._make_label("工具", self._extract_agent_component_names(file_path, 'tools'))
                        tools_node.setText(0, tools_label)
                        tools_node.setData(0, Qt.ItemDataRole.UserRole + 2, "tools")
                        tools_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                        tools_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
                    # MCP
                    if components['mcp']:
                        mcp_node = QTreeWidgetItem(file_item)
                        mcp_label = self._make_label("MCP", self._extract_agent_component_names(file_path, 'mcp'))
                        mcp_node.setText(0, mcp_label)
                        mcp_node.setData(0, Qt.ItemDataRole.UserRole + 2, "mcp")
                        mcp_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                        mcp_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
                    # 向量库
                    if components['vectorstores']:
                        vector_node = QTreeWidgetItem(file_item)
                        vector_label = self._make_label("向量库", self._extract_agent_component_names(file_path, 'vectorstores'))
                        vector_node.setText(0, vector_label)
                        vector_node.setData(0, Qt.ItemDataRole.UserRole + 2, "vectorstores")
                        vector_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                        vector_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
                    
            # 展开节点并强制刷新UI - 增强刷新机制
            item.setExpanded(True)
            
            # 多重刷新方式
            self.tree.viewport().update()
            self.tree.update()
            self.tree.repaint()
            
            # 触发布局更新与重绘
            self.tree.updateGeometries()
            self.tree.viewport().update()
            self.tree.repaint()
            
            # 强制处理所有挂起的事件
            QApplication.processEvents()
            
            # 记录日志
            self.logger.info(f"[调试][追踪] 完成强制刷新相关操作，子节点总数: {item.childCount()}")
            
        except Exception as e:
            self.logger.error(f"展开组件详情失败: {e}")
            
            # 出错时添加提示
            error_item = QTreeWidgetItem(item)
            error_item.setText(0, f"加载失败: {e}")
            error_item.setData(0, Qt.ItemDataRole.UserRole, "")
            item.setExpanded(True)

    def _make_label(self, base: str, names: List[str], limit: int = 3) -> str:
        """生成带名称预览的标签，如: 工具: a, b, c …"""
        try:
            arr = [str(x) for x in names if x]
            if not arr:
                return base
            preview = ", ".join(arr[:limit])
            suffix = " …" if len(arr) > limit else ""
            return f"{base}: {preview}{suffix}"
        except Exception:
            return base

    def _extract_agent_component_names(self, file_path: Path, component_type: str) -> List[str]:
        """从 agent 配置文件中提取组件名称列表，用于展示。只读。"""
        names: List[str] = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if component_type == 'tools':
                # 1) 顶层 tools（可能为 list/dict）
                tools = cfg.get('tools')
                if isinstance(tools, list):
                    for t in tools:
                        n = (t or {}).get('name') or (t or {}).get('id') or (t or {}).get('tool')
                        if n:
                            names.append(n)
                elif isinstance(tools, dict):
                    names.extend(list(tools.keys()))
                # 2) capabilities.tools（通常为 dict）
                caps = cfg.get('capabilities', {}) if isinstance(cfg.get('capabilities'), dict) else {}
                ctools = caps.get('tools')
                if isinstance(ctools, dict):
                    for k, v in ctools.items():
                        names.append(v.get('name') or k)
                elif isinstance(ctools, list):
                    for t in ctools:
                        n = (t or {}).get('name') or (t or {}).get('id')
                        if n:
                            names.append(n)
            elif component_type == 'mcp':
                caps = cfg.get('capabilities', {}) if isinstance(cfg.get('capabilities'), dict) else {}
                mcp = caps.get('mcp')
                if isinstance(mcp, dict):
                    # 兼容 servers/list/map
                    if 'servers' in mcp and isinstance(mcp['servers'], list):
                        names.extend([str(s.get('name') or s.get('id') or s) for s in mcp['servers']])
                    else:
                        names.extend(list(mcp.keys()))
                elif isinstance(mcp, list):
                    names.extend([str(x) for x in mcp])
            elif component_type == 'vectorstores':
                caps = cfg.get('capabilities', {}) if isinstance(cfg.get('capabilities'), dict) else {}
                vs = caps.get('vectorstores')
                if isinstance(vs, dict):
                    names.extend(list(vs.keys()))
                if 'vector_db' in cfg:
                    names.append(str(cfg.get('vector_db')))
                if 'vector_config' in cfg and isinstance(cfg['vector_config'], dict):
                    names.extend(list(cfg['vector_config'].keys()))
            elif component_type == 'model':
                mc = cfg.get('model_client') or {}
                if isinstance(mc, dict):
                    # 兼容嵌套的 model_client.config.*
                    conf = mc.get('config') if isinstance(mc.get('config'), dict) else {}
                    n = (
                        mc.get('name')
                        or mc.get('model')
                        or mc.get('model_id')
                        or (conf.get('name') if conf else None)
                        or (conf.get('model') if conf else None)
                        or (conf.get('model_id') if conf else None)
                    )
                    if n:
                        names.append(n)
                m = cfg.get('model')
                if isinstance(m, dict):
                    n = m.get('name') or m.get('model') or m.get('model_id')
                    if n:
                        names.append(n)
                elif isinstance(m, str):
                    names.append(m)
        except Exception:
            pass
        # 去重并清洗
        uniq = []
        for x in names:
            s = str(x)
            if s and s not in uniq:
                uniq.append(s)
        return uniq

    def _extract_team_part_component_names(self, agent_cfg: Dict[str, Any], component_type: str) -> List[str]:
        """从 team 的 participant.config 中提取组件名称列表。只读。"""
        names: List[str] = []
        try:
            if component_type == 'tools':
                workbench = agent_cfg.get('workbench', []) if isinstance(agent_cfg.get('workbench'), list) else []
                for w in workbench:
                    try:
                        tools = ((w or {}).get('config', {}) or {}).get('tools')
                        if isinstance(tools, dict):
                            for k, v in tools.items():
                                names.append(v.get('name') or k)
                        elif isinstance(tools, list):
                            for t in tools:
                                n = (t or {}).get('name') or (t or {}).get('id')
                                if n:
                                    names.append(n)
                    except Exception:
                        pass
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                ctools = caps.get('tools')
                if isinstance(ctools, dict):
                    for k, v in ctools.items():
                        names.append(v.get('name') or k)
                elif isinstance(ctools, list):
                    for t in ctools:
                        n = (t or {}).get('name') or (t or {}).get('id')
                        if n:
                            names.append(n)
            elif component_type == 'mcp':
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                mcp = caps.get('mcp')
                if isinstance(mcp, dict):
                    if 'servers' in mcp and isinstance(mcp['servers'], list):
                        names.extend([str(s.get('name') or s.get('id') or s) for s in mcp['servers']])
                    else:
                        names.extend(list(mcp.keys()))
                elif isinstance(mcp, list):
                    names.extend([str(x) for x in mcp])
            elif component_type == 'vectorstores':
                mems = agent_cfg.get('memory', []) if isinstance(agent_cfg.get('memory'), list) else []
                for m in mems:
                    try:
                        prov = (m or {}).get('provider') or (m or {}).get('name')
                        if prov:
                            names.append(str(prov))
                    except Exception:
                        pass
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                vs = caps.get('vectorstores')
                if isinstance(vs, dict):
                    names.extend(list(vs.keys()))
            elif component_type == 'model':
                mc = agent_cfg.get('model_client') or {}
                if isinstance(mc, dict):
                    conf = mc.get('config') if isinstance(mc.get('config'), dict) else {}
                    n = (
                        mc.get('name')
                        or mc.get('model')
                        or mc.get('model_id')
                        or (conf.get('name') if conf else None)
                        or (conf.get('model') if conf else None)
                        or (conf.get('model_id') if conf else None)
                    )
                    if n:
                        names.append(n)
                m = agent_cfg.get('model')
                if isinstance(m, dict):
                    n = m.get('name') or m.get('model') or m.get('model_id')
                    if n:
                        names.append(n)
                elif isinstance(m, str):
                    names.append(m)
        except Exception:
            pass
        uniq: List[str] = []
        for x in names:
            s = str(x)
            if s and s not in uniq:
                uniq.append(s)
        return uniq

    def _populate_agent_file_node(self, file_item: QTreeWidgetItem, file_path: Path):
        """为单个 agent 配置文件节点立即添加组件子节点（模型/工具/MCP/向量库）。"""
        try:
            components = self._analyze_agent_config(file_path)
            # 模型（始终添加）
            model_node = QTreeWidgetItem(file_item)
            model_label = self._make_label("模型", self._extract_agent_component_names(file_path, 'model'))
            model_node.setText(0, model_label)
            model_node.setData(0, Qt.ItemDataRole.UserRole + 2, "model")
            model_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
            model_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
            # 工具
            if components['tools']:
                tools_node = QTreeWidgetItem(file_item)
                tools_label = self._make_label("工具", self._extract_agent_component_names(file_path, 'tools'))
                tools_node.setText(0, tools_label)
                tools_node.setData(0, Qt.ItemDataRole.UserRole + 2, "tools")
                tools_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                tools_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
            # MCP
            if components['mcp']:
                mcp_node = QTreeWidgetItem(file_item)
                mcp_label = self._make_label("MCP", self._extract_agent_component_names(file_path, 'mcp'))
                mcp_node.setText(0, mcp_label)
                mcp_node.setData(0, Qt.ItemDataRole.UserRole + 2, "mcp")
                mcp_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                mcp_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
            # 向量库
            if components['vectorstores']:
                vector_node = QTreeWidgetItem(file_item)
                vector_label = self._make_label("向量库", self._extract_agent_component_names(file_path, 'vectorstores'))
                vector_node.setText(0, vector_label)
                vector_node.setData(0, Qt.ItemDataRole.UserRole + 2, "vectorstores")
                vector_node.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
                vector_node.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
            file_item.setExpanded(True)
        except Exception as e:
            self.logger.error(f"[调试] 填充 agent 组件失败: {e}")

    def _populate_team_file_node(self, file_item: QTreeWidgetItem, file_path: Path):
        """为单个 team 配置文件节点立即添加 participants 列表及其组件子节点。"""
        try:
            self._expand_team_participants(file_item, file_path)
            file_item.setExpanded(True)
        except Exception as e:
            self.logger.error(f"[调试] 填充 team participants 失败: {e}")

    def _load_team_participant_config(self, team_path: Path, participant_index: int):
        """加载并显示 team 中某个 participant 的完整 config 片段（只读）。"""
        try:
            with open(team_path, 'r', encoding='utf-8') as f:
                team_data = json.load(f)
            agents = []
            if isinstance(team_data, dict) and 'config' in team_data and isinstance(team_data['config'], dict):
                agents = team_data['config'].get('agents', []) or []
            if participant_index < 0 or participant_index >= len(agents):
                self.detail_editor.setPlainText(f"participants[{participant_index}] 不存在")
                return
            agent_entry = agents[participant_index]
            agent_cfg = agent_entry.get('config', {}) if isinstance(agent_entry, dict) else {}
            self.file_path_label.setText(f"{team_path} - participant[{participant_index}] 配置")
            formatted = json.dumps(agent_cfg, indent=4, ensure_ascii=False)
            self.detail_editor.setPlainText(formatted)
        except Exception as e:
            self.detail_editor.setPlainText(f"加载 participant 配置失败: {e}")
            self.logger.error(f"加载 participant 配置失败: {e}")
    
    def _load_team_participant_component(self, team_path: Path, participant_index: int, component_type: str):
        """加载并显示 team 中某个 participant 的指定组件配置。
        只读展示，不修改任何原始配置。
        """
        try:
            with open(team_path, 'r', encoding='utf-8') as f:
                team_data = json.load(f)
            agents = []
            if isinstance(team_data, dict) and 'config' in team_data and isinstance(team_data['config'], dict):
                agents = team_data['config'].get('agents', []) or []
            if participant_index < 0 or participant_index >= len(agents):
                self.detail_editor.setPlainText(f"participants[{participant_index}] 不存在")
                return
            agent_entry = agents[participant_index]
            agent_cfg = agent_entry.get('config', {}) if isinstance(agent_entry, dict) else {}

            component_config = {}
            # 组件提取逻辑与 agent 视图保持一致风格
            if component_type == 'tools':
                # workbench[*].config.tools 汇总
                workbench = agent_cfg.get('workbench', []) if isinstance(agent_cfg.get('workbench'), list) else []
                aggregated = []
                for w in workbench:
                    try:
                        tools = ((w or {}).get('config', {}) or {}).get('tools')
                        if tools:
                            aggregated.append(tools)
                    except Exception:
                        pass
                if aggregated:
                    component_config['workbench_tools'] = aggregated
                # capabilities.tools 若存在也展示
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                if 'tools' in caps:
                    component_config['capabilities.tools'] = caps['tools']

            elif component_type == 'mcp':
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                if 'mcp' in caps:
                    component_config['mcp'] = caps['mcp']

            elif component_type == 'vectorstores':
                # memory 列表直接展示；兼容 capabilities.vectorstores（若存在）
                mems = agent_cfg.get('memory', []) if isinstance(agent_cfg.get('memory'), list) else []
                if mems:
                    component_config['memory'] = mems
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                if 'vectorstores' in caps:
                    component_config['capabilities.vectorstores'] = caps['vectorstores']

            elif component_type == 'model':
                if 'model_client' in agent_cfg:
                    component_config['model_client'] = agent_cfg['model_client']
                if 'model' in agent_cfg:
                    component_config['model'] = agent_cfg['model']

            # UI 展示
            self.file_path_label.setText(f"{team_path} - participant[{participant_index}] - {component_type}组件配置")
            if component_config:
                formatted = json.dumps(component_config, indent=4, ensure_ascii=False)
                self.detail_editor.setPlainText(formatted)
            else:
                self.detail_editor.setPlainText(f"未发现 {component_type} 相关配置")
        except Exception as e:
            self.detail_editor.setPlainText(f"加载 team 组件配置失败: {e}")
            self.logger.error(f"加载 team 组件配置失败: {e}")
    def _expand_team_participants(self, team_file_item: QTreeWidgetItem, team_file_path: Path):
        """为 team 配置文件创建参与者(agent) 节点（直接挂在配置文件节点下）及其组件子节点。"""
        try:
            with open(team_file_path, 'r', encoding='utf-8') as f:
                team_data = json.load(f)
            # 遍历 agents
            agents = []
            if isinstance(team_data, dict) and 'config' in team_data and isinstance(team_data['config'], dict):
                agents = team_data['config'].get('agents', []) or []
            for idx, agent in enumerate(agents):
                if not isinstance(agent, dict) or 'config' not in agent:
                    continue
                agent_cfg = agent['config'] if isinstance(agent['config'], dict) else {}
                name = agent_cfg.get('name', f"agent-{idx}")
                agent_node = QTreeWidgetItem(team_file_item)
                agent_node.setText(0, name)
                agent_node.setData(0, Qt.ItemDataRole.UserRole, str(team_file_path))
                agent_node.setData(0, Qt.ItemDataRole.UserRole + 1, "team_participant")
                agent_node.setData(0, Qt.ItemDataRole.UserRole + 2, idx)  # 保存索引
                # 组件判断
                # 模型（仅当解析到模型名时添加）
                model_names = self._extract_team_part_component_names(agent_cfg, 'model')
                if model_names:
                    model_node = QTreeWidgetItem(agent_node)
                    model_label = self._make_label("模型", model_names)
                    model_node.setText(0, model_label)
                    model_node.setData(0, Qt.ItemDataRole.UserRole, str(team_file_path))
                    model_node.setData(0, Qt.ItemDataRole.UserRole + 1, "team_part_component")
                    model_node.setData(0, Qt.ItemDataRole.UserRole + 2, f"model|{idx}")
                # 工具
                has_tools = False
                wb = agent_cfg.get('workbench', []) if isinstance(agent_cfg.get('workbench'), list) else []
                for w in wb:
                    try:
                        if isinstance(w, dict) and 'config' in w and 'tools' in w['config'] and w['config']['tools']:
                            has_tools = True
                            break
                    except Exception:
                        pass
                if has_tools:
                    tools_node = QTreeWidgetItem(agent_node)
                    tools_label = self._make_label("工具", self._extract_team_part_component_names(agent_cfg, 'tools'))
                    tools_node.setText(0, tools_label)
                    tools_node.setData(0, Qt.ItemDataRole.UserRole, str(team_file_path))
                    tools_node.setData(0, Qt.ItemDataRole.UserRole + 1, "team_part_component")
                    tools_node.setData(0, Qt.ItemDataRole.UserRole + 2, f"tools|{idx}")
                # MCP
                has_mcp = False
                caps = agent_cfg.get('capabilities', {}) if isinstance(agent_cfg.get('capabilities'), dict) else {}
                if caps.get('mcp'):
                    has_mcp = True
                if has_mcp:
                    mcp_node = QTreeWidgetItem(agent_node)
                    mcp_label = self._make_label("MCP", self._extract_team_part_component_names(agent_cfg, 'mcp'))
                    mcp_node.setText(0, mcp_label)
                    mcp_node.setData(0, Qt.ItemDataRole.UserRole, str(team_file_path))
                    mcp_node.setData(0, Qt.ItemDataRole.UserRole + 1, "team_part_component")
                    mcp_node.setData(0, Qt.ItemDataRole.UserRole + 2, f"mcp|{idx}")
                # 向量库（检查 memory 中是否含 chroma 或存在 memory）
                has_vector = False
                mems = agent_cfg.get('memory', []) if isinstance(agent_cfg.get('memory'), list) else []
                for m in mems:
                    try:
                        prov = (m or {}).get('provider', '')
                        if isinstance(prov, str) and ('chromadb' in prov.lower() or prov):
                            has_vector = True
                            break
                    except Exception:
                        pass
                if has_vector:
                    vs_node = QTreeWidgetItem(agent_node)
                    vector_label = self._make_label("向量库", self._extract_team_part_component_names(agent_cfg, 'vectorstores'))
                    vs_node.setText(0, vector_label)
                    vs_node.setData(0, Qt.ItemDataRole.UserRole, str(team_file_path))
                    vs_node.setData(0, Qt.ItemDataRole.UserRole + 1, "team_part_component")
                    vs_node.setData(0, Qt.ItemDataRole.UserRole + 2, f"vectorstores|{idx}")
                # 展开单个 participant
                agent_node.setExpanded(True)
            # 展开文件节点
            team_file_item.setExpanded(True)
        except Exception as e:
            self.logger.error(f"[调试] 展开 team participants 失败: {e}")
    
    def _add_component_node(self, parent: QTreeWidgetItem, label: str, component_type: str) -> QTreeWidgetItem:
        """添加组件节点（工具、MCP等）
        
        Args:
            parent: 父节点
            label: 节点显示文本
            component_type: 组件类型
            
        Returns:
            QTreeWidgetItem: 创建的组件节点
        """
        self.logger.info(f"[调试][追踪] 开始为 {parent.text(0)} 添加组件节点: {label} (类型: {component_type})")
        
        # 先检查父节点是否有效
        if not parent or parent.treeWidget() != self.tree:
            self.logger.error(f"[调试][追踪] 父节点无效或不属于当前树: {parent}")
            return None
            
        # 创建节点
        component = QTreeWidgetItem(parent)
        component.setText(0, label)
        
        # 设置各种数据角色
        self.logger.info(f"[调试][追踪] 设置节点数据: {label}, 类型: {component_type}")
        # 将组件类型存储在UserRole+2位置，与_on_item_clicked中的读取位置匹配
        component.setData(0, Qt.ItemDataRole.UserRole + 2, component_type)
        component.setData(0, Qt.ItemDataRole.UserRole, component_type)  # 同时保留原有位置以保持兼容性
        component.setData(0, Qt.ItemDataRole.UserRole + 1, "component")
        
        # 强制刷新父节点显示
        parent.setExpanded(True)
        
        # 检查节点是否成功添加
        added = False
        for i in range(parent.childCount()):
            if parent.child(i) == component:
                added = True
                break
                
        self.logger.info(f"[调试][追踪] 组件节点 {label} 添加状态: {'成功' if added else '失败'}, 父节点子项数量: {parent.childCount()}")
        
        # 重要：强制更新UI
        self.tree.viewport().update()  # 强制更新视图
        # 尝试再次强制刷新
        self.tree.update()
        
        return component
        
    def _load_component_config(self, agent_path: Path, component_type: str):
        """加载并显示agent中特定组件的配置"""
        try:
            # 加载agent配置文件
            with open(agent_path, 'r', encoding='utf-8') as f:
                agent_config = json.load(f)
                
            # 设置标题显示
            self.file_path_label.setText(f"{agent_path} - {component_type}组件配置")
            
            # 提取对应组件配置
            component_config = {}
            
            # 根据组件类型提取配置
            if component_type == 'tools':
                # 直接从agent配置的tools字段获取
                if 'tools' in agent_config and agent_config['tools']:
                    component_config['tools'] = agent_config['tools']
                    
                # 从capabilities.tools获取
                if 'capabilities' in agent_config and 'tools' in agent_config['capabilities']:
                    component_config['capabilities.tools'] = agent_config['capabilities']['tools']
                    
                # 尝试获取外部工具配置路径并加载内容
                tool_paths = self._extract_tool_paths(agent_config)
                if tool_paths:
                    component_config['external_tools'] = {}
                    for tool_name, tool_path in tool_paths.items():
                        try:
                            with open(tool_path, 'r', encoding='utf-8') as tf:
                                component_config['external_tools'][tool_name] = json.load(tf)
                        except Exception as e:
                            component_config['external_tools'][tool_name] = f"加载失败: {e}"
            
            elif component_type == 'mcp':
                # 从capabilities.mcp获取
                if 'capabilities' in agent_config and 'mcp' in agent_config['capabilities']:
                    component_config['mcp'] = agent_config['capabilities']['mcp']
            
            elif component_type == 'vectorstores':
                # 从capabilities.vectorstores获取
                if 'capabilities' in agent_config and 'vectorstores' in agent_config['capabilities']:
                    component_config['vectorstores'] = agent_config['capabilities']['vectorstores']
                    
                # 检查其他向量库相关字段
                for field in ['vector_db', 'vector_config']:
                    if field in agent_config:
                        component_config[field] = agent_config[field]
            
            elif component_type == 'model':
                # 从 model_client 获取模型配置
                if 'model_client' in agent_config:
                    component_config['model_client'] = agent_config['model_client']
                    self.logger.info(f"[调试] 读取到model_client配置: {len(str(agent_config['model_client']))}字节")
                
                # 检查其他模型相关字段
                if 'model' in agent_config:
                    component_config['model'] = agent_config['model']
                    self.logger.info(f"[调试] 读取到model配置: {len(str(agent_config['model']))}字节")
                    
            # 显示读取到的组件配置
            if component_config:
                formatted_json = json.dumps(component_config, indent=4, ensure_ascii=False)
                self.detail_editor.setPlainText(formatted_json)
                self.logger.info(f"[调试] 成功加载并显示{component_type}组件配置，内容长度: {len(formatted_json)}字节")
            else:
                self.detail_editor.setPlainText(f"未发现{component_type}相关配置")
                self.logger.warning(f"[调试] 未找到{component_type}组件相关配置")
                
        except Exception as e:
            self.detail_editor.setPlainText(f"加载组件配置失败: {e}")
            self.logger.error(f"加载组件配置失败: {e}")
    
    def _extract_tool_paths(self, agent_config: Dict) -> Dict[str, str]:
        """从agent配置中提取工具配置文件路径"""
        tool_paths = {}
        
        # 检查capabilities.tools字段
        if 'capabilities' in agent_config and 'tools' in agent_config['capabilities']:
            tools_config = agent_config['capabilities']['tools']
            
            # 遍历工具配置
            for tool_name, tool_info in tools_config.items():
                if isinstance(tool_info, dict) and 'config_path' in tool_info:
                    # 获取工具配置路径
                    config_path = tool_info['config_path']
                    
                    # 处理相对路径和绝对路径
                    if not os.path.isabs(config_path):
                        # 相对路径，假设是相对于config/tools
                        base_dir = Path(__file__).resolve().parent.parent.parent.parent
                        config_path = os.path.join(base_dir, 'config', 'tools', config_path)
                    
                    # 检查文件是否存在
                    if os.path.exists(config_path):
                        tool_paths[tool_name] = config_path
        
        return tool_paths
