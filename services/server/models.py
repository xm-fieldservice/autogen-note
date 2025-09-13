from typing import Optional, List, Literal, Dict
from pydantic import BaseModel, Field

Mode = Literal["note", "search", "qa"]

class PolicyFields(BaseModel):
    index_vector: Optional[int] = Field(default=0)
    index_graphrag: Optional[int] = Field(default=0)
    knowledge_base: Optional[str] = None
    retention_ttl_days: Optional[int] = None
    is_hard_knowledge: Optional[int] = None
    tags: Optional[List[str]] = None

class PreprocessRequest(BaseModel):
    topic_id: str
    raw_md: str
    mode: Mode = "note"
    agent_config_path: Optional[str] = None

class PreprocessResponse(BaseModel):
    trace_id: str
    markdown: str

class SubmitRequest(BaseModel):
    topic_id: str
    final_md: str
    mode: Mode = "note"
    team_config_path: Optional[str] = None
    policy: Optional[PolicyFields] = None

class SubmitResponse(BaseModel):
    trace_id: str
    note_id: str
    db_status: Literal["queued", "done", "skipped"] = "queued"
    enqueue_vector: Literal["queued", "skipped"] = "skipped"
    enqueue_graphrag: Literal["queued", "skipped"] = "skipped"

class IngestRequest(BaseModel):
    topic_id: str
    file_name: str
    mime_type: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    storage_backend: Optional[str] = None
    storage_uri: Optional[str] = None
    policy: Optional[PolicyFields] = None

class IngestResponse(BaseModel):
    trace_id: str
    document_id: str

class ExportTopicResponse(BaseModel):
    topic_id: str
    markdown: str
    attachments: List[Dict] = []


class TestValidateRequest(BaseModel):
    topic_id: str
    note_id: str
    expect: Optional[str] = None
    api_base: Optional[str] = None


class TestValidateResponse(BaseModel):
    trace_id: str
    ok: bool
    report_markdown: str
