"""
DEPRECATED: 内部运行器已移除。

请使用外部脚本机制：services/server/external_runner.py
- 预处理：external_preprocess -> scripts/preprocess_agent_external.py
- 提交：external_submit     -> scripts/submit_team_external.py
"""
from __future__ import annotations

# 任何导入此模块的行为都直接失败，避免误用。
raise ImportError(
    "services.server.autogen_runner 已移除，请改用 services.server.external_runner（外部脚本机制）。"
)
from typing import Optional, Dict, Any, List
from pathlib import Path
import json
import os

from autogen_client.config_loader import load_agent_json, load_team_json
from .mcp_manager import get_manager as _get_mcp_manager
try:
    from autogen_client.autogen_backends import AutogenAgentBackend, AutogenTeamBackend  # type: ignore
except Exception:  # pragma: no cover
    AutogenAgentBackend = None  # type: ignore
    AutogenTeamBackend = None  # type: ignore

def _run_with_timeout(fn, *args, timeout: float = 12.0, **kwargs):
    """在后台线程执行函数，超时未返回则抛 TimeoutError。"""
    import threading, queue
    q: "queue.Queue[tuple[bool, object]]" = queue.Queue()
    def _worker():
        try:
            res = fn(*args, **kwargs)
            q.put((True, res))
        except Exception as e:
            q.put((False, e))
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        ok, val = q.get(timeout=timeout)
        if ok:
            return val
        raise val  # type: ignore
    except queue.Empty:
        raise TimeoutError(f"operation timed out after {timeout}s")


def _expand_env_placeholders(data):
    """浅递归展开 dict/list 中的 ${VAR} 占位符（仅用于运行态，避免改动只读 loader）。"""
    import os, re
    pat = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    def repl(s: str) -> str:
        def _r(m):
            return os.environ.get(m.group(1), "")
        return pat.sub(_r, s)
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if isinstance(v, str):
                out[k] = repl(v)
            else:
                out[k] = _expand_env_placeholders(v)
        return out
    if isinstance(data, list):
        return [_expand_env_placeholders(x) for x in data]
    if isinstance(data, str):
        return repl(data)
    return data


def _safe_read(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    try:
        # 仅解析与规范化，不执行
        if p.name.lower().endswith("team.json") or 'team' in p.stem.lower():
            return load_team_json(str(p))
        return load_agent_json(str(p))
    except Exception:
        return None


def preprocess_with_agent(topic_id: str, raw_md: str, mode: str, agent_config_path: Optional[str]) -> str:
    """调用“整理 Agent/Team”进行预处理，并在文末追加可见标记：
    - 成功：> 预处理 · Agent：{name}（{model}）
    - 占位：> 预处理 · 本地占位（未启用Agent）
    """
    cfg = _safe_read(agent_config_path)
    # 预加载 MCP servers（准备后续接入）
    _prepare_mcp_servers()

    agent_name = None
    model_name = None
    if isinstance(cfg, dict):
        agent_name = cfg.get("name") or "Agent"
        try:
            model_name = (
                (cfg.get("model_client") or {}).get("config", {}).get("model")
            )
        except Exception:
            model_name = None

    processed = False
    processed_mode = ""
    output = raw_md or ""
    if cfg and AutogenAgentBackend is not None:
        try:
            # 运行前展开环境变量占位符（尤其是 api_key）
            cfg_expanded = dict(cfg)
            mc = cfg_expanded.get("model_client") or {}
            if isinstance(mc, dict):
                mc_cfg = mc.get("config") or {}
                if isinstance(mc_cfg, dict):
                    mc["config"] = _expand_env_placeholders(mc_cfg)
                    cfg_expanded["model_client"] = mc
            backend = AutogenAgentBackend(cfg_expanded)
            # 为后端调用增加超时保护（12s）
            output = str(_run_with_timeout(backend.infer_once, raw_md or "", timeout=12.0))
            processed = True
            processed_mode = "autogen"
        except Exception as e:
            processed = False
            output = raw_md or ""
            # 后端错误信息将不在此处写入，统一在直连兜底与标记中给出诊断

    # 兜底：若仍未处理，尝试按 openai 风格直连 /chat/completions
    direct_err = ""
    direct_missing = ""
    if not processed and isinstance(cfg, dict):
        try:
            mc = (cfg.get("model_client") or {}).get("config", {})
            mc = _expand_env_placeholders(mc)
            api_key = str(mc.get("api_key") or "").strip()
            base_url = str(mc.get("base_url") or "").rstrip("/")
            model_id = str(mc.get("model") or "").strip()
            # 直连请求采用保护超时（取配置与60秒中的较小值）
            try:
                cfg_timeout = float(mc.get("timeout") or 30)
            except Exception:
                cfg_timeout = 30.0
            timeout = min(cfg_timeout, 60.0)
            if api_key and base_url and model_id:
                import json as _json
                from urllib import request as _req
                # 预处理场景控制生成长度，避免模型长时间生成导致读超时
                max_tokens = mc.get("max_tokens", 512)
                try:
                    max_tokens = int(max_tokens)
                except Exception:
                    max_tokens = 512
                max_tokens = min(max_tokens, 512)
                payload = {
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": str(cfg.get("system_message") or "You are a helpful assistant.")},
                        {"role": "user", "content": raw_md or ""},
                    ],
                    # 为避免长推理，收敛温度
                    "temperature": 0.2,
                    "top_p": mc.get("top_p", 0.9),
                    "max_tokens": max_tokens,
                }
                # DeepSeek reasoner 优化：降低思考强度
                try:
                    if "reasoner" in (model_id or "").lower():
                        payload["reasoning"] = {"effort": "low"}
                except Exception:
                    pass
                url = f"{base_url}/chat/completions"
                data = _json.dumps(payload).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }
                req = _req.Request(url, data=data, headers=headers, method="POST")
                try:
                    with _req.urlopen(req, timeout=timeout) as resp:
                        raw = resp.read().decode("utf-8", errors="ignore")
                except Exception as e:
                    try:
                        # 提取 HTTPError 的 body
                        from urllib.error import HTTPError
                        if isinstance(e, HTTPError):
                            raw_err = e.read().decode("utf-8", errors="ignore")
                            direct_err = f"HTTP {e.code}: {raw_err[:200]}"
                        else:
                            direct_err = str(e)
                    except Exception:
                        direct_err = str(e)
                    raise
                obj = _json.loads(raw)
                # 兼容 OpenAI 风格
                choices = obj.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or ""
                    if content:
                        output = str(content)
                        processed = True
                        processed_mode = "direct"
            else:
                missing = []
                if not model_id:
                    missing.append("model")
                if not base_url:
                    missing.append("base_url")
                if not api_key:
                    missing.append("api_key")
                direct_missing = ",".join(missing)
        except Exception:
            # 失败时保留 direct_err 供标记展示
            pass

    # 统一附加可见标记（置于文末，不干扰主结构）
    if processed:
        if processed_mode == "direct":
            marker = f"> 预处理 · Agent(直连)：{agent_name or 'Unknown'}（{model_name or 'unknown-model'}）"
        else:
            marker = f"> 预处理 · Agent：{agent_name or 'Unknown'}（{model_name or 'unknown-model'}）"
    else:
        if direct_err:
            marker = f"> 预处理 · 本地占位（未启用Agent，直连失败：{direct_err}）"
        elif direct_missing:
            marker = f"> 预处理 · 本地占位（未启用Agent，直连缺少字段：{direct_missing}）"
        else:
            # 追加诊断：cfg 是否加载、关键字段是否识别
            try:
                _cfg_ok = isinstance(cfg, dict)
                _mc = (_expand_env_placeholders((cfg or {}).get("model_client", {}).get("config", {})) if _cfg_ok else {})
                _model_ok = bool(str(_mc.get("model") or "").strip())
                _base_ok = bool(str(_mc.get("base_url") or "").strip())
                _key_ok = bool(str(_mc.get("api_key") or "").strip())
                marker = "> 预处理 · 本地占位（未启用Agent；diag: cfg=%s, model=%s, base_url=%s, api_key=%s)" % (
                    "ok" if _cfg_ok else "none",
                    "ok" if _model_ok else "missing",
                    "ok" if _base_ok else "missing",
                    "set" if _key_ok else "missing",
                )
            except Exception:
                marker = "> 预处理 · 本地占位（未启用Agent）"
    # 避免重复附加：若输出末尾已有同类标记则不再追加
    out_stripped = (output or "").rstrip()
    if not out_stripped.endswith(marker):
        output = f"{out_stripped}\n\n{marker}\n"
    return output


def submit_with_team(topic_id: str, final_md: str, mode: str, team_config_path: Optional[str]) -> str:
    """调用 Team 执行：
    - 当前阶段：加载配置以校验路径；qa 模式附加占位回答，其它模式原样返回；
    - 下一阶段：基于配置装配 Autogen Team + MCP servers 执行实际检索/问答。
    """
    cfg = _safe_read(team_config_path)
    _prepare_mcp_servers()
    if cfg and AutogenTeamBackend is not None:
        try:
            task = final_md or ""
            backend = AutogenTeamBackend(cfg)
            return str(backend.infer_rounds(task))
        except Exception:
            pass
    # 回退占位
    if (mode or "").lower() == "qa":
        return f"{final_md}\n\n> [占位查询结果]"
    return final_md or ""


# ---------- MCP servers preparation (placeholder) ----------
_MCP_READY = False

def _prepare_mcp_servers() -> None:
    """读取 config/mcp/servers.json 作为准备步骤。
    真实接入时，这里注册 MCP servers 到 Autogen 框架。
    """
    global _MCP_READY
    if _MCP_READY:
        return
    try:
        root = Path(__file__).resolve().parents[2]
        mcp_config = root / "config" / "mcp" / "servers.json"
        if mcp_config.exists():
            _ = json.loads(mcp_config.read_text(encoding="utf-8"))
        # 实际注册（占位返回数量）
        try:
            mgr = _get_mcp_manager()
            _ = mgr.register_into_runtime()
        except Exception:
            pass
        _MCP_READY = True
    except Exception:
        # 不中断主流程
        _MCP_READY = False
