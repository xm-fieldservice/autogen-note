# Q-项目管理需求规范 v0

## 1. 项目背景与目标

### 1.1 背景概述
当前系统需要一个集中式的项目管理页面，使用Qt技术栈实现，基于QTreeWidget构建核心交互界面，为配置管理和项目编排提供统一入口。

### 1.2 设计目标
- 提供直观、高效的项目资源管理界面
- 实现节点树的灵活编辑与组织
- 支持多维度的过滤、标签和分类
- 可视化项目组件间的关系图谱
- 保持与现有代码的高度兼容性
- 符合"前端外皮"原则，不改写原始配置

## 2. 设计原则与合规要求

### 2.1 前端外皮原则
- UI变更不得隐式修改原始配置文件
- 所有配置变更必须通过显式保存触发，生成补丁后写入文件
- 严格遵循"选中即查看，编辑后点保存才写入"逻辑

### 2.2 合规与审计规则
- 所有关键操作通过`utils/logger_sink.py`记录，满足角色白名单/去重节流要求
- 符合Autogen 0.7.1框架规范
- Windows平台遵循PowerShell命令规范

### 2.3 UI状态管理
- 页面状态（显示列、分割尺寸、过滤器）通过QSettings或SQLite持久化
- 不污染config/*.json配置文件
- 使用UserRole携带元数据（路径、角色、索引）

## 3. 页面架构与布局

### 3.1 整体架构
- 实现为`ProjectPage(QWidget)`类，可作为主窗口标签页集成
- 采用五列布局设计，由QSplitter分隔，支持拖拽调整宽度
- 顶部工具栏包含五个控制按钮，控制各列的显示/隐藏

### 3.2 列布局详细设计
1. **资源列** - 左侧第一列
   - 显示项目配置文件树
   - 支持选择多个文件进行操作
   - 提供文件级别过滤器

2. **节点树列** - 主体第二列 (QTreeWidget)
   - 核心编辑区域
   - 树状结构展示配置节点
   - 支持拖拽、右键菜单等丰富操作

3. **过滤/泳道列** - 中间第三列
   - 看板式分类视图
   - 支持自定义标签与分组
   - 提供拖拽节点到泳道功能

4. **关系图列** - 第四列 (QGraphicsView/Scene)
   - 可视化节点间关系
   - 支持缩放、平移、选择
   - 与树视图双向联动

5. **详情列** - 右侧第五列
   - 可编辑详情视图
   - 显示当前选中节点的详细属性
        - MD阅读器
        - 标题框
        - 内容框
        -四个按键：内容框的全屏，内容框内容的复制，粘贴；给节点添加附件
   - 全屏的内容框是一个MD编辑器；

## 4. 功能需求清单

### 4.1 节点树及其操作功能
- **拖拽复制与移动**
   - 支持节点间拖放
   - Ctrl+拖动实现复制，直接拖动实现移动
   - 不同类型间的拖放有限制性规则

- **节点创建**
   - 右键菜单创建新节点
   - 支持基于模板快速创建
   - 自动分配默认名称与ID

- **节点删除**
   - 支持单个/批量删除
   - 删除前确认对话框
   - 权限检查与保护机制

- **节点过滤**
   - 支持多维度过滤条件
   - 快速搜索功能
   - 过滤结果高亮显示

- **标签功能**
   - 为节点添加自定义标签
   - 基于标签的分组与过滤
   - 标签颜色自定义

### 4.2 上下文菜单功能
- 右键菜单支持导出/导入节点
- 复制节点路径/ID/内容
- 节点移动、重命名、删除操作
- 批量操作支持

### 4.3 撤销/重做功能
- 使用QUndoStack实现操作历史
- 支持撤销/重做的操作包括：
  - 节点创建/删除
  - 节点移动/复制
  - 属性修改
  - 结构变更

### 4.4 剪贴板集成
- 支持复制/粘贴节点
- 跨应用文本复制
- JSON格式保留

### 4.5 权限保护
- 基于角色的访问控制
- 敏感操作检查
- 防止意外修改的保护机制

### 4.6 关系图谱功能
- **可视化展示**
  - 节点与关系的图形化表示
  - 支持不同布局算法：分层/径向布局

- **交互能力**
  - 缩放/平移
  - 节点选择与高亮
  - 与树视图双向联动

- **投射功能**
  - 支持图谱结果到树的投射
  - 提供高亮/筛选/临时分组三种模式
  - 一键清除投射恢复原始视图

### 4.7 泳道功能
- Kanban风格的任务管理
- 自定义泳道列与标签
- 拖拽节点在泳道间移动

## 5. 数据策略与持久化

### 5.1 数据源
- 直接使用现有配置文件
- 复用`config_explorer.py`的数据抽取函数
- 禁止隐式转换或归一化

### 5.2 UI状态存储
- 使用QSettings存储UI偏好
  - 工具栏按钮状态
  - 分割器尺寸
  - 过滤器设置
  - 展开的节点路径

- 可选SQLite持久化(data/app_config/config.sqlite3)
  - 用户标签定义
  - 自定义分组
  - 泳道配置

### 5.3 元数据存储
- 使用QTreeWidgetItem的UserRole存储
  - 原始路径
  - 节点角色
  - 索引或键路径
  - 引用类型标记

## 6. 图谱与泳道设计

### 6.1 图谱实现策略
- **Phase A (默认方案，无第三方依赖)**
  - 使用QGraphicsView+QGraphicsScene纯Qt实现
  - 关系直接来源于配置抽取函数
  - 内置分层/径向布局算法
  - 基础交互：缩放、平移、选择

- **Phase B (可选增强，布局优化)**
  - 引入networkx实现更自然的布局
  - 使用spring_layout/shell_layout算法
  - 保持懒加载，不破坏现有打包

- **Phase C (可选增强，图分析)**
  - 引入Neo4j支持高级查询与分析
  - 支持Cypher查询与图算法
  - 结果投射回UI，不反向写入配置

### 6.2 泳道设计
- 看板式UI，支持自定义泳道列
- 基于标签或状态的节点分类
- 拖放在泳道间移动时更新节点属性

### 6.3 投射机制设计
- **高亮模式**
  - 零侵入性，不隐藏任何节点
  - 图谱结果在树中高亮显示
  - 自动展开至可见

- **筛选模式**
  - 非结果节点隐藏
  - 保留祖先路径提供上下文
  - 一键还原完整视图

- **临时分组模式**
  - 创建虚拟"投影视图"分组
  - 结果以引用方式聚合显示
  - 不落盘，关闭即删除

## 7. 现有代码复用与集成

### 7.1 复用点
- 复用`config_explorer.py`的树构建逻辑
- 复用现有的详情加载与渲染函数
- 复用`utils/logger_sink.py`进行日志审计

### 7.2 集成接口
- 实现`ProjectPage`类作为独立模块
- 提供标准接口与主窗口集成
- 事件信号设计与全局状态同步

### 7.3 可选组件集成
- jsmind只读思维导图(可选)
- networkx布局优化(可选)
- Neo4j查询与分析(可选)

## 8. 验收标准与里程碑

### 8.1 验收标准
- 符合"前端外皮"原则，不隐式修改配置
- 支持全部核心节点操作功能
- UI响应及操作流畅
- 数据一致性保证
- 日志审计合规

### 8.2 里程碑规划
1. **MVP阶段** - 5人天
   - 五列基础布局
   - QTreeWidget与详情联动
   - 基础右键菜单框架
   - UI状态保存与恢复

2. **核心功能阶段** - 8人天
   - 节点完整操作支持
   - 拖放与剪贴板功能
   - 撤销/重做堆栈
   - 权限保护机制

3. **关系图谱阶段** - 5人天
   - 基础图谱实现(Phase A)
   - 树-图双向联动
   - 投射机制(高亮模式)

4. **增强功能阶段** - 7人天
   - 泳道功能完善
   - 筛选与临时分组投射
   - 可选networkx集成
   - 性能优化

## 9. 风险评估与缓解策略

### 9.1 已识别风险
- **性能风险**: 节点数量巨大时的加载与渲染性能
  - **缓解**: 懒加载、虚拟化列表、分页技术

- **复杂度风险**: QTreeWidget与图谱的双向联动复杂度
  - **缓解**: 明确的UID映射机制，松耦合设计

- **兼容性风险**: 与现有代码的集成冲突
  - **缓解**: 严格遵循前端外皮原则，避免侵入式修改

### 9.2 技术债务
- 初始实现可能缺乏部分高级功能
- 布局算法可能需后续优化
- 大规模数据下的性能待测试验证

## 10. CI/CD与测试策略

### 10.1 CI/CD配置
- 确保项目符合自动构建要求
- 添加必要的单元测试
- 集成测试覆盖核心功能流程

### 10.2 测试重点
- 节点操作正确性测试
- UI交互与响应测试
- 数据一致性验证
- 性能与负载测试

## 11. 待确认事项

1. 顶部工具栏按钮是独立切换还是互斥单选
2. 资源列、过滤列、关系列的默认内容与命名
3. 泳道标签约定与默认列(如待办、进行中、完成)
4. 默认图谱范围(当前文件子树或全局)与过滤方式
5. Neo4j查询结果投射的默认模式(高亮或过滤)
6. 投射虚拟分组节点的命名与放置位置
7. 是否添加Neo4j依赖与UI支持


---



# Project页面模块化开发计划

## 一、基础架构设计（3天）

### 1. 文件结构设计
```
app/
  ui/
    pages/
      project_page/
        __init__.py                # 导出模块
        project_page.py            # 主页面类
        components/
          resource_panel.py        # 资源列组件
          tree_widget_panel.py     # 节点树列组件
          filter_panel.py          # 过滤/泳道列组件
          graph_panel.py           # 关系图列组件
          detail_panel.py          # 详情列组件
        models/
          node_model.py            # 节点数据模型
          projection_model.py      # 投射模型
        utils/
          undo_commands.py         # 撤销/重做命令
          tree_helpers.py          # 树操作辅助函数
          graph_layout.py          # 图布局算法
```

### 2. 核心类设计
- `ProjectPage(QWidget)`: 主容器，管理分割器与子面板
- `ResourcePanel(QWidget)`: 文件资源树面板
- `TreeWidgetPanel(QWidget)`: 主节点树面板
- `FilterPanel(QWidget)`: 过滤与泳道面板
- `GraphPanel(QWidget)`: 关系图谱面板
- `DetailPanel(QWidget)`: 节点详情面板

### 3. 全局状态管理
- `ProjectPageState`: 管理页面状态与持久化
- `SignalHub`: 处理组件间通信与事件传递

## 二、与主程序集成（2天）

### 1. 主程序接口设计
```python
# 在app/main.py中添加页面注册
def register_pages(self):
    # 现有代码...
    from app.ui.pages.project_page import ProjectPage
    self.project_page = ProjectPage(self)
    self.add_page("项目管理", self.project_page)
    # 保留现有其他页面...
```

### 2. 信号与事件连接
- 定义清晰的对外接口与事件
- 确保页面可以作为独立组件载入和卸载
- 实现资源共享但状态隔离的机制

### 3. 配置文件与权限接入
- 复用现有的配置加载与验证逻辑
- 对接现有的权限系统
- 共享日志审计机制

## 三、功能开发阶段

### 阶段一：基础框架实现（5天）
1. **构建基础UI结构**
   - 实现五列布局与分割器
   - 添加顶部工具栏按钮
   - 设计组件间初始通信机制

2. **基础节点树实现**
   - 创建QTreeWidget基类
   - 实现基本树节点加载与显示
   - 建立节点与详情面板的联动

3. **UI状态持久化**
   - 实现分割器大小保存
   - 保存列显示状态
   - 记住已展开节点状态

### 阶段二：核心功能实现（7天）
1. **节点操作功能**
   - 拖拽复制与移动实现
   - 右键菜单功能
   - 节点创建与删除

2. **撤销/重做系统**
   - 实现QUndoStack操作记录
   - 编写各类操作命令
   - 与全局撤销/重做按钮集成

3. **节点过滤与搜索**
   - 实现多维度过滤器
   - 添加快速搜索功能
   - 支持过滤条件组合

4. **标签与分类功能**
   - 实现节点标签系统
   - 创建基于标签的分组
   - 设计标签颜色管理

### 阶段三：图谱功能实现（6天）
1. **基础图谱实现**
   - 创建QGraphicsScene/View框架
   - 实现节点与连接线绘制
   - 添加基本交互（缩放、平移）

2. **图谱数据源接入**
   - 复用config_explorer数据抽取函数
   - 构建关系模型
   - 实现内置布局算法

3. **树与图的双向联动**
   - 实现UID映射机制
   - 添加图谱选择→树高亮功能
   - 添加树选择→图谱定位功能

4. **投射功能实现**
   - 实现高亮投射模式
   - 添加筛选投射模式
   - 创建临时分组投射模式

### 阶段四：详情与泳道功能（5天）
1. **详情面板功能**
   - 实现可编辑详情视图
   - 添加MD阅读/编辑器
   - 实现附件功能

2. **泳道功能开发**
   - 创建看板式分类视图
   - 实现泳道列自定义
   - 添加节点拖放功能

3. **功能集成与调优**
   - 组件间通信优化
   - 性能调优
   - 内存管理优化

## 四、测试与优化（5天）

### 1. 单元测试
- 为核心类编写单元测试
- 测试数据一致性
- 验证事务与撤销功能

### 2. 集成测试
- 与主程序集成测试
- 跨组件交互测试
- 边界条件测试

### 3. 性能优化
- 大数据集加载优化
- 渲染性能调优
- 内存占用优化

### 4. 最终审查与发布
- 代码审查与规范检查
- 文档完善
- 发布准备

## 五、关键技术实现指引

### 1. 核心数据模型
```python
# app/ui/pages/project_page/models/node_model.py
class NodeItem:
    def __init__(self, uid, name, node_type, parent_uid=None):
        self.uid = uid  # 格式: "<abs_path>|<role>|<index_or_key_path>"
        self.name = name
        self.node_type = node_type
        self.parent_uid = parent_uid
        self.children =
        self.attributes = {}
        
    def add_child(self, child):
        self.children.append(child)
        
    def set_attribute(self, key, value):
        self.attributes[key] = value
```

### 2. 树节点与UID映射
```python
# app/ui/pages/project_page/components/tree_widget_panel.py
class TreeWidgetPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.uid_to_item = {}  # UID到QTreeWidgetItem的映射
        
    def create_tree_item(self, node_item):
        tree_item = QTreeWidgetItem([node_item.name])
        tree_item.setData(0, Qt.UserRole, node_item.uid)
        self.uid_to_item[node_item.uid] = tree_item
        return tree_item
        
    def highlight_items(self, uids):
        # 图谱→树的高亮投射
        self.tree.setUpdatesEnabled(False)
        for item in self.tree.findItems("", Qt.MatchContains | Qt.MatchRecursive):
            uid = item.data(0, Qt.UserRole)
            if uid in uids:
                item.setBackground(0, QColor(255, 255, 0, 100))
                self.ensure_item_visible(item)
            else:
                item.setBackground(0, QColor(0, 0, 0, 0))
        self.tree.setUpdatesEnabled(True)
```

### 3. 图谱基础实现
```python
# app/ui/pages/project_page/components/graph_panel.py
class GraphPanel(QWidget):
    node_clicked = Signal(str)  # 发射被点击节点的UID
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter::Antialiasing)
        
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        self.setLayout(layout)
        
        self.node_items = {}  # UID到图形项的映射
        
    def create_node(self, uid, label, node_type):
        node = NodeGraphicsItem(uid, label, node_type)
        self.scene.addItem(node)
        self.node_items[uid] = node
        node.clicked.connect(lambda: self.node_clicked.emit(uid))
        return node
        
    def create_edge(self, source_uid, target_uid):
        if source_uid in self.node_items and target_uid in self.node_items:
            edge = EdgeGraphicsItem(self.node_items[source_uid], 
                                   self.node_items[target_uid])
            self.scene.addItem(edge)
            return edge
        return None
```

## 六、风险管理

1. **接口冲突风险**
   - 实现前详细分析主程序API
   - 使用私有方法减少命名冲突
   - 添加前缀避免命名空间污染

2. **性能问题**
   - 采用懒加载策略
   - 实现虚拟化列表
   - 分批处理大数据集

3. **UI一致性**
   - 复用主程序样式系统
   - 保持与现有组件外观一致
   - 遵循相同的用户体验模式

## 七、上线准备

1. **文档与注释**
   - 添加详细的类与方法文档
   - 编写组件使用指南
   - 记录关键算法与设计决策

2. **用户培训材料**
   - 创建功能演示视频
   - 编写快速入门指南
   - 准备常见问题解答

3. **渐进式部署策略**
   - 先在开发环境启用
   - 然后在测试环境验证
   - 最后在生产环境推广

这个开发计划确保了Project页面作为一个独立模块进行开发，同时与主程序保持良好的集成性。通过明确的文件结构、接口设计和分阶段实现，可以最小化对现有代码的影响。


---

我将先快速检查现有主程序中的可复用组件与页面结构（如 `app/main.py`、`app/ui/pages/` 下已有页面与通用部件），以便给出准确的复用建议与“单独页面 vs. 合并到 Project 页面”的评估。随后给出结论与建议。

为准确评估可复用组件与页面结构，我将快速查看现有的 [app/ui/pages/config_explorer.py](cci:7://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:0:0-0:0)，识别其中可直接复用的数据抽取函数、通用UI部件和信号逻辑，以便提出复用清单与集成建议。

# 可复用组件清单（来自主程序）

- __配置解析/数据抽取（强复用）__
  - [app/ui/pages/config_explorer.py](cci:7://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:0:0-0:0) 内只读抽取函数：
    - [ConfigExplorerPage._analyze_agent_config()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:233:4-281:25)：判定 Agent 是否挂载 工具/MCP/向量库/模型。
    - [ConfigExplorerPage._extract_agent_component_names()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:396:4-473:19)：从 Agent 配置提取组件名（tools/mcp/vectorstores/model）。
    - [ConfigExplorerPage._extract_team_part_component_names()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:475:4-555:19)：从 Team participant.config 提取组件名。
  - 建议：将以上3个函数抽取到“纯函数”模块（如 `services/config_extractors.py` 或 `repositories/config_repository.py` 内），供 `ProjectPage` 与 [ConfigExplorerPage](cci:2://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:18:0-918:25) 共用，避免重复实现与UI耦合。

- __配置加载与路径管理（强复用）__
  - `services/config_service.py`：已有本地配置初始化、路径常量等，继续沿用。
  - `config/constants.py`：UI/路径/日志常量，继续沿用。

- __日志与错误处理（强复用）__
  - `utils/error_handler.ErrorHandler`：日志入口保持一致。
  - `utils/logger_sink.py`：审计网关（满足“角色白名单/去重节流/幂等”），在 Project 页面交互处统一调用。

- __UI基础部件（可复用）__
  - `QSplitter/QTreeWidget` 使用模式与事件处理范式，参考 [ConfigExplorerPage](cci:2://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:18:0-918:25) 的 `tree` 初始化与 `itemClicked` 信号连接。
  - `app/ui/widgets/collapsible_panel.py`（如需折叠面板/工具栏容器）。

- __现有树的结构与展开逻辑（选择性复用/改造）__
  - [ConfigExplorerPage._expand_component_details()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:283:4-382:34)、[_populate_agent_file_node()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:557:4-594:73)、[_populate_team_file_node()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:596:4-602:79)：
    - 这些函数与当前页面UI耦合较多（写入 `QTextEdit`、树节点文案），可抽取“数据部分”到共享模块，UI渲染交给 `ProjectPage` 自己的组件。

# 不建议直接复用的部分

- __右侧详情编辑器__：`ConfigExplorerPage.detail_editor` 是只读 `QTextEdit`。Project 需求为“可编辑详情+MD编辑器+附件按键”，建议新建 `DetailPanel`，与现有只读编辑器分离。
- __点击处理直写UI__：[_on_item_clicked()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:144:4-215:63) 里混杂了数据读取与UI渲染，建议在 Project 页面解耦为“数据-状态-渲染”三层。

# 页面组织方案评估

- __方案A：单独顶级页面（推荐）__
  - 形式：新增 `app/ui/pages/project_page/` 模块，注册为主窗口一个独立Tab（如“项目管理”）。
  - 优点：
    - 隔离风险，不影响现有 [ConfigExplorerPage](cci:2://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:18:0-918:25) 行为。
    - 自由实现五列布局（资源/树/过滤-泳道/图谱/详情），不受现有页面约束。
    - 后续引入图谱（`QGraphicsView/Scene`）、Kanban泳道、MD编辑器、附件功能不会影响其他页面。
    - 易于按“前端外皮原则”实现只读/显式保存写回。
  - 缺点：
    - 需要在 `MainWindow` 做一次性注册（最小改动）。
  - 适用：
    - 你的需求明确需要关系图谱、投射机制、可编辑详情、泳道等复杂交互，独立页面更合适。

- __方案B：嵌入现有 ConfigExplorer 页面（不推荐）__
  - 形式：在 [ConfigExplorerPage](cci:2://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:18:0-918:25) 内再加子分栏/子Tab，硬塞入树/关系图/泳道/编辑器。
  - 优点：
    - 入口少一个Tab。
  - 缺点：
    - 增加现有页面复杂度与耦合；后续维护困难。
    - 现有“只读浏览器”的设计初衷被打破，风险高。
  - 适用：
    - 仅做轻量增强、无复杂交互时才考虑。

- __方案C：ProjectPage 内部使用“二级Tab”（推荐做法的细化）__
  - 在独立的 `ProjectPage` 内部，将“树/图谱/泳道/详情”组织为“分割器+二级Tab”，既满足五列框架，也便于按需隐藏/切换。
  - 优点：
    - 交互清晰、扩展性好；对主程序零侵入。

# 结论与建议

- __结论__：采用“独立顶级页面”最稳妥。将可复用的数据抽取逻辑抽取为共享模块，`ProjectPage` 仅复用这些“纯函数/服务”，UI部分完全独立实现，避免影响现有页面。
- __建议路径__：
  1. 新建 `app/ui/pages/project_page/` 目录与模块骨架，不改动现有 [config_explorer.py](cci:7://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:0:0-0:0) 逻辑。
  2. 抽取以下函数为共享“纯函数”模块（例如 `services/config_extractors.py`）：
     - [_analyze_agent_config()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:233:4-281:25)、[_extract_agent_component_names()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:396:4-473:19)、[_extract_team_part_component_names()](cci:1://file:///d:/AI-Projects/desktop_app/app/ui/pages/config_explorer.py:475:4-555:19)
  3. `ProjectPage` 五列实现中：
     - 树→复用抽取函数构建与高亮/筛选逻辑
     - 图谱→Phase A 先用纯Qt布局；联动靠 UID 映射
     - 详情→新建MD阅读/编辑器、附件按钮，不动旧页面
     - 审计→统一走 `utils/logger_sink.py`
  4. 在 `MainWindow` 注册新页面入口（最小改动，不影响其他页面）。

# 最小改动清单（不会影响其他代码）

- __新增__：`app/ui/pages/project_page/`（独立模块）
- __抽取/新增__：`services/config_extractors.py`（或放入 `repositories/config_repository.py`，仅新增函数，不修改其他逻辑）
- __注册入口__：在 `MainWindow` 的页面注册处添加一行引入与 `add_page("项目管理", ProjectPage(...))`（不修改既有页面）

如认可以上方向，我可以先提交“共享抽取模块”的代码骨架与 `ProjectPage` 空壳（UI骨架+信号仓+状态持久化），确保完全独立、零影响地接入主程序。随后逐步实现树/图/泳道/详情。


---


