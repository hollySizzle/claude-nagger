"""構造化ログ（JSON形式）モジュール

Claude Codeとの連携、トラブルシューティング効率化のための
構造化ログ機能を提供。

特徴:
- JSON形式でパース可能
- 出力先統一（/tmp/claude-nagger-{uid}/）
- デバッグモード検出（CLAUDE_CODE_DEBUG環境変数）
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# 統一ログディレクトリ（ユーザー固有パスで権限競合を回避）
DEFAULT_LOG_DIR = Path(f"/tmp/claude-nagger-{os.getuid()}")


def is_debug_mode() -> bool:
    """デバッグモード検出

    以下の条件でデバッグモードと判定:
    - CLAUDE_CODE_DEBUG環境変数が"true"
    - CLAUDE_NAGGER_DEBUG環境変数が"true"

    Returns:
        デバッグモードの場合True
    """
    claude_debug = os.environ.get('CLAUDE_CODE_DEBUG', '').lower() == 'true'
    nagger_debug = os.environ.get('CLAUDE_NAGGER_DEBUG', '').lower() == 'true'
    return claude_debug or nagger_debug


class StructuredFormatter(logging.Formatter):
    """JSON形式の構造化ログフォーマッター"""

    def __init__(self, include_extras: bool = True):
        """
        Args:
            include_extras: 追加フィールドを含めるか
        """
        super().__init__()
        self.include_extras = include_extras

    def format(self, record: logging.LogRecord) -> str:
        """ログレコードをJSON形式にフォーマット"""
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # ファイル・行番号情報（デバッグ時有用）
        if is_debug_mode():
            log_entry["source"] = {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
            }

        # 例外情報
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 追加フィールド（extra引数で渡されたもの）
        if self.include_extras:
            extras = {}
            for key, value in record.__dict__.items():
                if key not in {
                    'name', 'msg', 'args', 'created', 'filename', 'funcName',
                    'levelname', 'levelno', 'lineno', 'module', 'msecs',
                    'pathname', 'process', 'processName', 'relativeCreated',
                    'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
                    'message', 'taskName'
                }:
                    # JSON直列化可能かチェック
                    try:
                        json.dumps(value)
                        extras[key] = value
                    except (TypeError, ValueError):
                        extras[key] = str(value)

            if extras:
                log_entry["context"] = extras

        return json.dumps(log_entry, ensure_ascii=False)


class StructuredLogger:
    """構造化ログ出力クラス

    JSON形式でログを出力し、以下の機能を提供:
    - ファイル出力（JSONL形式）
    - 統一ログディレクトリ
    - デバッグモード対応
    - 入力JSONの保存
    """

    def __init__(
        self,
        name: str,
        log_dir: Optional[Path] = None,
        session_id: Optional[str] = None,
    ):
        """
        Args:
            name: ロガー名（通常はクラス名）
            log_dir: ログ出力ディレクトリ（デフォルト: /tmp/claude-nagger-{uid}）
            session_id: セッションID（ファイル名に使用）
        """
        self.name = name
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.session_id = session_id
        self._debug_mode = is_debug_mode()

        # ディレクトリ作成
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 標準ロガー設定
        self._logger = logging.getLogger(f"claude_nagger.{name}")
        self._setup_handlers()

    def _get_log_file_path(self) -> Path:
        """ログファイルパスを取得"""
        if self.session_id:
            return self.log_dir / f"{self.session_id}.jsonl"
        return self.log_dir / "claude_nagger.jsonl"

    def _setup_handlers(self):
        """ハンドラー設定"""
        # 既存ハンドラーをクリア
        self._logger.handlers.clear()

        # レベル設定
        self._logger.setLevel(logging.DEBUG if self._debug_mode else logging.INFO)

        # ファイルハンドラー（常に有効）
        log_file = self._get_log_file_path()
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(StructuredFormatter())
        file_handler.setLevel(logging.DEBUG)
        self._logger.addHandler(file_handler)

        # デバッグモード時はstderrにも出力（Claude Codeの--debugで表示）
        if self._debug_mode:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setFormatter(StructuredFormatter())
            stderr_handler.setLevel(logging.DEBUG)
            self._logger.addHandler(stderr_handler)

    def set_session_id(self, session_id: str):
        """セッションIDを設定（ログファイル名変更）"""
        self.session_id = session_id
        self._setup_handlers()

    def debug(self, message: str, **extra):
        """デバッグログ"""
        self._logger.debug(message, extra=extra)

    def info(self, message: str, **extra):
        """情報ログ"""
        self._logger.info(message, extra=extra)

    def warning(self, message: str, **extra):
        """警告ログ"""
        self._logger.warning(message, extra=extra)

    def error(self, message: str, **extra):
        """エラーログ"""
        self._logger.error(message, extra=extra)

    def exception(self, message: str, **extra):
        """例外ログ（スタックトレース付き）"""
        self._logger.exception(message, extra=extra)

    def save_input_json(self, raw_json: str, prefix: str = "input") -> Optional[Path]:
        """入力JSONを保存

        Args:
            raw_json: 生のJSONテキスト
            prefix: ファイル名プレフィックス

        Returns:
            保存先パス（失敗時None）
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            session_part = f"_{self.session_id}" if self.session_id else ""
            filename = f"{prefix}{session_part}_{timestamp}.json"
            filepath = self.log_dir / filename

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(raw_json)

            self.debug(f"Input JSON saved", path=str(filepath), size=len(raw_json))
            return filepath

        except Exception as e:
            self.error(f"Failed to save input JSON", error=str(e))
            return None

    def log_hook_event(
        self,
        event_type: str,
        hook_name: str,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **extra
    ):
        """フックイベントログ（構造化）

        Args:
            event_type: イベント種別（start, end, skip, block等）
            hook_name: フック名
            decision: 決定（allow, deny, ask等）
            reason: 理由
            duration_ms: 処理時間（ミリ秒）
            **extra: 追加情報
        """
        log_data = {
            "event_type": event_type,
            "hook_name": hook_name,
        }

        if decision:
            log_data["decision"] = decision
        if reason:
            log_data["reason"] = reason
        if duration_ms is not None:
            log_data["duration_ms"] = round(duration_ms, 2)

        log_data.update(extra)

        self.info(f"Hook event: {event_type}", **log_data)

    @property
    def is_debug(self) -> bool:
        """デバッグモードか"""
        return self._debug_mode


def get_logger(name: str, session_id: Optional[str] = None) -> StructuredLogger:
    """ロガー取得ユーティリティ

    Args:
        name: ロガー名
        session_id: セッションID

    Returns:
        StructuredLoggerインスタンス
    """
    return StructuredLogger(name=name, session_id=session_id)
