"""SubagentStart/Stopイベントハンドラ

settings.jsonのSubagentStart/SubagentStopフックから呼び出される。
SubagentRepositoryを使用してDB操作を行う。
処理をブロックしないよう終了コード0で終了する。
"""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from infrastructure.db import NaggerStateDB, SubagentRepository
from shared.structured_logging import StructuredLogger, DEFAULT_LOG_DIR

# モジュールレベルのロガー
_logger = StructuredLogger(name="SubagentEventHook", log_dir=DEFAULT_LOG_DIR)




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

        # DB Repository初期化
        db = NaggerStateDB(NaggerStateDB.resolve_db_path())
        repo = SubagentRepository(db)

        if event_name == "SubagentStart":
            agent_type = agent_type or "unknown"

            # leader_transcript_path: SubagentStartはleaderコンテキストで発火するため、
            # ここでのtranscript_pathはleaderのもの（issue_6057: leader/subagent区別用）
            leader_transcript_path = data.get("transcript_path")

            # subagent登録（leader_transcript_path保存）
            repo.register(agent_id, session_id, agent_type,
                          leader_transcript_path=leader_transcript_path)
            _logger.info(
                f"Subagent registered: session={session_id}, agent={agent_id}, "
                f"type={agent_type}, leader_transcript={leader_transcript_path}"
            )

            # 親セッションのtranscriptからtask_spawnsを登録（共通フィールド）
            transcript_path = leader_transcript_path
            if transcript_path:
                try:
                    count = repo.register_task_spawns(session_id, transcript_path)
                    _logger.info(f"Task spawns registered: {count} new entries")

                    # agent_progressベースの正確なマッチング試行（issue_5947）
                    role = repo.match_task_to_agent(
                        session_id, agent_id, agent_type, transcript_path=transcript_path
                    )
                    if role:
                        _logger.info(f"Role matched from task_spawns: {role}")
                except Exception as e:
                    _logger.error(f"Failed to process task_spawns: {e}")

        elif event_name == "SubagentStop":
            repo.unregister(agent_id)
            _logger.info(f"Subagent unregistered: session={session_id}, agent={agent_id}")
        else:
            _logger.warning(f"Unknown event: {event_name}")

        # DB接続クローズ
        db.close()

        # 処理をブロックしない
        sys.exit(0)

    except Exception as e:
        # 予期せぬ例外がstderrに漏れてClaude Codeの動作に影響しないようにする
        _logger.exception(f"Unexpected error: {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
