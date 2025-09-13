from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from repositories.mcp_repo import MCPRepository


class MCPManager:
    """
    MCP 管理器（stdio 进程托管版 v1）：
    - 读取并缓存 config/mcp/servers.json
    - 依据配置以 stdio 方式拉起 MCP 服务器子进程，并记录 PID/命令
    - 预留：后续将这些 stdio 连接交由 Autogen 0.7.1 内生 API 进行正式挂载
    - 提供 servers 列表给运行器以便构建工具/内存
    """

    def __init__(self) -> None:
        self._repo = MCPRepository()
        self._cache: Dict[str, Any] | None = None
        self._procs: list[subprocess.Popen] = []
        self._log_path = Path("logs/app.log")

    def _log(self, level: str, msg: str, extra: Dict[str, Any] | None = None) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                line = {"level": level, "msg": msg}
                if extra:
                    line.update(extra)
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def load(self) -> Dict[str, Any]:
        if self._cache is None:
            self._cache = self._repo.get_servers()
        return self._cache

    def list_servers(self) -> List[Dict[str, Any]]:
        reg = self.load()
        arr = reg.get("servers", []) if isinstance(reg, dict) else []
        return [s for s in arr if isinstance(s, dict)]

    def _spawn_stdio(self, name: str, cmd: str, args: List[str] | None, env: Dict[str, str] | None, cwd: str | None) -> subprocess.Popen:
        argv = [cmd] + list(args or [])
        env_final = os.environ.copy()
        if env:
            for k, v in env.items():
                if v is None:
                    continue
                env_final[str(k)] = str(v)
        proc = subprocess.Popen(
            argv,
            cwd=cwd or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env_final,
            text=True,
        )
        return proc

    def register_into_runtime(self) -> int:
        """注册 MCP 服务器到运行时（以 stdio 子进程形式）。
        返回成功启动的个数，并把错误写入 logs/app.log。
        """
        servers = self.list_servers()
        ok = 0
        for s in servers:
            try:
                if str(s.get("transport", "stdio")).lower() != "stdio":
                    self._log("warn", "跳过非 stdio 传输的 MCP 配置", {"name": s.get("name")})
                    continue
                name = str(s.get("name") or "mcp")
                cmd = s.get("command") or s.get("cmd")
                if not cmd:
                    self._log("error", "缺少 command", {"name": name})
                    continue
                args = s.get("args") or []
                env = s.get("env") or {}
                cwd = s.get("cwd") or None
                proc = self._spawn_stdio(name, cmd=str(cmd), args=[str(a) for a in args], env={k: str(v) for k, v in env.items()}, cwd=cwd)
                self._procs.append(proc)
                ok += 1
                self._log("info", "MCP server started", {"name": name, "pid": proc.pid, "cmd": cmd, "args": args})
            except Exception as e:
                self._log("error", "MCP server start failed", {"error": str(e), "cfg": s})
                continue
        return ok


_singleton: MCPManager | None = None


def get_manager() -> MCPManager:
    global _singleton
    if _singleton is None:
        _singleton = MCPManager()
    return _singleton
