"""フック処理の基底クラス"""

import json
import os
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from enum import IntEnum
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

try:
    from shared.permission_mode import (
        PermissionMode,
        PermissionModeBehavior,
        DEFAULT_MODE_BEHAVIORS,
    )
    from shared.structured_logging import (
        StructuredLogger,
        is_debug_mode,
        DEFAULT_LOG_DIR,
    )
except ImportError:
    from src.shared.permission_mode import (
        PermissionMode,
        PermissionModeBehavior,
        DEFAULT_MODE_BEHAVIORS,
    )
    from src.shared.structured_logging import (
        StructuredLogger,
        is_debug_mode,
        DEFAULT_LOG_DIR,
    )

if TYPE_CHECKING:
    from .hook_response import HookResponse


# ブロックメッセージの出所プレフィックス（ユーザー/AIが出所を判別可能にする）
BLOCK_MESSAGE_PREFIX = "[claude-nagger] "


def _prefix_block_reason(reason: str) -> str:
    """ブロック理由メッセージに出所プレフィックスを付与する（重複防止付き）"""
    if not reason:
        return reason
    if reason.startswith(BLOCK_MESSAGE_PREFIX):
        return reason
    return BLOCK_MESSAGE_PREFIX + reason


class ExitCode(IntEnum):
    """Claude Code Hooks API 終了コード

    終了コードの意味:
    - SUCCESS (0): 成功。stdoutのJSON出力が処理される
    - ERROR (1): ノンブロッキングエラー。stderr表示後も処理続行
    - BLOCK (2): ブロッキングエラー。stderrをClaudeへ表示し処理ブロック
    """
    SUCCESS = 0
    ERROR = 1
    BLOCK = 2



class MarkerPatterns:
    """マーカーパターン定義（一元管理）
    
    各フックで使用されるマーカーファイル名のパターンを一元管理。
    新しいマーカー追加時はここに定義を追加する。
    """
    
    # パターン定数（format文字列）
    SESSION_STARTUP = "claude_session_startup_{session_id}"
    HOOK_SESSION = "claude_hook_{class_name}_session_{session_id}"
    RULE = "claude_rule_{class_name}_{session_id}_{rule_hash}"
    COMMAND = "claude_cmd_{session_id}_{command_hash}"
    
    @classmethod
    def get_glob_patterns(cls, session_id: str) -> list[str]:
        """compact時のglob用パターンを取得
        
        Args:
            session_id: セッションID
            
        Returns:
            glob用パターンのリスト
        """
        return [
            f"claude_session_startup_*{session_id}*",   # SessionStartupHook
            f"claude_rule_*{session_id}*",              # 規約リマインダー
            f"claude_cmd_{session_id}_*",               # コマンド規約
            f"claude_hook_*_session_{session_id}",      # BaseHook汎用マーカー
        ]
    
    @classmethod
    def format_session_startup(cls, session_id: str) -> str:
        """SESSION_STARTUPパターンのフォーマット"""
        return cls.SESSION_STARTUP.format(session_id=session_id)
    
    @classmethod
    def format_hook_session(cls, class_name: str, session_id: str) -> str:
        """HOOK_SESSIONパターンのフォーマット"""
        return cls.HOOK_SESSION.format(class_name=class_name, session_id=session_id)
    
    @classmethod
    def format_rule(cls, class_name: str, session_id: str, rule_hash: str) -> str:
        """RULEパターンのフォーマット"""
        return cls.RULE.format(class_name=class_name, session_id=session_id, rule_hash=rule_hash)
    
    @classmethod
    def format_command(cls, session_id: str, command_hash: str) -> str:
        """COMMANDパターンのフォーマット"""
        return cls.COMMAND.format(session_id=session_id, command_hash=command_hash)

class BaseHook(ABC):
    """Claude Code Hook処理の基底クラス"""

    def __init__(self, log_dir: Optional[Path] = None, debug: Optional[bool] = None):
        """
        初期化

        Args:
            log_dir: ログ出力ディレクトリ（デフォルト: {tempdir}/claude-nagger-{uid}）
            debug: デバッグモードフラグ（Noneの場合は環境変数から自動検出）
        """
        # デバッグモード: 明示的指定 > 環境変数検出
        self.debug = debug if debug is not None else is_debug_mode()
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self._start_time: Optional[float] = None
        self._hook_event_name: Optional[str] = None
        self._setup_logging()

    def _setup_logging(self):
        """構造化ロギングの設定"""
        # 構造化ロガーを初期化（セッションIDは後で設定）
        self._structured_logger = StructuredLogger(
            name=self.__class__.__name__,
            log_dir=self.log_dir,
        )
        # 後方互換性のためlogger属性も維持
        self.logger = self._structured_logger

    @property
    def project_dir(self) -> Optional[str]:
        """CLAUDE_PROJECT_DIR環境変数からプロジェクトルートを取得

        Claude Codeが開始されたプロジェクトルートディレクトリへの絶対パス。
        設定されていない場合はNoneを返す。
        """
        return os.environ.get('CLAUDE_PROJECT_DIR')

    @property
    def is_remote(self) -> bool:
        """CLAUDE_CODE_REMOTE環境変数からリモート環境かどうかを判定

        リモート（web）環境の場合True、ローカルCLI環境の場合False。
        環境変数が"true"の場合のみTrueを返す。
        """
        return os.environ.get('CLAUDE_CODE_REMOTE', '').lower() == 'true'

    def get_permission_mode(self, input_data: Dict[str, Any]) -> PermissionMode:
        """入力データからpermission_modeを取得

        Args:
            input_data: 入力データ

        Returns:
            PermissionMode（不明な場合はUNKNOWN）
        """
        mode_str = input_data.get('permission_mode', '')
        mode = PermissionMode.from_string(mode_str)
        self.log_debug(f"Permission mode: {mode_str} -> {mode}")
        return mode

    def get_permission_mode_behavior(
        self,
        mode: PermissionMode,
        config_behaviors: Optional[Dict[str, str]] = None
    ) -> PermissionModeBehavior:
        """permission_modeに対応する挙動を取得

        設定ファイルからカスタム挙動を取得し、なければデフォルトを使用。

        Args:
            mode: PermissionMode
            config_behaviors: 設定ファイルのモード別挙動（オプション）

        Returns:
            PermissionModeBehavior
        """
        # 設定ファイルのカスタム挙動を優先
        if config_behaviors and mode.value in config_behaviors:
            behavior_str = config_behaviors[mode.value]
            try:
                return PermissionModeBehavior(behavior_str)
            except ValueError:
                self.log_debug(f"Invalid behavior config: {behavior_str}, using default")

        # デフォルト挙動
        return DEFAULT_MODE_BEHAVIORS.get(mode, PermissionModeBehavior.NORMAL)

    def should_skip_by_permission_mode(
        self,
        input_data: Dict[str, Any],
        config_behaviors: Optional[Dict[str, str]] = None
    ) -> tuple[bool, PermissionModeBehavior]:
        """permission_modeによりスキップすべきか判定

        Args:
            input_data: 入力データ
            config_behaviors: 設定ファイルのモード別挙動

        Returns:
            (スキップすべきか, 挙動)
        """
        mode = self.get_permission_mode(input_data)
        behavior = self.get_permission_mode_behavior(mode, config_behaviors)

        if behavior == PermissionModeBehavior.SKIP:
            self.log_info(f"Skipping due to permission_mode={mode.value}")
            return True, behavior

        return False, behavior

    def log_debug(self, message: str, **extra):
        """デバッグログ出力（構造化対応）"""
        self._structured_logger.debug(message, **extra)

    def log_info(self, message: str, **extra):
        """情報ログ出力（構造化対応）"""
        self._structured_logger.info(message, **extra)

    def log_error(self, message: str, **extra):
        """エラーログ出力（構造化対応）"""
        self._structured_logger.error(message, **extra)

    def log_warning(self, message: str, **extra):
        """警告ログ出力（構造化対応）"""
        self._structured_logger.warning(message, **extra)

    def _save_raw_json(self, raw_json: str) -> Optional[Path]:
        """生のJSONテキストを統一ログディレクトリに保存

        Returns:
            保存先パス（失敗時None）
        """
        return self._structured_logger.save_input_json(raw_json, prefix="hook_input")

    def read_input(self) -> Dict[str, Any]:
        """
        標準入力からJSON入力を読み取る

        Returns:
            入力データの辞書
        """
        try:
            input_data = sys.stdin.read()
            self.log_debug(f"Input JSON received", length=len(input_data))

            # 生のJSONテキストを保存（統一ログディレクトリ）
            self._save_raw_json(input_data)

            if not input_data:
                self.log_error("No input data received")
                return {}

            parsed = json.loads(input_data)

            # セッションIDが取得できたらロガーに設定
            session_id = parsed.get('session_id')
            if session_id:
                self._structured_logger.set_session_id(session_id)

            # イベント名を保持
            self._hook_event_name = parsed.get('hook_event_name')

            return parsed
        except json.JSONDecodeError as e:
            self.log_error(f"JSON decode error", error=str(e))
            return {}
        except Exception as e:
            self.log_error(f"Unexpected error reading input", error=str(e))
            return {}

    def output_response(self, decision: str, reason: str = "") -> bool:
        """
        JSON形式でレスポンスを出力（Claude Code公式スキーマ対応）

        Args:
            decision: 'approve', 'block' のいずれか
            reason: 理由メッセージ

        Returns:
            出力成功の場合True
        """
        try:
            event_name = self._hook_event_name or 'PreToolUse'

            # PreToolUseのみhookSpecificOutput形式（permissionDecision付き）
            if event_name == 'PreToolUse':
                perm_decision = 'allow' if decision == 'approve' else 'deny'
                # ブロック/deny時は出所プレフィックスを付与
                prefixed_reason = _prefix_block_reason(reason) if perm_decision == 'deny' else reason
                response = {
                    'hookSpecificOutput': {
                        'hookEventName': event_name,
                        'permissionDecision': perm_decision,
                        'permissionDecisionReason': prefixed_reason
                    }
                }
                json_output = json.dumps(response, ensure_ascii=False)
                print(json_output)
            else:
                # Stop/Notification等: hookSpecificOutput不要
                # 空出力でexit 0のみ
                json_output = "{}"
                self.log_debug(f"Non-PreToolUse event '{event_name}': skip hookSpecificOutput")

            self.log_debug(f"Output response: {json_output}")
            return True
        except Exception as e:
            self.log_error(f"Failed to output response: {e}")
            return False

    def exit_block(self, reason: str) -> None:
        """ブロッキングエラーで終了（終了コード2 + stderr）

        処理をブロックし、reasonをClaudeにフィードバックする。
        Claude Code Hooks APIの仕様に従い、stderrに出力して終了コード2で終了。
        WARN_ONLYモード（dontAsk）の場合はブロックを許可に変換。

        Args:
            reason: ブロック理由（Claudeに表示される）
        """
        # WARN_ONLYモードの場合はブロックを許可に変換
        if (hasattr(self, '_current_permission_mode_behavior') and
            self._current_permission_mode_behavior == PermissionModeBehavior.WARN_ONLY):
            self.log_info(f"Converting block to allow due to WARN_ONLY mode: {reason}")
            warn_reason = f"[WARN_ONLY] {reason}" if reason else "[WARN_ONLY]"
            self.exit_allow(reason=warn_reason)
            return  # exit_allowで終了するのでここには到達しない

        prefixed = _prefix_block_reason(reason)
        self.log_info(f"BLOCK: {prefixed}")
        print(prefixed, file=sys.stderr)
        sys.exit(ExitCode.BLOCK)

    def exit_success(
        self,
        hook_event_name: str = 'PreToolUse',
        permission_decision: str = 'allow',
        reason: str = '',
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> None:
        """成功終了（終了コード0 + stdout JSON出力）

        JSON形式でhookSpecificOutputを出力し、正常終了する。

        Args:
            hook_event_name: イベント名（PreToolUse, PostToolUse等）
            permission_decision: 許可決定（allow, deny, ask）
            reason: 理由メッセージ
            extra_fields: 追加フィールド（continueなど）
        """
        response: Dict[str, Any] = {
            'hookSpecificOutput': {
                'hookEventName': hook_event_name,
                'permissionDecision': permission_decision,
            }
        }

        if reason:
            # deny/ask時は出所プレフィックスを付与
            prefixed = _prefix_block_reason(reason) if permission_decision in ('deny', 'ask') else reason
            response['hookSpecificOutput']['permissionDecisionReason'] = prefixed

        # 追加フィールドをマージ
        if extra_fields:
            response.update(extra_fields)

        json_output = json.dumps(response, ensure_ascii=False)
        self.log_debug(f"Output JSON: {json_output}")
        print(json_output)
        sys.exit(ExitCode.SUCCESS)

    def exit_skip(self) -> None:
        """処理スキップで終了（終了コード0、出力なし）

        処理対象外の場合に使用。出力なしで正常終了。
        """
        self.log_debug("Skipping - not a target")
        sys.exit(ExitCode.SUCCESS)

    def exit_with_response(self, response: "HookResponse") -> None:
        """HookResponseで終了（終了コード0 + stdout JSON出力）

        HookResponseオブジェクトを使った構造化された応答出力。
        updated_input, additional_context, suppress_output等に対応。

        Args:
            response: HookResponseオブジェクト

        Examples:
            # 許可
            self.exit_with_response(HookResponse.allow())

            # 入力修正して許可
            self.exit_with_response(HookResponse.allow(
                updated_input={"command": "safe_command"}
            ))

            # コンテキスト注入
            self.exit_with_response(HookResponse.allow(
                additional_context="このプロジェクトでは..."
            ))

            # ユーザー確認要求
            self.exit_with_response(HookResponse.ask(
                reason="rmコマンドの確認"
            ))
        """
        response_dict = response.to_dict()
        # deny/ask時は出所プレフィックスを付与
        hook_output = response_dict.get("hookSpecificOutput", {})
        decision = hook_output.get("permissionDecision", "")
        if decision in ("deny", "ask") and "permissionDecisionReason" in hook_output:
            hook_output["permissionDecisionReason"] = _prefix_block_reason(
                hook_output["permissionDecisionReason"]
            )
        json_output = json.dumps(response_dict, ensure_ascii=False)
        self.log_debug(f"Output JSON: {json_output}")
        print(json_output)
        sys.exit(ExitCode.SUCCESS)

    def exit_allow(
        self,
        reason: str = "",
        updated_input: Optional[Dict[str, Any]] = None,
        additional_context: Optional[str] = None,
        hook_event_name: str = "PreToolUse",
        suppress_output: Optional[bool] = None,
    ) -> None:
        """許可して終了（終了コード0 + stdout JSON出力）

        updated_input, additional_context, suppress_outputに対応。

        Args:
            reason: 許可理由（ユーザーに表示）
            updated_input: ツール入力の修正
            additional_context: Claudeへの追加コンテキスト
            hook_event_name: イベント名
            suppress_output: verboseモードでの出力抑制
        """
        from .hook_response import HookResponse
        response = HookResponse(
            hook_event_name=hook_event_name,  # type: ignore
            permission_decision="allow",
            permission_decision_reason=reason if reason else None,
            updated_input=updated_input,
            additional_context=additional_context,
            suppress_output=suppress_output,
        )
        self.exit_with_response(response)

    def exit_deny(
        self,
        reason: str,
        hook_event_name: str = "PreToolUse",
    ) -> None:
        """拒否して終了（終了コード0 + stdout JSON出力）

        denyはブロックと異なり、stderrではなくJSON形式でClaudeにフィードバック。
        WARN_ONLYモード（dontAsk）の場合は拒否を許可に変換。

        Args:
            reason: 拒否理由（Claudeに表示）
            hook_event_name: イベント名
        """
        from .hook_response import HookResponse

        # WARN_ONLYモードの場合はdenyをallowに変換
        if (hasattr(self, '_current_permission_mode_behavior') and
            self._current_permission_mode_behavior == PermissionModeBehavior.WARN_ONLY):
            self.log_info(f"Converting deny to allow due to WARN_ONLY mode")
            warn_reason = f"[WARN_ONLY] {reason}" if reason else "[WARN_ONLY]"
            response = HookResponse.allow(reason=warn_reason, hook_event_name=hook_event_name)  # type: ignore
        else:
            response = HookResponse.deny(reason=reason, hook_event_name=hook_event_name)  # type: ignore

        self.exit_with_response(response)

    def exit_ask(
        self,
        reason: str,
        updated_input: Optional[Dict[str, Any]] = None,
        hook_event_name: str = "PreToolUse",
    ) -> None:
        """ユーザー確認要求して終了（終了コード0 + stdout JSON出力）

        UIでツール呼び出しを確認するようユーザーに求める。

        Args:
            reason: 確認要求理由（ユーザーに表示）
            updated_input: 入力修正（確認画面に反映）
            hook_event_name: イベント名
        """
        from .hook_response import HookResponse
        response = HookResponse.ask(
            reason=reason,
            updated_input=updated_input,
            hook_event_name=hook_event_name,  # type: ignore
        )
        self.exit_with_response(response)

    def get_session_marker_path(self, session_id: str) -> Path:
        """
        セッションマーカーファイルのパスを取得
        
        Args:
            session_id: セッションID
            
        Returns:
            マーカーファイルのパス
        """
        temp_dir = Path(tempfile.gettempdir())
        marker_name = MarkerPatterns.format_hook_session(self.__class__.__name__, session_id)
        return temp_dir / marker_name

    def get_command_marker_path(self, session_id: str, command: str) -> Path:
        """
        コマンド用マーカーファイルのパスを取得
        
        Args:
            session_id: セッションID
            command: 実行コマンド
            
        Returns:
            コマンドマーカーファイルのパス
        """
        import hashlib
        
        temp_dir = Path(tempfile.gettempdir())
        # コマンドのハッシュ値を生成（ファイル名として使用）
        command_hash = hashlib.sha256(command.encode()).hexdigest()[:8]
        marker_name = MarkerPatterns.format_command(session_id, command_hash)
        return temp_dir / marker_name

    def get_rule_marker_path(self, session_id: str, rule_name: str) -> Path:
        """
        規約名別マーカーファイルのパスを取得
        
        Args:
            session_id: セッションID
            rule_name: 規約名（例: "Presenter層編集規約"）
            
        Returns:
            規約別マーカーファイルのパス
        """
        import hashlib
        
        temp_dir = Path(tempfile.gettempdir())
        # 規約名のハッシュ値を生成（ファイル名として使用）
        rule_hash = hashlib.sha256(rule_name.encode()).hexdigest()[:8]
        marker_name = MarkerPatterns.format_rule(self.__class__.__name__, session_id, rule_hash)
        return temp_dir / marker_name

    def is_rule_processed(self, session_id: str, rule_name: str) -> bool:
        """
        規約が既に処理済みか確認
        
        Args:
            session_id: セッションID
            rule_name: チェック対象の規約名
            
        Returns:
            処理済みの場合True
        """
        marker_path = self.get_rule_marker_path(session_id, rule_name)
        return marker_path.exists()

    def mark_rule_processed(self, session_id: str, rule_name: str, context_tokens: int = 0) -> bool:
        """
        規約を処理済みとしてマーク
        
        Args:
            session_id: セッションID
            rule_name: 規約名
            context_tokens: 現在のコンテキストサイズ
            
        Returns:
            マーク成功の場合True
        """
        try:
            marker_path = self.get_rule_marker_path(session_id, rule_name)
            
            # コンテキスト情報を含むマーカーデータを作成
            marker_data = {
                'timestamp': datetime.now().isoformat(),
                'tokens': context_tokens,
                'session_id': session_id,
                'rule_name': rule_name
            }
            
            with open(marker_path, 'w') as f:
                import json
                json.dump(marker_data, f)
                
            self.log_debug(f"Created rule marker: {marker_path} for rule '{rule_name}' ({context_tokens} tokens)")
            return True
        except Exception as e:
            self.log_error(f"Failed to create rule marker: {e}")
            return False

    def is_command_processed(self, session_id: str, command: str) -> bool:
        """
        コマンドが既に処理済みか確認
        
        Args:
            session_id: セッションID
            command: チェック対象のコマンド
            
        Returns:
            処理済みの場合True
        """
        marker_path = self.get_command_marker_path(session_id, command)
        return marker_path.exists()

    def mark_command_processed(self, session_id: str, command: str, context_tokens: int = 0) -> bool:
        """
        コマンドを処理済みとしてマーク
        
        Args:
            session_id: セッションID
            command: 実行コマンド
            context_tokens: 現在のコンテキストサイズ
            
        Returns:
            マーク成功の場合True
        """
        try:
            marker_path = self.get_command_marker_path(session_id, command)
            
            # コンテキスト情報を含むマーカーデータを作成
            marker_data = {
                'timestamp': datetime.now().isoformat(),
                'tokens': context_tokens,
                'session_id': session_id,
                'command': command
            }
            
            with open(marker_path, 'w') as f:
                import json
                json.dump(marker_data, f)
                
            self.log_debug(f"Created command marker: {marker_path} ({context_tokens} tokens)")
            return True
        except Exception as e:
            self.log_error(f"Failed to create command marker: {e}")
            return False

    def is_session_processed(self, session_id: str) -> bool:
        """
        セッションが既に処理済みか確認（時間チェックなし）
        
        Args:
            session_id: セッションID
            
        Returns:
            処理済みの場合True
        """
        marker_path = self.get_session_marker_path(session_id)
        return marker_path.exists()
    
    def is_session_processed_context_aware(self, session_id: str, input_data: Dict[str, Any]) -> bool:
        """
        コンテキストベースでセッション処理済み状態を確認
        
        Args:
            session_id: セッションID
            input_data: 入力データ（transcript解析用）
            
        Returns:
            処理済みでスキップすべき場合True
        """
        marker_path = self.get_session_marker_path(session_id)
        
        if not marker_path.exists():
            return False
        
        try:
            # マーカーファイルから前回の情報を読み取り
            marker_data = self._read_marker_data(marker_path)
            if not marker_data:
                return False
            
            # transcript解析で現在のコンテキストサイズを取得
            current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
            if current_tokens is None:
                # transcript解析失敗時は単純にマーカ存在チェックのみ
                return self.is_session_processed(session_id)
            
            # コンテキストベース判定
            last_tokens = marker_data.get('tokens', 0)
            token_increase = current_tokens - last_tokens
            
            # 設定から閾値を取得
            marker_settings = getattr(self, 'marker_settings', {'valid_until_token_increase': 50000})
            threshold = marker_settings.get('valid_until_token_increase', 50000)
            
            if token_increase < threshold:
                self.log_debug(f"Within context threshold: {token_increase}/{threshold} tokens increase")
                return True
            else:
                # 閾値を超えた場合は古いマーカーをリネーム（履歴保持）
                self._rename_expired_marker(marker_path)
                self.log_debug(f"Context threshold exceeded: {token_increase}/{threshold} tokens, marker renamed")
                return False
                
        except Exception as e:
            self.log_error(f"Error in context-aware session check: {e}")
            # エラー時は単純にマーカ存在チェックのみ
            return self.is_session_processed(session_id)

    def should_skip_session(self, session_id: str, input_data: Dict[str, Any]) -> bool:
        """
        セッション処理済み判定（run()から呼ばれるオーバーライドポイント）

        デフォルト実装: is_session_processed_context_awareに委譲。
        サブクラスでオーバーライドすることで独自のセッションスキップ判定が可能。
        例: subagent対応hookは常にFalseを返し、should_process()内で独自判定を行う。

        Args:
            session_id: セッションID
            input_data: 入力データ

        Returns:
            スキップすべき場合True
        """
        return self.is_session_processed_context_aware(session_id, input_data)
    
    def _read_marker_data(self, marker_path: Path) -> Optional[Dict[str, Any]]:
        """マーカーファイルからデータを読み取り"""
        try:
            if marker_path.exists():
                with open(marker_path, 'r') as f:
                    import json
                    return json.load(f)
        except Exception as e:
            self.log_debug(f"マーカーファイル読み取り失敗（{marker_path}）: {e}")
        return None
    
    def _get_current_context_size(self, transcript_path: Optional[str]) -> Optional[int]:
        """transcriptから現在のコンテキストサイズを取得"""
        if not transcript_path or not Path(transcript_path).exists():
            return None
            
        try:
            import json
            last_usage = None
            
            with open(transcript_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') == 'assistant' and entry.get('message', {}).get('usage'):
                            last_usage = entry['message']['usage']
                    except json.JSONDecodeError:
                        continue
            
            if last_usage:
                total_tokens = (
                    last_usage.get('input_tokens', 0) +
                    last_usage.get('output_tokens', 0) +
                    last_usage.get('cache_creation_input_tokens', 0) +
                    last_usage.get('cache_read_input_tokens', 0)
                )
                return total_tokens
                
        except Exception as e:
            self.log_error(f"Error reading transcript: {e}")
            
        return None



    def _rename_expired_marker(self, marker_path: Path) -> bool:
        """
        期限切れマーカーファイルをリネーム（履歴保持）
        
        Args:
            marker_path: リネーム対象のマーカーファイルパス
            
        Returns:
            リネーム成功の場合True
        """
        try:
            if marker_path.exists():
                # タイムスタンプ付きの履歴ファイル名を生成
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                expired_name = f"{marker_path.name}.expired_{timestamp}"
                expired_path = marker_path.parent / expired_name
                
                # マーカーファイルをリネーム
                marker_path.rename(expired_path)
                self.log_info(f"🗃️ Renamed expired marker: {marker_path} -> {expired_path}")
                return True
            else:
                self.log_info(f"⚠️ Marker file does not exist, skipping rename: {marker_path}")
                return False
        except Exception as e:
            self.log_error(f"Failed to rename expired marker: {e}")
            return False

    def mark_session_processed(self, session_id: str, context_tokens: int = 0) -> bool:
        """
        セッションを処理済みとしてマーク（コンテキスト情報付き）
        
        Args:
            session_id: セッションID
            context_tokens: 現在のコンテキストサイズ
            
        Returns:
            マーク成功の場合True
        """
        try:
            marker_path = self.get_session_marker_path(session_id)
            
            # コンテキスト情報を含むマーカーデータを作成
            marker_data = {
                'timestamp': datetime.now().isoformat(),
                'tokens': context_tokens,
                'session_id': session_id
            }
            
            with open(marker_path, 'w') as f:
                import json
                json.dump(marker_data, f)
                
            self.log_debug(f"Created session marker with context: {marker_path} ({context_tokens} tokens)")
            return True
        except Exception as e:
            self.log_error(f"Failed to create session marker: {e}")
            return False

    @abstractmethod
    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """
        処理対象かどうかを判定
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理対象の場合True
        """
        pass

    @abstractmethod
    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """
        フック処理を実行
        
        Args:
            input_data: 入力データ
            
        Returns:
            decision と reason を含む辞書
        """
        pass

    def run(self) -> int:
        """
        フックのメインエントリーポイント

        Returns:
            ExitCode（SUCCESS=0, ERROR=1, BLOCK=2）
        """
        # 処理開始時刻を記録
        self._start_time = time.time()

        # 設定ファイル存在保証（自動生成）
        from application.install_hooks import ensure_config_exists
        ensure_config_exists()

        # 構造化ログでフック開始を記録
        self._structured_logger.log_hook_event(
            event_type="start",
            hook_name=self.__class__.__name__,
            debug_mode=self.debug,
        )

        # 現在のpermission_mode挙動を保持（process内で参照可能）
        self._current_permission_mode_behavior: Optional[PermissionModeBehavior] = None

        try:
            # 入力を読み取る
            input_data = self.read_input()

            if not input_data:
                self.log_debug("No input data, exiting")
                return ExitCode.SUCCESS

            # permission_modeによるスキップ判定
            should_skip, behavior = self.should_skip_by_permission_mode(input_data)
            self._current_permission_mode_behavior = behavior

            if should_skip:
                # bypassPermissions: 全処理スキップ
                self.log_info(f"Skipping all processing due to permission_mode behavior: {behavior}")
                return ExitCode.SUCCESS

            # セッションIDを取得
            session_id = input_data.get('session_id', '')
            if session_id:
                self.log_debug(f"Session ID: {session_id}")

                # セッション処理済み判定（サブクラスでオーバーライド可能）
                if self.should_skip_session(session_id, input_data):
                    self.log_debug("Session already processed, skipping (via should_skip_session)")
                    return ExitCode.SUCCESS

            # 処理対象かチェック
            if not self.should_process(input_data):
                self.log_debug("Not a target for processing, skipping")
                return ExitCode.SUCCESS

            # フック処理を実行
            # process()メソッドはexit_block/exit_success/exit_skipで終了する
            # ここに戻ってきた場合は従来形式（後方互換性）
            result = self.process(input_data)

            # ここに到達した場合は従来の形式（後方互換性）
            # 処理が正常終了した場合のみマーカーを作成
            if session_id:
                # transcriptから現在のコンテキストサイズを取得
                current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
                self.mark_session_processed(session_id, current_tokens or 0)
                self.log_debug(f"Created session marker after successful processing with {current_tokens or 0} tokens")

            # dontAskモード: ブロックを警告(allow)に変換（skip_warn_only=True時は変換しない）
            decision = result['decision']
            if behavior == PermissionModeBehavior.WARN_ONLY and decision == 'block' and not result.get('skip_warn_only'):
                self.log_info(f"Converting block to allow due to WARN_ONLY mode (dontAsk)")
                decision = 'approve'
                # 理由に警告を追加
                original_reason = result.get('reason', '')
                result['reason'] = f"[WARN_ONLY] {original_reason}" if original_reason else "[WARN_ONLY]"

            if self.output_response(decision, result.get('reason', '')):
                self._log_hook_end(decision=decision, reason=result.get('reason', ''))
                return ExitCode.SUCCESS
            else:
                self._log_hook_end(decision="output_error")
                return ExitCode.ERROR

        except Exception as e:
            self.log_error(f"Unexpected error in run", error=str(e))
            self._log_hook_end(decision="error")
            return ExitCode.ERROR

    def _log_hook_end(self, decision: Optional[str] = None, reason: Optional[str] = None):
        """フック終了ログを出力"""
        duration_ms = None
        if self._start_time:
            duration_ms = (time.time() - self._start_time) * 1000

        self._structured_logger.log_hook_event(
            event_type="end",
            hook_name=self.__class__.__name__,
            decision=decision,
            reason=reason,
            duration_ms=duration_ms,
        )