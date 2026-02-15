"""SubagentStart/Stopイベントハンドラ

settings.jsonのSubagentStart/SubagentStopフックから呼び出される。
SubagentRepositoryを使用してDB操作を行う。
処理をブロックしないよう終了コード0で終了する。
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

sys.path.append(str(Path(__file__).parent.parent.parent))

from infrastructure.db import NaggerStateDB, SubagentRepository
from shared.structured_logging import StructuredLogger, DEFAULT_LOG_DIR

# モジュールレベルのロガー
_logger = StructuredLogger(name="SubagentEventHook", log_dir=DEFAULT_LOG_DIR)


def _load_transcript_storage_config() -> dict:
    """config.yamlからtranscript_storage設定を読み込む

    探索順序:
    1. CLAUDE_PROJECT_DIR環境変数
    2. パッケージルート（__file__から算出）
    3. Path.cwd()
    """
    candidates = []

    # 1. CLAUDE_PROJECT_DIR
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        candidates.append(Path(project_dir) / ".claude-nagger" / "config.yaml")

    # 2. パッケージルート（src/domain/hooks/ → 3階層上がpackage root）
    package_root = Path(__file__).resolve().parent.parent.parent.parent
    candidates.append(package_root / ".claude-nagger" / "config.yaml")

    # 3. cwd
    try:
        cwd_candidate = Path.cwd() / ".claude-nagger" / "config.yaml"
        if cwd_candidate not in candidates:
            candidates.append(cwd_candidate)
    except OSError:
        pass

    for config_path in candidates:
        if config_path.exists():
            _logger.info(f"config.yaml発見: {config_path}")
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                return data.get('transcript_storage', {}) if data else {}
            except Exception as e:
                _logger.warning(f"設定ファイル読み込み失敗: {e}")
                return {}

    _logger.info(f"config.yaml未発見: 探索パス={[str(c) for c in candidates]}")
    return {}


def _launch_subagent_transcript_storage(
    agent_id: str, agent_transcript_path: str
) -> None:
    """subagentトランスクリプトのバックグラウンド格納を起動（issue_6184）

    agent_transcript_pathのファイル名（拡張子除去）をsession_idとして使用し、
    transcript_storage_hookのrun_background_storage()をnohup起動する。

    Args:
        agent_id: subagentのエージェントID
        agent_transcript_path: subagentのトランスクリプトファイルパス
    """
    config = _load_transcript_storage_config()
    if not config.get('enabled', False):
        _logger.info("transcript_storage無効、subagentトランスクリプト格納スキップ")
        return

    transcript_file = Path(agent_transcript_path)
    if not transcript_file.exists():
        _logger.info(f"トランスクリプトファイル不在: {agent_transcript_path}")
        return

    # session_id: ファイル名から拡張子を除去
    subagent_session_id = transcript_file.stem
    mode = config.get("mode", "raw")

    python_exec = sys.executable
    module_path = "domain.hooks.transcript_storage_hook"
    cmd = [
        "nohup", python_exec, "-m", module_path,
        "--background",
        "--session-id", subagent_session_id,
        "--transcript-path", agent_transcript_path,
        "--mode", mode,
    ]
    env = os.environ.copy()
    # PYTHONPATHにsrcディレクトリを追加
    src_dir = str(Path(__file__).resolve().parent.parent.parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}:{existing}" if existing else src_dir

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        _logger.info(
            f"subagentトランスクリプト格納起動: session={subagent_session_id}, "
            f"mode={mode}, path={agent_transcript_path}"
        )
    except Exception as e:
        _logger.error(f"subagentトランスクリプト格納起動失敗: {e}")


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
            # agent_transcript_path: subagent自身のトランスクリプトパス（issue_6184）
            agent_transcript_path = data.get("agent_transcript_path")
            _logger.info(
                f"SubagentStop: agent_transcript_path={agent_transcript_path}"
            )

            repo.unregister(agent_id, agent_transcript_path=agent_transcript_path)
            _logger.info(f"Subagent unregistered: session={session_id}, agent={agent_id}")

            # subagentトランスクリプトのバックグラウンド格納（issue_6184）
            if agent_transcript_path:
                _launch_subagent_transcript_storage(
                    agent_id, agent_transcript_path
                )
            else:
                _logger.info(
                    "agent_transcript_path未提供、トランスクリプト格納スキップ"
                )
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
