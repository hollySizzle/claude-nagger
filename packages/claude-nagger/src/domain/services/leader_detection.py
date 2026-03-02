"""leader判定ユーティリティ（transcript解析ベース）"""

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def is_leader_tool_use(transcript_path: str, tool_use_id: str) -> bool:
    """main transcriptに指定tool_use_idが存在するか判定（issue_6952）

    PreToolUseのtool_use_idがleader（親）のtranscript内に存在すれば
    leaderのtool呼び出し、存在しなければsubagentのtool呼び出しと判定。
    フォールバック: 見つからない場合はFalse（subagent扱い=安全側）
    """
    path = Path(transcript_path)
    if not path.exists():
        _logger.warning(f"is_leader_tool_use: transcript not found: {transcript_path}")
        return False  # フォールバック: subagent扱い

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
                # 全ツール種別対象（Task以外もBash, Read等含む）
                if content_item.get("id") == tool_use_id:
                    return True

    return False


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
