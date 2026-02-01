"""SubagentStart/Stopイベントハンドラ

settings.jsonのSubagentStart/SubagentStopフックから呼び出される。
SubagentMarkerManagerを使用してマーカーファイルのCRUDを行う。
処理をブロックしないよう終了コード0で終了する。
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.services.subagent_marker_manager import SubagentMarkerManager
from shared.structured_logging import StructuredLogger, DEFAULT_LOG_DIR

# モジュールレベルのロガー
_logger = StructuredLogger(name="SubagentEventHook", log_dir=DEFAULT_LOG_DIR)


def main():
    """メインエントリーポイント"""
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
    elif event_name == "SubagentStop":
        manager.delete_marker(agent_id)
        _logger.info(f"Marker deleted: session={session_id}, agent={agent_id}")
    else:
        _logger.warning(f"Unknown event: {event_name}")

    # 処理をブロックしない
    sys.exit(0)


if __name__ == "__main__":
    main()
