from fastapi import FastAPI, HTTPException, UploadFile, File, Response, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional
import os
import sys
import uuid
import json
from pathlib import Path
import sqlite3
import time

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.server.models import (
    PreprocessRequest, PreprocessResponse,
    SubmitRequest, SubmitResponse,
    IngestResponse, ExportTopicResponse,
    TestValidateRequest, TestValidateResponse,
)
from services.server import external_runner
from services.server.validators import ensure_structured_markdown

app = FastAPI(title="Notes Backend (Autogen 0.7.1)")

# CORS: 允许本地与服务器前端页面访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 简易内存态：用于预演接口，后续将替换为 DB/MCP 管道
_FAKE_DB = {
    "documents": []
}

def _new_trace() -> str:
    return uuid.uuid4().hex

def _run_mode() -> str:
    return os.environ.get("RUN_MODE", "internal").lower().strip()  # internal|external

def _queue_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    qdir = root / "logs" / "queue"
    qdir.mkdir(parents=True, exist_ok=True)
    return qdir / "tri_write.jsonl"

def _enqueue_tri_write(topic_id: str, note_id: str, mode: str, policy: Optional[dict]):
    rec = {
        "topic_id": topic_id,
        "note_id": note_id,
        "mode": mode,
        "policy": policy or {},
        "event": "tri_write_enqueued",
    }
    try:
        qp = _queue_path()
        with qp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _db_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    ddir = root / "data"
    ddir.mkdir(parents=True, exist_ok=True)
    return ddir / "app_data.sqlite3"

def _db_conn():
    p = _db_path()
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            note_id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    return conn

def _db_insert_note(note_id: str, topic_id: str, content: str):
    ts = int(time.time() * 1000)
    with _db_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notes(note_id, topic_id, content, created_at) VALUES(?,?,?,?)",
            (note_id, topic_id, content, ts),
        )

def _db_query_notes_by_topic(topic_id: str) -> list:
    with _db_conn() as conn:
        cur = conn.execute(
            "SELECT note_id, topic_id, content, created_at FROM notes WHERE topic_id=? ORDER BY created_at ASC",
            (topic_id,),
        )
        rows = cur.fetchall()
    return [
        {"note_id": r[0], "topic_id": r[1], "content": r[2], "created_at": r[3]} for r in rows
    ]

# 应用启动时确保 DB 架构存在
@app.on_event("startup")
def _init_db_on_startup():
    try:
        conn = _db_conn()
        conn.close()
    except Exception:
        pass

@app.post("/preprocess", response_model=PreprocessResponse)
async def preprocess(body: PreprocessRequest):
    """第一次 Alt/Shift+Enter 预处理：调用整理Agent/Team（占位）
    - 现阶段：直接回显；后续接入 Autogen Team + 模板校验
    """
    trace_id = _new_trace()
    # 强制采用外部脚本运行机制（不再走内部 autogen_runner）
    raw = external_runner.external_preprocess(
        topic_id=body.topic_id,
        raw_md=body.raw_md,
        mode=body.mode,
        agent_config_path=body.agent_config_path,
    )
    content = str(raw)
    # 统一保证存在预处理标记（external 路径也加标记）
    try:
        has_marker = any((ln.strip().startswith('> 预处理 ·') for ln in (content or '').splitlines()))
    except Exception:
        has_marker = False
    if not has_marker:
        content = (content or '').rstrip() + "\n\n> 预处理 · 本地占位（未启用Agent）\n"
    markdown = ensure_structured_markdown(content, mode=body.mode)
    return PreprocessResponse(trace_id=trace_id, markdown=content)

@app.post("/submit", response_model=SubmitResponse)
async def submit(body: SubmitRequest):
    """第二次 Alt+Enter：落库或查询（占位）
    - note/search: 写入 DB（内存假库）
    - qa: 先生成占位答案，再写入
    """
    trace_id = _new_trace()
    # 强制外部脚本提交流程
    content = external_runner.external_submit(
        topic_id=body.topic_id,
        final_md=body.final_md,
        mode=body.mode,
        team_config_path=body.team_config_path,
        policy=(body.policy.model_dump() if body.policy else {}),
    )
    content = ensure_structured_markdown(content, mode=body.mode)
    note_id = uuid.uuid4().hex
    # 仅写入 DB（无降级）
    _db_insert_note(note_id, body.topic_id, content)
    # 策略三写入队（Vector/GraphRAG）
    try:
        policy_dict = body.policy.model_dump() if body.policy else {}
    except Exception:
        policy_dict = {}
    _enqueue_tri_write(body.topic_id, note_id, body.mode, policy_dict)
    return SubmitResponse(
        trace_id=trace_id,
        note_id=note_id,
        db_status="done",
        enqueue_vector="queued" if (body.policy and body.policy.index_vector == 1) else "skipped",
        enqueue_graphrag="queued" if (body.policy and body.policy.index_graphrag == 1) else "skipped",
    )

# 明确入库接口：会话项点击“入库”时调用（不依赖 Alt+Enter 自动入库）
@app.post("/notes/store", response_model=SubmitResponse)
async def store_note(body: SubmitRequest):
    trace_id = _new_trace()
    # 直接按外部脚本提交流程（保持与 submit 一致的落库效果）
    content = external_runner.external_submit(
        topic_id=body.topic_id,
        final_md=body.final_md,
        mode=body.mode,
        team_config_path=body.team_config_path,
        policy=(body.policy.model_dump() if body.policy else {}),
    )
    content = ensure_structured_markdown(content, mode=body.mode)
    note_id = uuid.uuid4().hex
    # 仅写入 DB（无降级）
    _db_insert_note(note_id, body.topic_id, content)
    try:
        policy_dict = body.policy.model_dump() if body.policy else {}
    except Exception:
        policy_dict = {}
    _enqueue_tri_write(body.topic_id, note_id, body.mode, policy_dict)
    return SubmitResponse(
        trace_id=trace_id,
        note_id=note_id,
        db_status="done",
        enqueue_vector="queued" if (body.policy and body.policy.index_vector == 1) else "skipped",
        enqueue_graphrag="queued" if (body.policy and body.policy.index_graphrag == 1) else "skipped",
    )

@app.post("/ingest", response_model=IngestResponse)
async def ingest(
    topic_id: str = Form(...),
    file: UploadFile = File(...),
):
    """附件原样归档（占位）：写 documents 列表并返回 document_id
    后续接入存储后端与 DB 指针登记，并按策略决定是否入向量/GraphRAG
    """
    document_id = uuid.uuid4().hex
    _FAKE_DB["documents"].append({
        "document_id": document_id,
        "topic_id": topic_id,
        "origin_filename": file.filename,
        "mime_type": file.content_type,
        "size": None,
    })
    return IngestResponse(trace_id=_new_trace(), document_id=document_id)

@app.get("/export/topic/{topic_id}", response_model=ExportTopicResponse)
async def export_topic(topic_id: str):
    """导出议题：返回 markdown 与空的附件清单（占位）"""
    notes = _db_query_notes_by_topic(topic_id)
    notes_sorted = list(notes)
    lines = [f"# 议题：{topic_id}", ""]
    for idx, n in enumerate(notes_sorted, start=1):
        lines.append(f"## 笔记 {idx}")
        lines.append("")
        lines.append(n["content"])  # noqa
        lines.append("")
    return ExportTopicResponse(topic_id=topic_id, markdown="\n".join(lines), attachments=[])

def _normalize_text(s: str) -> str:
    try:
        import re
        if not isinstance(s, str):
            return ""
        s = re.sub(r"`+", "", s)
        s = re.sub(r"^#+\\s*", "", s, flags=re.MULTILINE)
        s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "", s)
        return s.strip().lower()
    except Exception:
        return (s or "").strip().lower() if isinstance(s, str) else ""


# 测试入库校验（不入库）：内联校验，避免外部子进程与超时
@app.post("/test/validate", response_model=TestValidateResponse)
async def test_validate(body: TestValidateRequest):
    trace_id = _new_trace()
    try:
        # 1) 导出 markdown（内联调用函数，避免HTTP网络与子进程）
        export = await export_topic(body.topic_id)  # type: ignore
        md = export.markdown if hasattr(export, "markdown") else ""
        # 2) 宽松匹配
        ok_export = False
        if body.expect:
            norm_expect = _normalize_text(body.expect)
            norm_md = _normalize_text(md)
            if norm_expect and norm_md:
                ok_export = norm_expect in norm_md
            if not ok_export:
                ok_export = body.expect in md
        else:
            ok_export = bool(md and md.strip())

        # 3) 数据库校验：必须命中 DB 记录
        db_hit = False
        try:
            with _db_conn() as conn:
                cur = conn.execute("SELECT 1 FROM notes WHERE note_id=? LIMIT 1", (str(body.note_id),))
                db_hit = cur.fetchone() is not None
        except Exception:
            db_hit = False

        # 4) 读取 DB 实际内容（用于报告展示）
        db_content = ""
        try:
            with _db_conn() as conn:
                cur = conn.execute("SELECT content FROM notes WHERE note_id=? LIMIT 1", (str(body.note_id),))
                row = cur.fetchone()
                if row and isinstance(row[0], str):
                    db_content = row[0]
        except Exception:
            db_content = ""

        # 5) 生成报告
        lines = []
        lines.append("# 入库校验报告")
        lines.append("")
        lines.append(f"- 主题 Topic ID: `{body.topic_id}`")
        lines.append(f"- 笔记 Note ID: `{body.note_id}`")
        lines.append(f"- 期望片段: `{(body.expect or '')}`")
        lines.append("")
        lines.append(f"- 导出检查(仅DB): {'✅ 通过' if ok_export else '❌ 未通过'}")
        lines.append(f"- 数据库记录: {'✅ 存在' if db_hit else '❌ 未找到'}")
        lines.append("")
        overall = ok_export and db_hit
        lines.append(f"**结论：{'通过' if overall else '未通过'}**")
        # 附：DB 实际读取内容
        lines.append("")
        lines.append("## DB 实际读取内容")
        lines.append("")
        # 使用 fenced code block，避免渲染问题
        safe = db_content if isinstance(db_content, str) else ""
        lines.append("```markdown")
        lines.append(safe)
        lines.append("```")
        return TestValidateResponse(trace_id=trace_id, ok=overall, report_markdown="\n".join(lines))
    except Exception as e:
        return TestValidateResponse(trace_id=trace_id, ok=False, report_markdown=f"# 入库校验失败\n\n- 错误：{e}")

# 健康检查
@app.get("/healthz")
async def health():
    return {"status": "ok"}

@app.get("/meta")
async def meta():
    return {
        "message": "AutoGen Notes Backend is running",
        "version": "0.7.1",
        "framework": "AutoGen 0.7.1",
        "environment": "Docker Container",
        "endpoints": {
            "health": "/healthz",
            "preprocess": "/preprocess",
            "submit": "/submit",
            "ingest": "/ingest",
            "export": "/export/topic/{topic_id}",
            "test": "/test/validate"
        }
    }

# OpenAI 兼容端点（用于本地直连兜底）：/chat/completions
# 注意：仅用于开发与调试，生产请接入真实模型服务
@app.post("/chat/completions")
async def chat_completions(payload: dict):
    try:
        model = str(payload.get("model") or "mock-model")
        messages = payload.get("messages") or []
        user_text = ""
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                user_text = str(m.get("content") or "")
        stamp = int(time.time())
        content = f"# 结果整理\n\n> backend-mock · model={model}\n\n" + user_text
        return {
            "id": "chatcmpl-backend-mock",
            "object": "chat.completion",
            "created": stamp,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"bad request: {e}")

# 静默处理浏览器自动探测与站点图标，避免噪音 404
@app.get("/.well-known/{path:path}")
async def well_known(path: str):
    return Response(status_code=204)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

# 放在所有 API 路由之后，以避免路由冲突
app.mount("/", StaticFiles(directory=str(Path(__file__).resolve().parents[2] / "web"), html=True), name="static")

