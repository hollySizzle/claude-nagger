"""フック処理の基底クラス"""

import json
import sys
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


class BaseHook(ABC):
    """Claude Code Hook処理の基底クラス"""

    def __init__(self, log_file: Optional[Path] = None, debug: bool = False):
        """
        初期化
        
        Args:
            log_file: ログファイルのパス（デフォルト: /tmp/claude_hooks_debug.log）
            debug: デバッグモードフラグ
        """
        self.debug = debug
        self.log_file = log_file or Path("/tmp/claude_hooks_debug.log")
        self._setup_logging()

    def _setup_logging(self):
        """ロギングの設定"""
        # ログはファイルのみに出力（デバッグ用に一時的にDEBUGレベル）
        logging.basicConfig(
            level=logging.DEBUG,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            handlers=[logging.FileHandler(self.log_file)]
        )
        
        self.logger = logging.getLogger(self.__class__.__name__)

    def log_debug(self, message: str):
        """デバッグログ出力"""
        self.logger.debug(message)

    def log_info(self, message: str):
        """情報ログ出力"""
        self.logger.info(message)

    def log_error(self, message: str):
        """エラーログ出力"""
        self.logger.error(message)

    def _save_raw_json(self, raw_json: str):
        """生のJSONテキストを一時ファイルに保存"""
        try:
            import os
            from datetime import datetime
            
            # ディレクトリ作成
            output_dir = "/tmp/claude"
            os.makedirs(output_dir, exist_ok=True)
            
            # タイムスタンプ付きファイル名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"base_hook_{timestamp}.json"
            filepath = os.path.join(output_dir, filename)
            
            # 生JSONを保存
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(raw_json)
            
            self.log_debug(f"Raw JSON saved to: {filepath}")
            
        except Exception as e:
            self.log_error(f"Failed to save raw JSON: {e}")

    def read_input(self) -> Dict[str, Any]:
        """
        標準入力からJSON入力を読み取る
        
        Returns:
            入力データの辞書
        """
        try:
            input_data = sys.stdin.read()
            self.log_debug(f"Input JSON length: {len(input_data)}")
            self.log_debug(f"Raw input data: {input_data[:500]}...")
            
            # 生のJSONテキストを保存
            self._save_raw_json(input_data)
            
            if not input_data:
                self.log_error("No input data received")
                return {}
            
            return json.loads(input_data)
        except json.JSONDecodeError as e:
            self.log_error(f"JSON decode error: {e}")
            return {}
        except Exception as e:
            self.log_error(f"Unexpected error reading input: {e}")
            return {}

    def output_response(self, decision: str, reason: str = "") -> bool:
        """
        JSON形式でレスポンスを出力（Claude Code v2対応）
        
        Args:
            decision: 'approve', 'block' のいずれか
            reason: 理由メッセージ
            
        Returns:
            出力成功の場合True
        """
        try:
            # Claude Code v2の新しいスキーマに対応
            response = {
                'decision': decision,
                'reason': reason,
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'allow' if decision == 'approve' else 'deny',
                'permissionDecisionReason': reason
            }
            
            json_output = json.dumps(response, ensure_ascii=False)
            print(json_output)
            
            self.log_debug(f"Output response: {json_output}")
            return True
        except Exception as e:
            self.log_error(f"Failed to output response: {e}")
            return False

    def get_session_marker_path(self, session_id: str) -> Path:
        """
        セッションマーカーファイルのパスを取得
        
        Args:
            session_id: セッションID
            
        Returns:
            マーカーファイルのパス
        """
        temp_dir = Path("/tmp")
        marker_name = f"claude_hook_{self.__class__.__name__}_session_{session_id}"
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
        
        temp_dir = Path("/tmp")
        # コマンドのハッシュ値を生成（ファイル名として使用）
        command_hash = hashlib.md5(command.encode()).hexdigest()[:8]
        marker_name = f"claude_cmd_{session_id}_{command_hash}"
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
        
        temp_dir = Path("/tmp")
        # 規約名のハッシュ値を生成（ファイル名として使用）
        rule_hash = hashlib.md5(rule_name.encode()).hexdigest()[:8]
        marker_name = f"claude_rule_{self.__class__.__name__}_{session_id}_{rule_hash}"
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
    
    def _read_marker_data(self, marker_path: Path) -> Optional[Dict[str, Any]]:
        """マーカーファイルからデータを読み取り"""
        try:
            if marker_path.exists():
                with open(marker_path, 'r') as f:
                    import json
                    return json.load(f)
        except Exception:
            pass
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
            終了コード（0: 成功、1: エラー）
        """
        self.log_info(f"{'='*10} {self.__class__.__name__} Started {'='*10}")
        
        try:
            # 入力を読み取る
            input_data = self.read_input()
            
            if not input_data:
                self.log_debug("No input data, exiting")
                return 0
            
            # セッションIDを取得
            session_id = input_data.get('session_id', '')
            if session_id:
                self.log_debug(f"Session ID: {session_id}")
                
                # 既に処理済みかをコンテキストベースで確認
                if self.is_session_processed_context_aware(session_id, input_data):
                    self.log_debug("Session already processed and within context threshold, skipping")
                    return 0
            
            # 処理対象かチェック
            if not self.should_process(input_data):
                self.log_debug("Not a target for processing, skipping")
                return 0
            
            # フック処理を実行（終了コード方式）
            # 注意: process() メソッドは sys.exit() で終了するため、
            # 通常はここに到達しない
            result = self.process(input_data)
            
            # ここに到達した場合は従来の形式（後方互換性）
            # 処理が正常終了した場合のみマーカーを作成
            if session_id:
                # transcriptから現在のコンテキストサイズを取得
                current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
                self.mark_session_processed(session_id, current_tokens or 0)
                self.log_debug(f"Created session marker after successful processing with {current_tokens or 0} tokens")
            
            if self.output_response(result['decision'], result.get('reason', '')):
                self.log_info(f"Successfully processed with decision: {result['decision']}")
                return 0
            else:
                return 1
                
        except Exception as e:
            self.log_error(f"Unexpected error in run: {e}")
            return 1
        finally:
            self.log_info(f"{'='*10} {self.__class__.__name__} Ended {'='*10}")