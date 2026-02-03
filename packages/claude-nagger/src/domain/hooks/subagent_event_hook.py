"""SubagentStart/Stopイベントハンドラ

settings.jsonのSubagentStart/SubagentStopフックから呼び出される。
SubagentMarkerManagerを使用してマーカーファイルのCRUDを行う。
処理をブロックしないよう終了コード0で終了する。
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.services.subagent_marker_manager import SubagentMarkerManager
from shared.structured_logging import StructuredLogger, DEFAULT_LOG_DIR

# モジュールレベルのロガー
_logger = StructuredLogger(name="SubagentEventHook", log_dir=DEFAULT_LOG_DIR)


def _parse_role_from_transcript(transcript_path: str) -> Optional[str]:
    """トランスクリプトJSONLから[ROLE:xxx]パターンを抽出

    2つのパターンを検索:
    1. 最初のuserメッセージ（subagent自身のtranscript）
    2. 最後のTask tool_useのprompt（親セッションtranscript）

    Args:
        transcript_path: トランスクリプトJSONLファイルパス

    Returns:
        抽出されたロール文字列、未検出時はNone
    """
    if not transcript_path:
        return None

    try:
        path = Path(transcript_path)
        if not path.exists():
            _logger.debug(f"Transcript file not found: {transcript_path}")
            return None

        role_from_user = None
        role_from_task = None
        first_user_seen = False

        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get('type', '')

                # パターン1: 最初のuserメッセージ
                if entry_type == 'user' and not first_user_seen:
                    first_user_seen = True
                    message = entry.get('message', {})
                    content = message.get('content', '')

                    # contentがリストの場合（複数ブロック）はテキスト部分を結合
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                text_parts.append(block.get('text', ''))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        content = '\n'.join(text_parts)

                    match = re.search(r'\[ROLE:(\w+)\]', content)
                    if match:
                        role_from_user = match.group(1)

                # パターン2: assistant内のTask tool_use prompt
                if entry_type == 'assistant':
                    message = entry.get('message', {})
                    content = message.get('content', [])
                    if isinstance(content, list):
                        for block in content:
                            if (isinstance(block, dict)
                                and block.get('type') == 'tool_use'
                                and block.get('name') == 'Task'):
                                prompt = block.get('input', {}).get('prompt', '')
                                match = re.search(r'\[ROLE:(\w+)\]', prompt)
                                if match:
                                    role_from_task = match.group(1)

        # userメッセージ優先（subagent自身のtranscriptの場合）
        # Task tool_useはフォールバック（親transcriptの場合）
        result = role_from_user or role_from_task
        if result:
            _logger.info(f"Parsed role from transcript: {result}")
        return result

    except Exception as e:
        _logger.error(f"Error parsing role from transcript: {e}")

    return None


def main():
    """メインエントリーポイント"""
    try:
        _logger.info("SubagentEventHook invoked")

        try:
            raw = sys.stdin.read()
            _logger.info(f"stdin raw length: {len(raw)}")
            _logger.debug(f"stdin raw content: {raw[:500]}")
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            # JSON解析失敗時はスキップ
            _logger.error(f"JSON decode error: {e}, raw: {raw[:200]}")
            sys.exit(0)

        event_name = data.get("hook_event_name", "")
        session_id = data.get("session_id", "")
        agent_id = data.get("agent_id", "")
        agent_type = data.get("agent_type", "")

        _logger.info(
            f"Event: {event_name}, session_id: {session_id}, "
            f"agent_id: {agent_id}, agent_type: {agent_type}"
        )
        _logger.info(f"Input data keys: {list(data.keys())}")

        if not session_id or not agent_id:
            _logger.warning(
                f"Missing required fields - session_id: '{session_id}', agent_id: '{agent_id}'"
            )
            sys.exit(0)

        manager = SubagentMarkerManager(session_id)

        if event_name == "SubagentStart":
            agent_type = agent_type or "unknown"
            manager.create_marker(agent_id, agent_type)
            _logger.info(
                f"Marker created: session={session_id}, agent={agent_id}, type={agent_type}"
            )

            # agent_transcript_pathからROLEを解析してマーカーに保存
            agent_transcript_path = data.get("agent_transcript_path")
            if agent_transcript_path:
                try:
                    role = _parse_role_from_transcript(agent_transcript_path)
                    if role:
                        manager.update_marker(agent_id, role=role)
                        _logger.info(f"Role updated: agent={agent_id}, role={role}")
                except Exception as e:
                    _logger.error(f"Failed to parse role from transcript: {e}")
        elif event_name == "SubagentStop":
            manager.delete_marker(agent_id)
            _logger.info(f"Marker deleted: session={session_id}, agent={agent_id}")
        else:
            _logger.warning(f"Unknown event: {event_name}")

        # 処理をブロックしない
        sys.exit(0)

    except Exception as e:
        # 予期せぬ例外がstderrに漏れてClaude Codeの動作に影響しないようにする
        _logger.exception(f"Unexpected error: {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
