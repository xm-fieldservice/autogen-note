# -*- coding: utf-8 -*-
"""
纯函数：配置抽取与分析（只读）。
- 遵循“前端外皮”原则：仅读取与分析，不产生任何写入/归一化。
- 供 ProjectPage 与 ConfigExplorerPage 等页面复用，避免UI耦合。

注意：
- 所有返回结构保持简单可序列化。
- 与 AutoGen 0.7.1 规范字段保持一致，不做隐式结构变换。
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Any, Tuple
import json


def analyze_agent_config(file_path: Path) -> Dict[str, bool]:
    """判定 Agent 是否挂载 组件（tools/mcp/vectorstores/model）。
    返回：{"tools": bool, "mcp": bool, "vectorstores": bool, "model": bool}
    """
    components = {"tools": False, "mcp": False, "vectorstores": False, "model": False}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            # tools
            if isinstance(data.get('tools'), list) and len(data['tools']) > 0:
                components['tools'] = True
            # mcp（可能位于 capabilities 或独立字段，保持宽松判定）
            caps = data.get('capabilities')
            if isinstance(caps, list) and any(isinstance(c, dict) and c.get('type') == 'mcp' for c in caps):
                components['mcp'] = True
            if isinstance(data.get('mcp'), list) and len(data['mcp']) > 0:
                components['mcp'] = True
            # vectorstores / memory（AutoGen 0.7.1 memory 列表）
            mem = data.get('memory')
            if isinstance(mem, list) and len(mem) > 0:
                components['vectorstores'] = True
            # model
            mc = data.get('model_client')
            if isinstance(mc, dict) and (mc.get('provider') or mc.get('config')):
                components['model'] = True
    except Exception:
        # 静默失败，返回默认 False
        pass
    return components


def extract_agent_component_names(file_path: Path) -> Dict[str, List[str]]:
    """从 Agent 配置提取组件名称集合。
    返回：{"tools": [...], "mcp": [...], "vectorstores": [...], "model": [<provider/model>]}（若无则空表）
    """
    result = {"tools": [], "mcp": [], "vectorstores": [], "model": []}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return result
        # tools
        tools = data.get('tools')
        if isinstance(tools, list):
            for t in tools:
                if isinstance(t, dict):
                    name = t.get('id') or t.get('name') or t.get('type')
                    if name:
                        result['tools'].append(str(name))
                elif isinstance(t, str):
                    result['tools'].append(t)
        # mcp
        caps = data.get('capabilities')
        if isinstance(caps, list):
            for c in caps:
                if isinstance(c, dict) and c.get('type') == 'mcp':
                    n = c.get('name') or c.get('id')
                    if n:
                        result['mcp'].append(str(n))
        mcp_list = data.get('mcp')
        if isinstance(mcp_list, list):
            for m in mcp_list:
                if isinstance(m, (str,)):
                    result['mcp'].append(m)
                elif isinstance(m, dict):
                    n = m.get('name') or m.get('id')
                    if n:
                        result['mcp'].append(str(n))
        # vectorstores / memory
        mem = data.get('memory')
        if isinstance(mem, list):
            for v in mem:
                if isinstance(v, dict):
                    n = v.get('name') or v.get('collection_name') or v.get('vendor')
                    if n:
                        result['vectorstores'].append(str(n))
        # model
        mc = data.get('model_client')
        if isinstance(mc, dict):
            prov = mc.get('provider')
            cfg = mc.get('config')
            model = None
            if isinstance(cfg, dict):
                model = cfg.get('name') or cfg.get('model')
            if prov:
                result['model'].append(str(prov))
            if model:
                result['model'].append(str(model))
    except Exception:
        pass
    return result


def extract_team_part_component_names(file_path: Path) -> Dict[str, List[str]]:
    """从 Team 配置中提取参与者（participants）所引用的组件名集合。
    返回：{"agents": [...], "tools": [...], "mcp": [...], "vectorstores": [...], "models": [...]}。
    """
    result = {"agents": [], "tools": [], "mcp": [], "vectorstores": [], "models": []}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return result
        parts = data.get('participants')
        if isinstance(parts, list):
            for p in parts:
                if not isinstance(p, dict):
                    continue
                # agent 名称
                name = p.get('name') or p.get('id')
                if name:
                    result['agents'].append(str(name))
                # 工具/记忆/模型引用（最佳努力，字段名并不完全统一）
                tools = p.get('tools')
                if isinstance(tools, list):
                    for t in tools:
                        if isinstance(t, dict):
                            n = t.get('id') or t.get('name')
                            if n:
                                result['tools'].append(str(n))
                        elif isinstance(t, str):
                            result['tools'].append(t)
                mem = p.get('memory')
                if isinstance(mem, list):
                    for v in mem:
                        if isinstance(v, dict):
                            n = v.get('name') or v.get('collection_name')
                            if n:
                                result['vectorstores'].append(str(n))
                mc = p.get('model_client')
                if isinstance(mc, dict):
                    prov = mc.get('provider')
                    cfg = mc.get('config')
                    model = None
                    if isinstance(cfg, dict):
                        model = cfg.get('name') or cfg.get('model')
                    if prov:
                        result['models'].append(str(prov))
                    if model:
                        result['models'].append(str(model))
    except Exception:
        pass
    return result
