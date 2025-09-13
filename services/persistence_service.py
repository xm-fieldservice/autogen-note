# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import tempfile

from utils import logger_sink


@dataclass
class PersistResult:
    ok: bool
    error: Optional[str] = None


class PersistenceBus:
    """集中式持久化服务（最小可用版）。
    - 提供语义化接口，隐藏文件读/改/写细节
    - 原子写入（临时文件 + os.replace）
    - 字段级合并（仅更新传入的 fields）
    - 失败不抛异常，返回 PersistResult 并记录日志
    """

    def __init__(self) -> None:
        # 预留：去抖/批量合并可在此加入
        pass

    # —— 公共语义接口 ——
    def save_tree_expansion(self, file: Path, node_id: str, expanded: bool, *, session_id: Optional[str] = None, reason: str = "ui.expand") -> PersistResult:
        if not self._ensure_file(file):
            return PersistResult(False, "file_not_exists")
        root = self._read_json(file)
        if root is None:
            return PersistResult(False, "read_json_failed")
        if not self._update_node_in_json(root, node_id, {"expanded": bool(expanded)}):
            return PersistResult(False, "node_not_found")
        if not self._write_json_atomic(file, root):
            return PersistResult(False, "write_failed")
        try:
            logger_sink.log_user_message(session_id or "-", f"[PBUS] save_tree_expansion ok id={node_id} expanded={expanded} file={file}")
        except Exception:
            pass
        return PersistResult(True)

    def save_node_fields(self, file: Path, node_id: str, fields: Dict[str, Any], *, session_id: Optional[str] = None, reason: str = "ui.fields") -> PersistResult:
        if not isinstance(fields, dict) or not fields:
            return PersistResult(False, "empty_fields")
        if not self._ensure_file(file):
            return PersistResult(False, "file_not_exists")
        root = self._read_json(file)
        if root is None:
            return PersistResult(False, "read_json_failed")
        if not self._update_node_in_json(root, node_id, fields):
            return PersistResult(False, "node_not_found")
        if not self._write_json_atomic(file, root):
            return PersistResult(False, "write_failed")
        try:
            logger_sink.log_user_message(session_id or "-", f"[PBUS] save_node_fields ok id={node_id} fields={list(fields.keys())} file={file}")
        except Exception:
            pass
        return PersistResult(True)

    def save_swimlane_state(self, file: Path, state: Dict[str, List[Tuple[str, int]]], *, session_id: Optional[str] = None, reason: str = "ui.swimlane") -> PersistResult:
        if not self._ensure_file(file):
            return PersistResult(False, "file_not_exists")
        root = self._read_json(file)
        if root is None:
            return PersistResult(False, "read_json_failed")
        try:
            for key, arr in (state or {}).items():
                for nid, order in arr:
                    if not nid:
                        continue
                    self._update_node_in_json(root, nid, {"status": key, "kanban_order": int(order)})
        except Exception:
            return PersistResult(False, "state_apply_failed")
        if not self._write_json_atomic(file, root):
            return PersistResult(False, "write_failed")
        try:
            logger_sink.log_user_message(session_id or "-", f"[PBUS] save_swimlane_state ok file={file}")
        except Exception:
            pass
        return PersistResult(True)

    def save_full_tree(self, file: Path, children: List[Dict[str, Any]], *, session_id: Optional[str] = None, reason: str = "ui.full_save") -> PersistResult:
        """以原子方式保存整棵树结构：
        - 读取现有 JSON 根对象；
        - 用传入的 children 替换根的 children 字段（保留其它顶层字段，如 id/topic 等）；
        - 原子写回。
        """
        if not self._ensure_file(file):
            return PersistResult(False, "file_not_exists")
        root = self._read_json(file)
        if root is None:
            return PersistResult(False, "read_json_failed")
        try:
            if not isinstance(children, list):
                return PersistResult(False, "invalid_children")
            # 统一取得根节点对象
            root_node = root[0] if isinstance(root, list) and root else root
            if not isinstance(root_node, dict):
                return PersistResult(False, "invalid_root")
            root_node["children"] = children
        except Exception:
            return PersistResult(False, "apply_failed")
        if not self._write_json_atomic(file, root):
            return PersistResult(False, "write_failed")
        try:
            logger_sink.log_user_message(session_id or "-", f"[PBUS] save_full_tree ok file={file} children_count={len(children)}")
        except Exception:
            pass
        return PersistResult(True)

    # —— 内部：通用读/写/更新 ——
    def _ensure_file(self, file: Path) -> bool:
        try:
            p = Path(file)
            return p.exists() and p.is_file()
        except Exception:
            return False

    def _read_json(self, path: Path) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_json_atomic(self, path: Path, data: Any) -> bool:
        try:
            dir_path = Path(path).parent
            fd, tmp_path = tempfile.mkstemp(prefix=Path(path).stem + "_", suffix=".tmp", dir=str(dir_path))
            os.close(fd)
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
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

    def _update_node_in_json(self, node: Any, node_id: str, updates: Dict[str, Any]) -> bool:
        try:
            if isinstance(node, dict):
                if node.get("id") == node_id:
                    for k, v in updates.items():
                        node[k] = v
                    return True
                ch = node.get("children")
                if isinstance(ch, list):
                    for c in ch:
                        if self._update_node_in_json(c, node_id, updates):
                            return True
            elif isinstance(node, list):
                for c in node:
                    if self._update_node_in_json(c, node_id, updates):
                        return True
        except Exception:
            return False
        return False
