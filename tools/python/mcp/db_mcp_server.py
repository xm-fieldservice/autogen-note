# -*- coding: utf-8 -*-
"""
MCP 数据库服务（SQLite 正式版，最小可用）
- 与 `config/mcp/servers.json` 的 `rdbms-generic` 对应。
- 暴露两个工具：
  - db_query(sql: str) -> { columns: list[str], rows: list[dict] }
  - db_execute(sql: str) -> { affected_rows: int }
- DSN 读取优先级：命令行 --dsn > 环境变量 RDBMS_DSN_DEV。
- 仅支持 SQLite（dsn 必须以 sqlite:/// 开头）。
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from typing import Any, Dict, List

try:
    # mcp>=1.1.0 per requirements
    from mcp.server.fastmcp import FastMCP
except Exception as e:  # pragma: no cover
    raise SystemExit("缺少 mcp 依赖，请安装后再试：pip install mcp>=1.1.0")


def _parse_sqlite_path(dsn: str) -> str:
    prefix = "sqlite:///"
    if not dsn or not dsn.lower().startswith(prefix):
        raise ValueError("仅支持 SQLite，DSN 需以 sqlite:/// 开头，例如 sqlite:///d:/AI-Projects/desktop_app/data/rdbms/dev.sqlite")
    return dsn[len(prefix):]


class SQLiteClient:
    def __init__(self, dsn: str) -> None:
        self.db_path = _parse_sqlite_path(dsn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def query(self, sql: str) -> Dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(sql)
            cols: List[str] = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(zip(cols, [r[c] for c in cols])) for r in cur.fetchall()] if cols else []
            return {"columns": cols, "rows": rows}

    def execute(self, sql: str) -> Dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(sql)
            affected = cur.rowcount if cur.rowcount is not None else 0
            conn.commit()
            return {"affected_rows": int(affected)}


def build_app(dsn: str) -> FastMCP:
    app = FastMCP("rdbms-generic")
    client = SQLiteClient(dsn)

    @app.tool()
    def db_query(sql: str) -> Dict[str, Any]:
        """执行只读查询（SELECT）。返回 columns 与 rows。"""
        sql_norm = (sql or "").strip()
        if not sql_norm.lower().startswith("select"):
            raise ValueError("db_query 仅允许 SELECT 语句")
        return client.query(sql_norm)

    @app.tool()
    def db_execute(sql: str) -> Dict[str, Any]:
        """执行 DDL/DML 语句（非 SELECT），返回 affected_rows。"""
        sql_norm = (sql or "").strip()
        if sql_norm.lower().startswith("select"):
            raise ValueError("db_execute 不允许执行 SELECT，请使用 db_query")
        return client.execute(sql_norm)

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="SQLite MCP Server（db_query/db_execute）")
    ap.add_argument("--dsn", default=os.getenv("RDBMS_DSN_DEV", ""), help="数据库 DSN（默认读取 RDBMS_DSN_DEV）")
    args = ap.parse_args()

    if not args.dsn:
        raise SystemExit("缺少 DSN，请通过 --dsn 或 RDBMS_DSN_DEV 提供，例如 sqlite:///d:/.../dev.sqlite")

    app = build_app(args.dsn)
    # FastMCP 默认以 stdio 运行，供宿主（AutoGen）托管。
    app.run()


if __name__ == "__main__":
    main()
