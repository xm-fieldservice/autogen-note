from __future__ import annotations
import subprocess
from pathlib import Path
import sys
import os
from typing import Dict, Any, List, Optional
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
LOG_DIR = ROOT / "logs" / "queue"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _run_python_script(script_path: Path, args: List[str], stdin_text: Optional[str], timeout: int = 60) -> tuple[int, str, str]:
    if not script_path.exists():
        raise FileNotFoundError(f"未找到脚本: {script_path}")
    # 使用当前进程的 Python 解释器，避免路径探测失败
    py = sys.executable or "python"
    cmd = [py, str(script_path)] + args
    # 强制子进程以 UTF-8 输出；并在解码时容错替换非法字节，避免 UnicodeDecodeError
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        input=(stdin_text or ""),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def external_preprocess(topic_id: str, raw_md: str, mode: str, agent_config_path: str|None) -> str:
    script = SCRIPTS_DIR / "preprocess_agent_external.py"
    args: List[str] = []
    # 1) 规范化 agent_config_path：兼容仅文件名或前端传错值
    norm_cfg: Optional[str] = None
    if agent_config_path and isinstance(agent_config_path, str):
        # 去除可能拼接的时间戳等非路径字符（仅保留最后一个路径段）
        candidate = Path(agent_config_path).name
        # 优先绝对/相对路径存在判断
        direct = ROOT / agent_config_path if not Path(agent_config_path).is_file() else Path(agent_config_path)
        if Path(agent_config_path).is_file():
            norm_cfg = str(Path(agent_config_path))
        elif direct.is_file():
            norm_cfg = str(direct)
        else:
            # 退回到 config/agents 目录尝试
            alt = ROOT / "config" / "agents" / candidate
            if alt.is_file():
                norm_cfg = str(alt)
            else:
                # 明确提示配置缺失，直接返回占位，避免子进程无效失败
                (LOG_DIR / "preprocess_external.last_err.txt").write_text(
                    f"agent 配置未找到: '{agent_config_path}'；已尝试 '{alt}'\n", encoding="utf-8"
                )
                return "> 预处理 · 外部占位（原因：agent 配置未找到；请检查选择器是否传递了有效路径 config/agents/*.json）"
    if norm_cfg:
        args += ["--agent-config", norm_cfg]
    # 预处理超时：支持环境变量 PREPROCESS_TIMEOUT_SECONDS 覆盖；默认 90s
    try:
        base_timeout = int(os.environ.get("PREPROCESS_TIMEOUT_SECONDS", "90"))
    except Exception:
        base_timeout = 90
    # 文本越长，越容易触发长推理：根据长度做轻量加成（最多 +30s）
    length_bonus = 0
    try:
        n = len(raw_md or "")
        if n > 4000:
            length_bonus = 30
        elif n > 2500:
            length_bonus = 15
    except Exception:
        length_bonus = 0
    script_timeout = base_timeout + length_bonus
    args += ["--topic-id", topic_id or "", "--mode", mode or "note", "--timeout", str(script_timeout)]
    # 将原文写入临时文件，供脚本通过 --input-file 读取，避免某些环境下 stdin 丢失
    tmp_path: Optional[str] = None
    try:
        # 2) 轻量清洗：若 ``` 出现为奇数次，自动补一个闭合围栏，避免直连端解析失败
        safe_text = raw_md or ""
        try:
            ticks = safe_text.count("```")
            if ticks % 2 == 1:
                safe_text = f"{safe_text.rstrip()}\n\n```\n"
        except Exception:
            pass
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as tf:
            tf.write(safe_text)
            tf.flush()
            tmp_path = tf.name
        args += ["--input-file", tmp_path]
        # 指定输出文件，供父进程回读
        out_file = LOG_DIR / "preprocess_external.last_render.md"
        try:
            # 清空旧文件
            if out_file.exists():
                out_file.unlink()
        except Exception:
            pass
        args += ["--output-file", str(out_file)]
        # 子进程总体等待时间：脚本超时 + 10s 缓冲
        rc, stdout, stderr = _run_python_script(script, args, stdin_text=safe_text or "", timeout=script_timeout + 10)
        # 调试落盘
        (LOG_DIR / "preprocess_external.last_cmd.txt").write_text(
            " ".join([str(script)] + args), encoding="utf-8"
        )
        (LOG_DIR / "preprocess_external.last_in.md").write_text(raw_md or "", encoding="utf-8")
        (LOG_DIR / "preprocess_external.last_out.txt").write_text(stdout or "", encoding="utf-8")
        (LOG_DIR / "preprocess_external.last_err.txt").write_text(stderr or "", encoding="utf-8")
        # 仅依据长度判断是否空输出，不 strip，避免误判只有换行/BOM 等情况
        if rc != 0:
            # 汇总更可读的错误信息
            err_first = (stderr or "").splitlines()[0] if stderr else ""
            diag = err_first or (stderr[:200] if stderr else "")
            return f"> 预处理 · 外部占位（原因：脚本退出码 {rc}；stderr: {diag}；log=logs/queue/preprocess_external.last_err.txt）"
        # 优先读取输出文件（更稳健）
        try:
            if out_file.exists():
                file_text = out_file.read_text(encoding="utf-8")
                if file_text and len(file_text) > 0:
                    return file_text
        except Exception:
            pass
        # 回退 stdout
        if stdout and len(stdout) > 0:
            return stdout
        # 空输出：返回占位，附带 stdout/stderr 长度与片段
        outlen = 0 if stdout is None else len(stdout)
        errfrag = (stderr or "")[:200]
        hint = "；log=logs/queue/preprocess_external.last_render.md" if out_file.exists() else ""
        return f"> 预处理 · 外部占位（原因：脚本空输出；stdout_len={outlen}；stderr: {errfrag}{hint})"
    except Exception as e:
        # 发生异常时返回占位并附带原因
        return f"> 预处理 · 外部占位（原因：{type(e).__name__}: {e}）"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def external_submit(topic_id: str, final_md: str, mode: str, team_config_path: str|None, policy: Dict[str, Any]|None) -> str:
    script = SCRIPTS_DIR / "submit_team_external.py"
    args: List[str] = []
    if team_config_path:
        args += ["--team-config", team_config_path]
    args += ["--topic-id", topic_id or "", "--mode", mode or "note", "--timeout", "60"]
    # 将原文写入临时文件，供脚本通过 --input-file 读取
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as tf:
            tf.write(final_md or "")
            tf.flush()
            tmp_path = tf.name
        args += ["--input-file", tmp_path]
        # 指定输出文件，供父进程回读
        out_file = LOG_DIR / "submit_external.last_render.md"
        try:
            if out_file.exists():
                out_file.unlink()
        except Exception:
            pass
        args += ["--output-file", str(out_file)]
        rc, stdout, stderr = _run_python_script(script, args, stdin_text=final_md or "", timeout=65)
        # 调试落盘
        (LOG_DIR / "submit_external.last_cmd.txt").write_text(
            " ".join([str(script)] + args), encoding="utf-8"
        )
        (LOG_DIR / "submit_external.last_in.md").write_text(final_md or "", encoding="utf-8")
        (LOG_DIR / "submit_external.last_out.txt").write_text(stdout or "", encoding="utf-8")
        (LOG_DIR / "submit_external.last_err.txt").write_text(stderr or "", encoding="utf-8")
        # 返回策略：优先回读文件，其次 stdout
        if rc != 0:
            return f"> 提交 · 外部占位（原因：脚本退出码 {rc}；stderr: {stderr[:200]}；log=logs/queue/submit_external.last_err.txt）"
        try:
            if out_file.exists():
                file_text = out_file.read_text(encoding="utf-8")
                if file_text and len(file_text) > 0:
                    return file_text
        except Exception:
            pass
        if stdout and len(stdout) > 0:
            return stdout
        outlen = 0 if stdout is None else len(stdout)
        errfrag = (stderr or "")[:200]
        hint = "；log=logs/queue/submit_external.last_render.md" if out_file.exists() else ""
        return f"> 提交 · 外部占位（原因：脚本空输出；stdout_len={outlen}；stderr: {errfrag}{hint})"
    except Exception as e:
        return f"> 提交 · 外部占位（原因：{type(e).__name__}: {e}）"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
