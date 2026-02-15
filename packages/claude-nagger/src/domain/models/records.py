"""データモデル定義"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SubagentRecord:
    """サブエージェント情報レコード"""

    agent_id: str
    session_id: str
    agent_type: str
    role: Optional[str]
    role_source: Optional[str]
    created_at: str
    startup_processed: bool
    startup_processed_at: Optional[str]
    task_match_index: Optional[int]
    leader_transcript_path: Optional[str] = None


@dataclass
class SessionRecord:
    """セッション情報レコード"""

    session_id: str
    hook_name: str
    created_at: str
    last_tokens: int
    status: str
    expired_at: Optional[str]


@dataclass
class HookLogRecord:
    """フックログレコード"""

    id: int
    session_id: str
    hook_name: str
    event_type: str
    agent_id: Optional[str]
    timestamp: str
    result: Optional[str]
    details: Optional[str]
    duration_ms: Optional[int]


@dataclass
class TranscriptLineRecord:
    """トランスクリプト行レコード"""

    id: int
    session_id: str
    line_number: int
    line_type: str          # "user" | "assistant" | "progress" 等
    raw_json: str           # 生JSON文字列（raw mode）
    created_at: str
