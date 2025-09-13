from __future__ import annotations

from typing import Optional, Callable

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QScrollArea,
    QFrame,
)
from PySide6.QtGui import QIcon


class CollapsiblePanel(QWidget):
    """通用折叠面板组件

    功能：
    - 标题区：标题文本、可选“新增”按钮、可选“复制”按钮、点击标题/箭头可展开/折叠。
    - 内容区：嵌入任意 QWidget，外包一层 QScrollArea；支持设置最大高度阈值，超出出现内部滚动。
    - 自适应：展开时按内容高度，但不超过 max_content_height；收起时仅显示标题区。
    - 信号：toggled(bool)、addClicked()、copyClicked()。
    
    注意：不改变传入内容部件的父子层级外的行为，作为容器使用。
    """

    toggled = Signal(bool)
    addClicked = Signal()
    copyClicked = Signal()

    def __init__(
        self,
        title: str = "",
        parent: Optional[QWidget] = None,
        *,
        show_add_button: bool = True,
        show_copy_button: bool = False,
        clickable_header: bool = True,
        max_content_height: int = 240,
        start_collapsed: bool = False,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._content_widget: Optional[QWidget] = None
        self._max_content_height = max(120, int(max_content_height))
        self._collapsed = bool(start_collapsed)
        self._clickable_header = bool(clickable_header)
        self._show_add_button = bool(show_add_button)
        self._show_copy_button = bool(show_copy_button)

        self._build_ui()
        self._apply_collapsed_state(initial=True)

    # region UI
    def _build_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 6)
        root.setSpacing(4)

        # 头部：箭头 + 标题 + 占位 + Add
        header = QWidget(self)
        header_lyt = QHBoxLayout(header)
        header_lyt.setContentsMargins(6, 2, 6, 2)
        header_lyt.setSpacing(6)

        self.btn_toggle = QToolButton(header)
        self.btn_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(not self._collapsed)
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)

        self.lbl_title = QLabel(self._title, header)
        font = self.lbl_title.font()
        font.setBold(True)
        self.lbl_title.setFont(font)

        self.btn_add = QPushButton("新增", header)
        self.btn_add.setVisible(self._show_add_button)
        self.btn_add.clicked.connect(self.addClicked.emit)
        
        # 复制按钮
        self.btn_copy = QPushButton("复制", header)
        self.btn_copy.setVisible(self._show_copy_button)
        self.btn_copy.clicked.connect(self.copyClicked.emit)
        self.btn_copy.setToolTip("复制内容到剪贴板")

        header_lyt.addWidget(self.btn_toggle, 0)
        header_lyt.addWidget(self.lbl_title, 1)
        header_lyt.addStretch(1)
        if self._show_copy_button:
            header_lyt.addWidget(self.btn_copy, 0)
        header_lyt.addWidget(self.btn_add, 0)

        # 点击标题也可切换
        if self._clickable_header:
            header.mousePressEvent = self._wrap_header_click(header.mousePressEvent)
            self.lbl_title.mousePressEvent = self._wrap_header_click(self.lbl_title.mousePressEvent)

        # 内容滚动区
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMaximumHeight(self._max_content_height)

        root.addWidget(header)
        root.addWidget(self.scroll)

        self._header = header
        self._root = root

    # endregion

    # region API
    def setTitle(self, title: str) -> None:
        self._title = title or ""
        self.lbl_title.setText(self._title)
        
    def showCopyButton(self, show: bool) -> None:
        """显示或隐藏复制按钮"""
        self._show_copy_button = bool(show)
        if hasattr(self, 'btn_copy'):
            self.btn_copy.setVisible(self._show_copy_button)
            
    def showAddButton(self, show: bool) -> None:
        """显示或隐藏新增按钮"""
        self._show_add_button = bool(show)
        if hasattr(self, 'btn_add'):
            self.btn_add.setVisible(self._show_add_button)

    def contentWidget(self) -> Optional[QWidget]:
        return self._content_widget

    def setContentWidget(self, widget: Optional[QWidget]) -> None:
        """设置面板内容部件。传入 None 将清空。
        注意：该部件会被设置为 scroll 的子部件。
        """
        self._content_widget = widget
        self.scroll.setWidget(widget)
        self._update_heights()

    def setMaxContentHeight(self, h: int) -> None:
        self._max_content_height = max(120, int(h))
        self.scroll.setMaximumHeight(self._max_content_height)
        self._update_heights()

    def isCollapsed(self) -> bool:
        return self._collapsed

    def expand(self) -> None:
        if self._collapsed:
            self._collapsed = False
            self.btn_toggle.setChecked(True)
            self._apply_collapsed_state()

    def collapse(self) -> None:
        if not self._collapsed:
            self._collapsed = True
            self.btn_toggle.setChecked(False)
            self._apply_collapsed_state()

    def setCollapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.btn_toggle.setChecked(not self._collapsed)
        self._apply_collapsed_state()

    # endregion

    # region Internals
    def _wrap_header_click(self, orig_handler: Optional[Callable]):
        def _handler(event):
            self._toggle()
            if callable(orig_handler):
                orig_handler(event)
        return _handler

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply_collapsed_state()
        self.toggled.emit(not self._collapsed)

    def _on_toggle_clicked(self):
        self._toggle()

    def _apply_collapsed_state(self, initial: bool = False) -> None:
        # 箭头方向：展开=向下；折叠=向右
        self.btn_toggle.setArrowType(
            Qt.ArrowType.DownArrow if not self._collapsed else Qt.ArrowType.RightArrow
        )
        self.scroll.setVisible(not self._collapsed)
        self._update_heights()
        # 初始阶段不触发信号
        if not initial:
            self.toggled.emit(not self._collapsed)

    def _update_heights(self) -> None:
        # 根据内容自适应高度，但不超过最大值
        if self._collapsed:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            return
        content = self._content_widget
        if content is None:
            self.scroll.setMaximumHeight(0)
            return
        # 估算内容高度
        content.adjustSize()
        h = content.sizeHint().height()
        h = min(max(0, h), self._max_content_height)
        self.scroll.setMaximumHeight(h)

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        if self._collapsed or self._content_widget is None:
            return QSize(base.width(), 36)
        h = min(self._content_widget.sizeHint().height(), self._max_content_height)
        return QSize(base.width(), 36 + h)
    # endregion
