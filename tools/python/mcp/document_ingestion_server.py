# -*- coding: utf-8 -*-
"""
MCP 文档解析服务（占位版）
- 目标：作为 Autogen 0.7.1 的 MCP Server，后续由客户端通过内生 MCP 机制调用。
- 当前占位：支持命令行直调，解析 .txt/.md/.pdf/.docx，为后续正式接入 MCP 协议打基础。

用法（命令行直调占位）：
  python tools/python/mcp/document_ingestion_server.py --files "D:/a.txt;D:/b.pdf"
输出：JSON，形如 {"results":[{"text":..., "metadata":{...}}, ...], "errors": [...]}。

注意：正式 MCP 协议集成将在下一步完成（使用 autogen_ext.tools.mcp）。
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

CHUNK_SIZE = 1500


def _read_text_file(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return p.read_text(encoding="gbk", errors="ignore")
        except Exception:
            return ""


def _read_pdf_file(p: Path) -> str:
    try:
        # 轻依赖：尝试使用 pypdf
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        texts = []
        for page in reader.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append("")
        return "\n".join(texts)
    except Exception:
        return ""


def _read_docx_file(p: Path) -> str:
    try:
        from docx import Document  # python-docx
        doc = Document(str(p))
        texts = []
        for para in doc.paragraphs:
            texts.append(para.text or "")
        return "\n".join(texts)
    except Exception:
        return ""


def _chunk(text: str, size: int = CHUNK_SIZE) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [text[i:i+size] for i in range(0, len(text), size)]


def _guess_mime(ext: str) -> str:
    e = ext.lower().lstrip('.')
    return {
        "txt": "text/plain",
        "md": "text/markdown",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(e, "application/octet-stream")


def parse_files(paths: List[str]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for ap in paths:
        try:
            p = Path(ap)
            if not p.exists() or not p.is_file():
                errors.append(f"not_found:{ap}")
                continue
            ext = p.suffix.lower().lstrip('.')
            if ext in ("txt", "md"):
                txt = _read_text_file(p)
            elif ext == "pdf":
                txt = _read_pdf_file(p)
            elif ext == "docx":
                txt = _read_docx_file(p)
            else:
                errors.append(f"unsupported:{ap}")
                continue
            chunks = _chunk(txt)
            for idx, ck in enumerate(chunks):
                results.append({
                    "text": ck,
                    "metadata": {
                        "file_name": p.name,
                        "file_ext": ext,
                        "mime": _guess_mime(ext),
                        "chunk_idx": idx,
                        "size": len(ck),
                    }
                })
        except Exception as e:
            errors.append(f"error:{ap}:{e}")
    return {"results": results, "errors": errors}


def main():
    ap = argparse.ArgumentParser(description="文档解析占位（直调版本，后续替换为 MCP 协议）")
    ap.add_argument("--files", required=True, help="以分号分隔的文件路径列表")
    args = ap.parse_args()
    files = [s for s in str(args.files).split(';') if s.strip()]
    out = parse_files(files)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
