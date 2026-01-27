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


def main():
    """メインエントリーポイント"""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        # JSON解析失敗時はスキップ
        sys.exit(0)

    event_name = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")
    agent_id = data.get("agent_id", "")

    if not session_id or not agent_id:
        sys.exit(0)

    manager = SubagentMarkerManager(session_id)

    if event_name == "SubagentStart":
        agent_type = data.get("agent_type", "unknown")
        manager.create_marker(agent_id, agent_type)
    elif event_name == "SubagentStop":
        manager.delete_marker(agent_id)

    # 処理をブロックしない
    sys.exit(0)


if __name__ == "__main__":
    main()
