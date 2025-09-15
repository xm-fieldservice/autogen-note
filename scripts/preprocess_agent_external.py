#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
预处理 Agent 外部脚本（STDIN -> Markdown）
- 严格使用 Autogen 内生机制（优先），失败时直连兜底 /chat/completions（OpenAI 兼容）
- 输入：从 STDIN 读取原始 Markdown；命令行参数传递 agent 配置/超时等
- 输出：将最终 Markdown 打印到 STDOUT，末尾追加标记行

退出码：
- 0 成功；1 参数错误；2 超时；3 HTTP/鉴权错误；4 其他异常
用法示例：
  echo "测试预处理：000000" | python scripts/preprocess_agent_external.py \
    --agent-config config/agents/preprocess_structurer.deepseek_reasoner.json \
    --topic-id demo --mode note --timeout 60
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib import request as _req, error as _err

# 尽量少依赖：从本仓库导入内生后端
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autogen_client.autogen_backends import AutogenAgentBackend  # type: ignore


def _load_env():
    # 轻量加载 .env
    for p in [Path(__file__).resolve().parents[1]/'.env', Path.cwd()/'.env']:
        if p.exists():
            try:
                for line in p.read_text(encoding='utf-8').splitlines():
                    s = line.strip()
                    if not s or s.startswith('#') or '=' not in s:
                        continue
                    k,v = s.split('=',1)
                    k=k.strip(); v=v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)
            except Exception:
                pass


def _expand_env_placeholders(data):
    import re
    pat = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    def repl(s: str) -> str:
        def _r(m):
            return os.environ.get(m.group(1), "")
        return pat.sub(_r, s)
    if isinstance(data, dict):
        return {k: _expand_env_placeholders(v) for k,v in data.items()}
    if isinstance(data, list):
        return [_expand_env_placeholders(x) for x in data]
    if isinstance(data, str):
        return repl(data)
    return data


def _to_backend_agent(agent_cfg: dict) -> dict:
    """将 0.7.1 组件风格（顶层 provider/component_type/config）转换为后端可消费的 agent 结构。
    - 如果已经是后端风格（存在顶层 model_client/config），直接返回原对象的浅拷贝。
    - 若为组件风格（含 config 且 component_type==agent），返回 cfg 的浅拷贝，并保留必要键。
    """
    try:
        if not isinstance(agent_cfg, dict):
            return {}
        # 已是后端风格
        if isinstance(agent_cfg.get('model_client'), dict) or isinstance(agent_cfg.get('memory'), (list, dict)):
            return dict(agent_cfg)
        # 组件风格
        if agent_cfg.get('component_type') == 'agent' and isinstance(agent_cfg.get('config'), dict):
            cfg = dict(agent_cfg.get('config') or {})
            # 补齐 name/label 到 name
            if not cfg.get('name'):
                try:
                    cfg['name'] = agent_cfg.get('label') or agent_cfg.get('name') or 'Assistant'
                except Exception:
                    cfg['name'] = 'Assistant'
            # 确保存在 model_client 键
            if not isinstance(cfg.get('model_client'), dict):
                cfg['model_client'] = {}
            # 直连字段容错：顶层也允许覆盖（与 normalize_agent_config 对齐）
            if agent_cfg.get('base_url') and not cfg.get('base_url'):
                cfg['base_url'] = agent_cfg.get('base_url')
            if agent_cfg.get('api_key_env') and not (cfg.get('api_key_env') or (cfg.get('model_client') or {}).get('config',{}).get('api_key_env')):
                # 优先写入 model_client.config
                try:
                    _mc = cfg.get('model_client') or {}
                    if not isinstance(_mc, dict):
                        _mc = {}
                    _mcc = _mc.get('config') or {}
                    if not isinstance(_mcc, dict):
                        _mcc = {}
                    _mcc['api_key_env'] = agent_cfg.get('api_key_env')
                    _mc['config'] = _mcc
                    cfg['model_client'] = _mc
                except Exception:
                    cfg['api_key_env'] = agent_cfg.get('api_key_env')
            return cfg
    except Exception:
        pass
    # 兜底：原样返回（避免脚本崩溃）
    return dict(agent_cfg or {})


def _read_stdin() -> str:
    try:
        data = sys.stdin.read()
        return data or ""
    except Exception:
        return ""
    
def _read_input_file(path: str|None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    try:
        return p.read_text(encoding='utf-8')
    except Exception:
        return ""


def _autogen_infer(agent_cfg: dict, text: str, timeout: float) -> str:
    # 使用 AutogenAgentBackend 执行一次推理（内部已包含时间校准/内存处理等）
    backend = AutogenAgentBackend(agent_cfg)
    # 后端 infer_once 同步调用（内部会视情况建立事件循环），由外层统一控制脚本总超时
    return str(backend.infer_once(text or ""))


def _direct_call(agent_cfg: dict, text: str, timeout: float) -> str:
    mc = (agent_cfg.get('model_client') or {}).get('config', {})
    mc = _expand_env_placeholders(mc)
    api_key = str(mc.get('api_key') or '').strip()
    base_url = str(mc.get('base_url') or '').rstrip('/')
    model_id = str(mc.get('model') or '').strip()
    if not (api_key and base_url and model_id):
        missing = []
        if not model_id: missing.append('model')
        if not base_url: missing.append('base_url')
        if not api_key: missing.append('api_key')
        raise RuntimeError(f"直连缺少字段：{','.join(missing)}")

    # 控制生成长度：尊重配置，设置合理上限以避免服务端拒绝
    max_tokens = mc.get('max_tokens', 1024)
    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 1024
    # 上限定为 4096，避免无上限导致的服务端失败
    max_tokens = max(256, min(max_tokens, 4096))

    payload = {
        'model': model_id,
        'messages': [
            {'role': 'system', 'content': str(agent_cfg.get('system_message') or 'You are a helpful assistant.')},
            {'role': 'user', 'content': text or ''},
        ],
        'temperature': mc.get('temperature', 0.2),
        'top_p': mc.get('top_p', 0.9),
        'max_tokens': max_tokens,
    }
    if 'reasoner' in (model_id or '').lower():
        payload['reasoning'] = {'effort': 'low'}
    url = f"{base_url}/chat/completions"
    data = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }
    req = _req.Request(url, data=data, headers=headers, method='POST')
    with _req.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8', errors='ignore')
    obj = json.loads(body)
    chs = obj.get('choices') or []
    if not chs:
        return text or ''
    msg = chs[0].get('message') or {}
    return str(msg.get('content') or '')


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description='外部脚本：预处理 Agent')
    ap.add_argument('--agent-config', required=True)
    ap.add_argument('--topic-id', default='')
    ap.add_argument('--mode', default='note')
    ap.add_argument('--timeout', type=int, default=60)
    ap.add_argument('--input-file', default=None, help='原文文件路径（可选，优先于STDIN）')
    ap.add_argument('--output-file', default=None, help='结果输出文件路径（可选，便于被父进程读取）')
    args = ap.parse_args()

    # 读取输入：优先文件，其次 STDIN
    raw_md = _read_input_file(args.input_file) or _read_stdin()
    try:
        sys.stderr.write(f"[diag] cwd={os.getcwd()} input_len={len(raw_md)} agent_cfg={args.agent_config}\n")
        sys.stderr.flush()
    except Exception:
        pass

    # 读取 agent 配置
    try:
        with open(args.agent_config, 'r', encoding='utf-8') as f:
            agent_cfg = json.load(f)
    except Exception as e:
        print(f"# 结果整理\n\n读取Agent配置失败：{e}\n\n> 预处理 · 外部占位（原因：配置读取失败）", end='')
        return 1

    # 展开占位（api_key/base_url/model 等）
    agent_cfg = _expand_env_placeholders(agent_cfg)
    # 将 0.7.1 组件风格转换为后端可消费结构
    backend_agent = _to_backend_agent(agent_cfg)

    # 尝试内生后端
    t0 = time.time()
    try:
        out = _autogen_infer(backend_agent, raw_md, timeout=float(args.timeout))
        if not str(out or '').strip():
            # 最小占位：避免空输出导致上游判定为失败
            base = (raw_md or '').strip()
            if base:
                out = f"# 结果整理\n\n## 摘要\n- {base[:80]}\n"
            else:
                out = "# 结果整理\n\n- （无内容）\n"
        dt = time.time() - t0
        marker = f"> 预处理 · Agent(外部)：{backend_agent.get('name') or 'Agent'}（{(backend_agent.get('model_client') or {}).get('config',{}).get('model') or 'unknown-model'}）"
        final_text = (out or '').rstrip() + f"\n\n{marker}\n"
        # 写入输出文件（若指定）
        try:
            if args.output_file:
                Path(args.output_file).write_text(final_text, encoding='utf-8')
        except Exception:
            pass
        print(final_text, end='')
        return 0
    except Exception:
        pass

    # 直连兜底
    try:
        out = _direct_call(backend_agent, raw_md, timeout=float(args.timeout))
        if not str(out or '').strip():
            base = (raw_md or '').strip()
            if base:
                out = f"# 结果整理\n\n## 摘要\n- {base[:80]}\n"
            else:
                out = "# 结果整理\n\n- （无内容）\n"
        marker = f"> 预处理 · Agent(外部)：{backend_agent.get('name') or 'Agent'}（{(backend_agent.get('model_client') or {}).get('config',{}).get('model') or 'unknown-model'}）"
        final_text = (out or '').rstrip() + f"\n\n{marker}\n"
        try:
            if args.output_file:
                Path(args.output_file).write_text(final_text, encoding='utf-8')
        except Exception:
            pass
        print(final_text, end='')
        return 0
    except _err.HTTPError as he:
        try:
            err_body = he.read().decode('utf-8', errors='ignore')
        except Exception:
            err_body = ''
        fail_text = f"# 结果整理\n\n> 预处理 · 外部占位（原因：HTTP {he.code} {he.reason} {err_body[:160]}）"
        try:
            if args.output_file:
                Path(args.output_file).write_text(fail_text, encoding='utf-8')
        except Exception:
            pass
        print(fail_text, end='')
        return 3
    except _err.URLError as ue:
        fail_text = f"# 结果整理\n\n> 预处理 · 外部占位（原因：URLError {ue.reason}）"
        try:
            if args.output_file:
                Path(args.output_file).write_text(fail_text, encoding='utf-8')
        except Exception:
            pass
        print(fail_text, end='')
        return 2
    except Exception as e:
        fail_text = f"# 结果整理\n\n> 预处理 · 外部占位（原因：{type(e).__name__}: {e}）"
        try:
            if args.output_file:
                Path(args.output_file).write_text(fail_text, encoding='utf-8')
        except Exception:
            pass
        print(fail_text, end='')
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
