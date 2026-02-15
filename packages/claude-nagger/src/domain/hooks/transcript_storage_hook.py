"""Stop hook: セッション終了時にトランスクリプトをDBに格納"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from domain.hooks.base_hook import BaseHook
from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.transcript_repository import TranscriptRepository

logger = logging.getLogger(__name__)


class TranscriptStorageHook(BaseHook):
    """Stop hook: セッション終了時に.jsonlトランスクリプトをSQLiteに格納

    フロー:
      1. config.yamlのtranscript_storage.enabled確認
      2. enabled→バックグラウンドプロセス起動（セッション終了をブロックしない）
      3. hook自体は即座にexit 0
    """

    def __init__(self):
        """初期化"""
        super().__init__(debug=True)
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """config.yamlからtranscript_storage設定を読み込む"""
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        if project_dir:
            config_path = Path(project_dir) / ".claude-nagger" / "config.yaml"
        else:
            config_path = Path.cwd() / ".claude-nagger" / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            return data.get('transcript_storage', {}) if data else {}
        except Exception as e:
            logger.warning(f"設定ファイル読み込み失敗: {e}")
            return {}

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """transcript_storage.enabled設定を確認"""
        if not self._config.get('enabled', False):
            self.log_info("transcript_storage機能が無効化されています (enabled: false)")
            return False

        transcript_path = input_data.get('transcript_path')
        if not transcript_path:
            self.log_info("transcript_pathが未指定、スキップ")
            return False

        if not Path(transcript_path).exists():
            self.log_info(f"トランスクリプトファイル不在: {transcript_path}")
            return False

        self.log_info("transcript_storage処理を開始")
        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """バックグラウンドプロセスを起動して即座に終了"""
        transcript_path = input_data.get('transcript_path', '')
        session_id = input_data.get('session_id', '')

        self._launch_background(session_id, transcript_path)
        return {"decision": "approve", "reason": ""}

    def _launch_background(self, session_id: str, transcript_path: str) -> None:
        """バックグラウンド処理をnohup起動

        セッション終了をブロックしないよう、子プロセスを分離して起動。
        """
        mode = self._config.get("mode", "raw")
        python_exec = sys.executable
        module_path = "domain.hooks.transcript_storage_hook"
        cmd = [
            "nohup", python_exec, "-m", module_path,
            "--background",
            "--session-id", session_id,
            "--transcript-path", transcript_path,
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
            self.log_info("バックグラウンドプロセス起動完了")
        except Exception as e:
            self.log_error(f"バックグラウンドプロセス起動失敗: {e}")


def run_background_storage(session_id: str, transcript_path: str, mode: str = "raw") -> int:
    """バックグラウンド処理本体

    .jsonlトランスクリプトをSQLiteに格納する。

    Args:
        session_id: セッションID
        transcript_path: .jsonlファイルパス
        mode: 格納モード ("raw" | "indexed" | "structured")

    Returns:
        0: 成功, 1: エラー
    """
    try:
        db_path = NaggerStateDB.resolve_db_path()
        db = NaggerStateDB(db_path)
        db.connect()

        try:
            repo = TranscriptRepository(db, mode=mode)
            count = repo.store_transcript(session_id, transcript_path)
            logger.info(f"トランスクリプト格納完了: {count}行, mode={mode}")
            return 0
        finally:
            db.close()

    except Exception as e:
        logger.error(f"バックグラウンド処理エラー: {e}")
        return 1


def main():
    """エントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--background", action="store_true",
        help="バックグラウンド処理を実行",
    )
    parser.add_argument(
        "--session-id", default="",
        help="セッションID",
    )
    parser.add_argument(
        "--transcript-path", default="",
        help="トランスクリプトファイルパス",
    )
    parser.add_argument(
        "--mode", default="raw",
        choices=["raw", "indexed", "structured"],
        help="格納モード (raw/indexed/structured)",
    )
    args = parser.parse_args()

    if args.background:
        # バックグラウンド処理モード
        sys.exit(run_background_storage(
            session_id=args.session_id,
            transcript_path=args.transcript_path,
            mode=args.mode,
        ))
    else:
        # 通常のStop hookモード
        hook = TranscriptStorageHook()
        sys.exit(hook.run())


if __name__ == "__main__":
    main()
