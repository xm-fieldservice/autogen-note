# -*- coding: utf-8 -*-
"""
配置服务层：改为仅从本地 config/ JSON 文件读取，彻底移除数据库依赖。

符合“原始配置为最高权限”的设计：
- 运行与加载直接使用 `config/` 下 JSON，禁止隐式转换与回写。
- UI 仅展示与显式保存时写回。
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional
import json
import os
from pathlib import Path


class ConfigService:
    def __init__(self) -> None:
        # 计算项目根目录（services/ 的上上级）
        self.root: Path = Path(__file__).resolve().parents[1]
        self.config_dir: Path = self.root / "config"

    # —— 初始化占位：确保必要目录存在 ——
    def init_local_config(self) -> None:
        try:
            for sub in [
                self.config_dir,
                self.config_dir / "models",
                self.config_dir / "agents",
                self.config_dir / "tools",
                self.config_dir / "mcp",
                self.root / "logs",
                self.root / "data",
                self.root / "out",
            ]:
                sub.mkdir(parents=True, exist_ok=True)
        except Exception:
            # 目录创建失败不阻塞启动，由调用方记录日志
            pass

    # —— 文件读取辅助 ——
    def _read_json_file(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return default
        return default

    def _read_json_glob(self, folder: Path) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not folder.exists():
            return items
        for p in sorted(folder.glob("*.json")):
            try:
                with p.open("r", encoding="utf-8") as f:
                    obj = json.load(f)
                    if isinstance(obj, dict):
                        items.append(obj)
            except Exception:
                continue
        return items

    # —— 列表接口（UI 可直接调用） ——
    def list_models(self) -> Iterable[Dict[str, Any]]:
        return self._read_json_glob(self.config_dir / "models")

    def list_agents(self) -> Iterable[Dict[str, Any]]:
        return self._read_json_glob(self.config_dir / "agents")

    def list_tools(self) -> Iterable[Dict[str, Any]]:
        registry = self._read_json_file(self.config_dir / "tools" / "tools_registry.json", {"schema": 1, "tools": []})
        # 保持原始结构，不做展开/迁移
        return registry.get("tools", []) if isinstance(registry, dict) else []

    def list_mcp(self) -> Iterable[Dict[str, Any]]:
        servers = self._read_json_file(self.config_dir / "mcp" / "servers.json", {"schema": 1, "servers": []})
        return servers.get("servers", []) if isinstance(servers, dict) else []

    def list_vectorstores(self) -> Iterable[Dict[str, Any]]:
        # 优先读取向量库注册表（如存在）；若无，则返回空列表
        registry_path = self.config_dir / "vectorstores" / "registry.json"
        registry = self._read_json_file(registry_path, {"schema": 1, "vectorstores": []})
        return registry.get("vectorstores", []) if isinstance(registry, dict) else []

    def list_teams(self) -> Iterable[Dict[str, Any]]:
        # 目前没有 teams 配置目录，返回空列表以兼容 UI
        return []

    # —— 环境变量装载（已废弃，统一使用 app_new.py 内置机制） ——
    def load_env_into_process(self, overwrite: bool = False) -> Dict[str, Optional[str]]:
        """已废弃：环境变量统一由 app_new.py 的 EMBEDDED_ENV 加载"""
        return {}
