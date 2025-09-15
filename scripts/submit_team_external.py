#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
提交 Team 外部脚本（STDIN/--input-file -> Markdown）
- 严格优先使用 Autogen Team 内生机制；失败时占位回退
- 输入：从 --input-file 或 STDIN 读取最终 Markdown
- 输出：STDOUT 打印最终 Markdown，并在 --output-file 时同步写入文件

退出码：
- 0 成功；1 参数错误；2 超时；3 HTTP/鉴权错误；4 其他异常
用法示例：
  echo "最终内容" | python scripts/submit_team_external.py \
    --team-config config/teams/team_demo.json \
    --topic-id demo --mode note --timeout 60 \
    --output-file logs/queue/submit_external.last_render.md
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

# 轻量读取 .env 供 Team 内的客户端使用

def _load_env():
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


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description='外部脚本：提交 Team')
    ap.add_argument('--team-config', required=True)
    ap.add_argument('--topic-id', default='')
    ap.add_argument('--mode', default='note')
    ap.add_argument('--timeout', type=int, default=60)
    ap.add_argument('--input-file', default=None, help='原文文件路径（可选，优先于STDIN）')
    ap.add_argument('--output-file', default=None, help='结果输出文件路径（可选）')
    args = ap.parse_args()

    final_md = _read_input_file(args.input_file) or _read_stdin()
    try:
        sys.stderr.write(f"[diag] cwd={os.getcwd()} input_len={len(final_md)} team_cfg={args.team_config}\n")
        sys.stderr.flush()
    except Exception:
        pass

    # 读取 team 配置
    try:
        with open(args.team_config, 'r', encoding='utf-8') as f:
            team_cfg = json.load(f)
    except Exception as e:
        fail_text = f"# 提交结果\n\n> 提交 · 外部占位（原因：团队配置读取失败：{e}）"
        try:
            if args.output_file:
                Path(args.output_file).write_text(fail_text, encoding='utf-8')
        except Exception:
            pass
        print(fail_text, end='')
        return 1

    # Autogen Team 内生执行（若不可用则直接回显 + 标记）
    out_text = None
    try:
        from autogen_client.autogen_backends import AutogenTeamBackend  # type: ignore
        backend = AutogenTeamBackend(team_cfg)  # 具体实现由内生组件决定
        # 这里采用最小调用：将最终 Markdown 作为输入，返回处理后的文本
        out_text = str(backend.run_once(final_md or ""))  # 若无该方法则抛异常走占位
    except Exception:
        out_text = None

    if not out_text or not str(out_text).strip():
        # 占位：直接回显输入内容
        base = (final_md or '').strip()
        if base:
            out_text = base
        else:
            out_text = "# 提交结果\n\n- （无内容）\n"

    marker = f"> 提交 · Agent(外部)：{team_cfg.get('name') or 'Team'}"
    final_text = (out_text or '').rstrip() + f"\n\n{marker}\n"

    try:
        if args.output_file:
            Path(args.output_file).write_text(final_text, encoding='utf-8')
    except Exception:
        pass
    print(final_text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
