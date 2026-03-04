"""leader判定ユーティリティ（transcript解析ベース）"""

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def is_leader_tool_use(transcript_path: str) -> bool:
    """coygeek方式: Task tool_use有無でleader判定（issue_7312）

    transcriptを走査し、Task tool_useの存在を確認。
    Task tool_useが1つでも存在すればsubagentが起動済み → False（非leader）。
    Task tool_useが不在 → leader単独 → True。

    Args:
        transcript_path: main transcript（.jsonl）のパス

    Returns:
        True: leader（Task tool_useなし）
        False: 非leader（Task tool_useあり）

    フォールバック方針:
        - transcript未存在/読み込みエラー → False（安全側=subagent扱い）
          理由: ファイル不在は異常状態のためleader誤判定リスク回避
        - 空transcript → True（leader）
          理由: セッション開始直後でツール未使用=leader単独作業の正常状態

    制約:
        - tool_use_idを使わないため、呼び出し元の特定は不可
        - leader自身もTask tool_useを発行するため、leaderのPreToolUseでもFalse返却
        - 複数subagent環境でどのsubagentかは識別不可
    """
    path = Path(transcript_path)
    if not path.exists():
        _logger.warning(f"is_leader_tool_use: transcript未発見: {transcript_path}")
        return False  # フォールバック: subagent扱い（異常状態のためleader誤判定を回避）

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                message = entry.get("message", {})
                for content_item in message.get("content", []):
                    if content_item.get("type") != "tool_use":
                        continue
                    if content_item.get("name") == "Task":
                        _logger.info(
                            f"is_leader_tool_use: Task tool_use発見 "
                            f"id={content_item.get('id')} → 非leader"
                        )
                        return False
    except (OSError, IOError) as e:
        _logger.warning(f"is_leader_tool_use: ファイル読み込みエラー: {e}")
        return False

    _logger.info("is_leader_tool_use: Task tool_use不在 → leader")
    return True


from typing import Optional


def find_caller_agent_id(transcript_path: str, tool_use_id: str) -> Optional[str]:
    """subagentsディレクトリからtool_use_idを持つagentのIDを特定する

    各agent-{UUID}.jsonlを走査し、tool_use_idが一致するエントリを検索。
    ヒット時はUUIDを返却、未ヒット時はNone（安全側フォールバック）。
    """
    subagents_dir = Path(transcript_path).parent / "subagents"
    if not subagents_dir.exists() or not subagents_dir.is_dir():
        _logger.info(f"find_caller_agent_id: subagentsディレクトリ不在: {subagents_dir}")
        return None

    for agent_file in subagents_dir.glob("agent-*.jsonl"):
        try:
            with open(agent_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "assistant":
                        continue
                    message = entry.get("message", {})
                    for content_item in message.get("content", []):
                        if content_item.get("type") != "tool_use":
                            continue
                        if content_item.get("id") == tool_use_id:
                            # ファイル名からagent_idを抽出: agent-{UUID}.jsonl → UUID
                            agent_id = agent_file.stem.removeprefix("agent-")
                            _logger.info(f"find_caller_agent_id: tool_use_id={tool_use_id} → agent_id={agent_id}")
                            return agent_id
        except (OSError, IOError) as e:
            _logger.warning(f"find_caller_agent_id: ファイル読み込みエラー: {agent_file}: {e}")
            continue

    _logger.info(f"find_caller_agent_id: tool_use_id={tool_use_id} に該当するagent未発見")
    return None
