import argparse
import datetime as dt
import json
import os
import hashlib
import time
import threading
import concurrent.futures
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

# 文件操作锁
_file_locks = {}
_locks_mutex = threading.RLock()


APP_NAME = "windsurf-sink"
APP_VERSION = "0.1.0"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def iso_now() -> str:
    # Use local time, include timezone offset
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def day_folder(root: Path) -> Path:
    d = dt.date.today().strftime("%Y-%m-%d")
    return root / "logs" / d


def to_jsonl_line(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _sanitize_title(text: str, max_len: int = 80) -> str:
    """Make a single-line, safe title from raw content.
    - Take first line
    - Strip markdown heading/code markers
    - Collapse whitespace
    - Truncate to max_len
    """
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    # Remove common markdown markers and backticks
    for ch in ["#", "`", "*", "_", "<", ">"]:
        line = line.replace(ch, "")
    # Collapse spaces
    line = " ".join(line.split())
    if len(line) > max_len:
        line = line[: max_len - 1] + "…"
    return line


def _md_has_open_pair(md_fp: Path, sep: str) -> bool:
    """Return True if the markdown file exists and DOES NOT end with the separator.
    This indicates a previous user section is open awaiting assistant reply.
    """
    if not md_fp.exists():
        return False
    try:
        # 添加文件存在二次检查和文件大小检查
        if not os.path.exists(str(md_fp)):
            return False
            
        size = md_fp.stat().st_size
        if size == 0:
            return False
            
        # 使用线程超时代替signal（Windows兼容）
        import io
        import threading
        import concurrent.futures
        
        def read_file_with_timeout():
            try:
                with io.open(str(md_fp), "rb") as f:
                    read_len = min(4096, size)
                    f.seek(size - read_len)
                    return f.read().decode("utf-8", errors="ignore")
            except Exception as e:
                print(f"[WARNING] 读取文件出错: {e}", flush=True)
                raise
        
        # 使用线程池实现超时控制（3秒超时）
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(read_file_with_timeout)
                tail = future.result(timeout=3)
        except concurrent.futures.TimeoutError:
            print(f"[WARNING] 检查文件末尾超时: {md_fp}", flush=True)
            return False
        except (PermissionError, IOError) as e:
            print(f"[WARNING] 无法访问文件: {md_fp} - {e}", flush=True)
            return False
            
        tail = tail.rstrip("\n")
        return not (tail.endswith(sep.rstrip("\n")))
    except Exception as e:
        # 更详细的错误日志
        print(f"[ERROR] _md_has_open_pair失败: {md_fp} - {e}", flush=True)
        # If any error reading, fall back to conservative (closed)
        return False


class SinkContext:
    def __init__(self, log_dir: Path, md_separator: str = "\n---\n", md_heading_level: int = 3) -> None:
        self.log_dir = log_dir
        self.md_separator = md_separator
        self.md_heading_level = max(1, min(6, int(md_heading_level)))
        ensure_dir(self.log_dir)

    def session_jsonl(self, session_id: str) -> Path:
        folder = day_folder(self.log_dir)
        ensure_dir(folder)
        return folder / f"session-{session_id}.jsonl"

    def session_json(self, session_id: str) -> Path:
        folder = day_folder(self.log_dir)
        ensure_dir(folder)
        return folder / f"session-{session_id}.json"

    def session_md(self, session_id: str) -> Path:
        folder = day_folder(self.log_dir)
        ensure_dir(folder)
        return folder / f"session-{session_id}.md"


mcp = FastMCP(APP_NAME)
_ctx: Optional[SinkContext] = None

# In-process dedup/rate-limit cache: (session_id, hash) -> last_ts
_recent: Dict[Tuple[str, str], float] = {}
_recent_ttl_sec: float = 7.0  # rate-limit window

# Role whitelist and content filters
_allowed_roles = {"user", "assistant"}
_content_block_markers = (
    "<ephemeral_message>",
    "Thought for ",
)

def _hash_content(role: str, content: str, max_len: int = 2048) -> str:
    payload = (role + "\n" + content[:max_len]).encode("utf-8", errors="ignore")
    return hashlib.sha1(payload).hexdigest()

def _should_skip(session_id: str, role: str, content: str) -> Tuple[bool, str]:
    # role filter
    if role not in _allowed_roles:
        return True, "role_filtered"
    # content filters
    low = content or ""
    for marker in _content_block_markers:
        if marker in low:
            return True, "content_filtered"
    # dedup / rate-limit
    now = time.time()
    h = _hash_content(role, low)
    key = (session_id, h)
    last = _recent.get(key)
    if last is not None and (now - last) < _recent_ttl_sec:
        return True, "dedup_rate_limited"
    _recent[key] = now
    # GC occasionally
    if len(_recent) > 2048:
        cutoff = now - _recent_ttl_sec
        for k, ts0 in list(_recent.items()):
            if ts0 < cutoff:
                _recent.pop(k, None)
    return False, ""


def get_file_lock(file_path: str):
    """获取指定文件的线程锁"""
    with _locks_mutex:
        if file_path not in _file_locks:
            _file_locks[file_path] = threading.RLock()
        return _file_locks[file_path]

@mcp.tool()
def save_message(
    session_id: str,
    role: str,
    content: str,
    meta: Optional[Dict[str, Any]] = None,
    write_markdown: bool = True,
    write_jsonl: bool = False,
    md_separator: Optional[str] = None,
    md_heading_level: Optional[int] = None,
    md_title: Optional[str] = None,
    md_title_include_date: bool = True,
) -> Dict[str, Any]:
    """Append a single message to session JSONL.

    Args:
      session_id: Logical conversation id (e.g., date+short uuid).
      role: "user" | "assistant" | "system" | etc.
      content: Raw text content (no truncation).
      meta: Optional metadata (e.g., model, tokens, tool_calls).

    Returns: dict with file path and size.
    """
    start_time = time.time()
    try:
        print(f"[DEBUG] save_message开始: session={session_id}, role={role}, len={len(content) if content else 0}", flush=True)
        assert _ctx is not None, "Server context is not initialized"
        ts = iso_now()
        line = {
            "timestamp": ts,
            "session_id": session_id,
            "role": role,
            "content": content,
            "meta": meta or {},
        }
        out: Dict[str, Any] = {}

        # Pre-checks: role/content filter and dedup/rate-limit
        skipped, reason = _should_skip(session_id, role, content or "")
        if skipped:
            out["skipped"] = True
            out["reason"] = reason
            print(f"[DEBUG] save_message跳过: {reason}", flush=True)
            return out

        # Markdown append (default on)
        if write_markdown:
            md_fp = _ctx.session_md(session_id)
            # 获取文件锁
            file_lock = get_file_lock(str(md_fp))
            
            # 使用超时锁定，防止死锁
            lock_acquired = False
            try:
                lock_acquired = file_lock.acquire(timeout=2)  # 2秒超时
                if not lock_acquired:
                    print(f"[WARNING] 获取文件锁超时: {md_fp}", flush=True)
                    out["skipped"] = True
                    out["reason"] = "file_lock_timeout"
                    return out
                    
                # 成功获取锁，处理文件操作
                # Determine heading level and separator
                heading_level = _ctx.md_heading_level if md_heading_level is None else max(1, min(6, int(md_heading_level)))
                sep = _ctx.md_separator if (md_separator is None) else md_separator
                heading = "#" * heading_level
                file_exists = md_fp.exists()
                
                # 使用线程池执行文件写入，带超时控制
                def write_file_operation():
                    try:
                        with io.open(str(md_fp), "a", encoding="utf-8") as f:
                            # On first write, add a conversation title
                            if not file_exists:
                                f.write(f"# Conversation {session_id}\n\n")
                            # Detect if there is an open user section awaiting assistant
                            open_pair = _md_has_open_pair(md_fp, sep)

                            def write_heading_for(current_role: str) -> None:
                                """Write a heading line for a new section using current context."""
                                base_title_local = None
                                if (not md_title) and current_role == "user":
                                    base_title_local = _sanitize_title(content)
                                title_final = (md_title.strip() if md_title else (base_title_local if base_title_local else f"[{current_role}]"))
                                date_str_local = ts.split("T")[0]
                                if md_title_include_date:
                                    heading_line_local = f"{heading} {title_final} - {date_str_local}"
                                else:
                                    heading_line_local = f"{heading} {title_final}"
                                f.write(heading_line_local + "\n\n")

                            # Decide whether to write heading
                            if role == "assistant" and open_pair:
                                # Continue the existing open user section: no new heading
                                pass
                            else:
                                # Start a new section (user, or assistant without preceding user)
                                write_heading_for(role)

                            # Write meta + content
                            f.write(f"> role: {role} | timestamp: {ts}\n\n")
                            f.write(content)
                            f.write("\n\n")

                            # Section closing policy: close only after assistant when pairing
                            if role == "assistant":
                                if sep:
                                    f.write(sep)
                                    if not sep.endswith("\n"):
                                        f.write("\n")
                            else:
                                # For user (or other roles), do not close here to allow pairing.
                                # Keep as is (open).
                                pass
                    except Exception as e:
                        print(f"[ERROR] 写入文件失败: {md_fp} - {e}", flush=True)
                        raise
                
                # 使用线程池执行文件操作，设置超时时间
                try:
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(write_file_operation)
                        future.result(timeout=5)  # 5秒超时
                except concurrent.futures.TimeoutError:
                    print(f"[ERROR] 写入文件超时: {md_fp}", flush=True)
                    out["skipped"] = True
                    out["reason"] = "file_write_timeout"
                    return out
                except Exception as e:
                    print(f"[ERROR] 写入文件时发生错误: {e}", flush=True)
                    out["skipped"] = True
                    out["reason"] = f"file_write_error:{str(e)}"
                    return out
                    
                # 文件写入成功，更新输出信息
                out["markdown"] = {"path": str(md_fp), "bytes": md_fp.stat().st_size if md_fp.exists() else 0}
            finally:
                # 确保释放锁
                if lock_acquired:
                    file_lock.release()
                    
        # 所有操作成功完成
        out["skipped"] = False
        out["reason"] = ""
        duration = time.time() - start_time
        print(f"[DEBUG] save_message完成: 用时={duration:.3f}秒", flush=True)
        return out
    except Exception as e:
        # 捕获所有异常，避免工具失败导致整个应用崩溃
        duration = time.time() - start_time
        print(f"[ERROR] save_message异常: {e}, 用时={duration:.3f}秒", flush=True)
        return {
            "skipped": True,
            "reason": f"sink_error:{str(e)}",
            "error": str(e)
        }

    out["skipped"] = False
    out["reason"] = ""
    return out


@mcp.tool()
def save_conversation(
    session_id: str,
    conversation: List[Dict[str, Any]],
    write_markdown: bool = True,
) -> Dict[str, Any]:
    """Write a full conversation dump and optional Markdown summary.

    conversation: list of messages with fields e.g.
      {"timestamp": str?, "role": str, "content": str, "meta": dict?}
    """
    start_time = time.time()
    try:
        print(f"[DEBUG] save_conversation开始: session={session_id}, msgs={len(conversation)}", flush=True)
        assert _ctx is not None, "Server context is not initialized"
        # Markdown only
        out: Dict[str, Any] = {}
        md_fp = None
        
        if write_markdown:
            md_fp = _ctx.session_md(session_id)
            # 获取文件锁
            file_lock = get_file_lock(str(md_fp))
            
            # 使用超时锁定，防止死锁
            lock_acquired = False
            try:
                lock_acquired = file_lock.acquire(timeout=2)  # 2秒超时
                if not lock_acquired:
                    print(f"[WARNING] 获取文件锁超时: {md_fp}", flush=True)
                    out["skipped"] = True
                    out["reason"] = "file_lock_timeout"
                    return out
                
                # 定义文件写入操作
                def write_conversation_file():
                    try:
                        with io.open(str(md_fp), "w", encoding="utf-8") as f:
                            f.write(f"# Conversation {session_id}\n\n")
                            for msg in conversation:
                                ts = msg.get("timestamp") or iso_now()
                                role = msg.get("role", "assistant")
                                content = msg.get("content", "")
                                f.write(f"## [{role}] {ts}\n\n")
                                f.write(content)
                                f.write("\n\n")
                    except Exception as e:
                        print(f"[ERROR] 写入会话内容失败: {md_fp} - {e}", flush=True)
                        raise
                
                # 使用线程池执行文件操作，设置超时时间
                try:
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(write_conversation_file)
                        future.result(timeout=5)  # 5秒超时
                except concurrent.futures.TimeoutError:
                    print(f"[ERROR] 写入会话超时: {md_fp}", flush=True)
                    out["skipped"] = True
                    out["reason"] = "file_write_timeout"
                    return out
                except Exception as e:
                    print(f"[ERROR] 写入会话时发生错误: {e}", flush=True)
                    out["skipped"] = True
                    out["reason"] = f"file_write_error:{str(e)}"
                    return out
                    
                # 文件写入成功
                if md_fp is not None:
                    out["markdown"] = {"path": str(md_fp), "bytes": md_fp.stat().st_size if md_fp.exists() else 0}
            finally:
                # 确保释放锁
                if lock_acquired:
                    file_lock.release()
        
        duration = time.time() - start_time
        print(f"[DEBUG] save_conversation完成: 用时={duration:.3f}秒", flush=True)
        out["skipped"] = False
        out["reason"] = ""
        return out
    except Exception as e:
        # 捕获所有异常，避免工具失败导致整个应用崩溃
        duration = time.time() - start_time
        print(f"[ERROR] save_conversation异常: {e}, 用时={duration:.3f}秒", flush=True)
        return {
            "skipped": True,
            "reason": f"sink_error:{str(e)}",
            "error": str(e)
        }


@mcp.tool()
def ping() -> str:
    return "ok"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windsurf MCP sink server")
    parser.add_argument(
        "--log-dir",
        type=str,
        default=str(Path.cwd() / "out" / "windsurf-logs"),
        help="Directory to store logs (default: ./out/windsurf-logs)",
    )
    parser.add_argument(
        "--md-separator",
        type=str,
        default="\n---\n",
        help="Markdown separator between messages (default: ---)",
    )
    parser.add_argument(
        "--md-heading-level",
        type=int,
        default=3,
        help="Markdown heading level for messages 1-6 (default: 3)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    _ctx = SinkContext(Path(args.log_dir), md_separator=args.md_separator, md_heading_level=args.md_heading_level)
    # Display resolved directory for debugging when launched manually
    print(f"[{APP_NAME}] Log dir: {os.path.abspath(args.log_dir)}", flush=True)
    mcp.run()
