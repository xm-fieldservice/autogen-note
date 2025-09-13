# -*- coding: utf-8 -*-
"""
SQLite 初始化脚本（用于 Tri-Store 本地开发）
- 读取 --dsn（推荐 sqlite:///d:/.../dev.sqlite）
- 创建数据库文件（若不存在）并建表 mindmap_nodes（若不存在）
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from typing import Optional

DDL = (
    "CREATE TABLE IF NOT EXISTS mindmap_nodes ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " source TEXT NOT NULL,"
    " channel TEXT NOT NULL,"
    " content_type TEXT NOT NULL,"
    " tree_id TEXT NOT NULL,"
    " node_id TEXT NOT NULL,"
    " level INTEGER NOT NULL,"
    " path TEXT NOT NULL,"
    " subtype TEXT NOT NULL,"
    " created_at TEXT NOT NULL,"
    " updated_at TEXT,"
    " module TEXT,"
    " version TEXT,"
    " owner TEXT,"
    " tags TEXT"
    ")"
)


def _parse_sqlite_path(dsn: str) -> str:
    prefix = "sqlite:///"
    if not dsn or not dsn.lower().startswith(prefix):
        raise SystemError("DSN 必须以 sqlite:/// 开头")
    return dsn[len(prefix):]


def ensure_table(dsn: str) -> None:
    db_path = _parse_sqlite_path(dsn)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(DDL)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="初始化 SQLite（建表 mindmap_nodes）")
    ap.add_argument("--dsn", required=True, help="sqlite:///... 路径")
    args = ap.parse_args()
    ensure_table(args.dsn)
    print("SQLite 初始化完成：", args.dsn)


if __name__ == "__main__":
    main()
