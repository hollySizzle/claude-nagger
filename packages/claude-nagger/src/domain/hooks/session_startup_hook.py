"""セッション開始時の規約確認フック"""

import sys
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.hooks.base_hook import BaseHook, MarkerPatterns


class SessionStartupHook(BaseHook):
    """セッション開始時のAI協働規約確認フック"""

    def __init__(self, *args, **kwargs):
        """初期化"""
        super().__init__(debug=True)
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """
        設定ファイルを読み込む
        
        優先順位:
        1. .claude-nagger/config.yaml (プロジェクト設定)
        2. rules/session_startup_settings.yaml (デフォルト設定)
        
        Returns:
            設定データの辞書
        """
        # プロジェクト設定を優先
        project_config = Path.cwd() / ".claude-nagger" / "config.yaml"
        if project_config.exists():
            config_file = project_config
        else:
            # フォールバック: デフォルト設定
            config_file = Path(__file__).parent.parent.parent.parent / "rules" / "session_startup_settings.yaml"
        
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    self.log_info(f"✅ Loaded session startup config: {config_file}")
                    return data.get('session_startup', {})
            else:
                self.log_error(f"❌ Config file not found: {config_file}")
                return {}
        except Exception as e:
            self.log_error(f"❌ Failed to load config: {e}")
            return {}
        
    def get_session_startup_marker_path(self, session_id: str) -> Path:
        """
        セッション開始確認マーカーファイルのパスを取得
        
        Args:
            session_id: セッションID
            
        Returns:
            マーカーファイルのパス
        """
        temp_dir = Path("/tmp")
        marker_name = MarkerPatterns.format_session_startup(session_id)
        return temp_dir / marker_name

    def is_session_startup_processed(self, session_id: str, input_data: Dict[str, Any] = None) -> bool:
        """
        セッション開始時の規約確認が既に処理済みか確認（トークン闾値対応）
        
        Args:
            session_id: セッションID
            input_data: 入力データ（トークンチェック用）
            
        Returns:
            処理済みの場合True
        """
        if not session_id:
            return False
            
        marker_path = self.get_session_startup_marker_path(session_id)
        exists = marker_path.exists()
        
        self.log_info(f"📋 Session startup marker check: {marker_path} -> {'EXISTS' if exists else 'NOT_EXISTS'}")
        
        if not exists:
            return False
            
        # トークン閾値チェック
        threshold = self.config.get('behavior', {}).get('token_threshold', 50000)
        if input_data and input_data.get('transcript_path'):
            current_tokens = super()._get_current_context_size(input_data.get('transcript_path'))
            if current_tokens is not None:
                # マーカーファイルから前回のトークン数を取得
                try:
                    import json
                    with open(marker_path, 'r') as f:
                        marker_data = json.load(f)
                        last_tokens = marker_data.get('tokens', 0)
                    
                    token_increase = current_tokens - last_tokens
                    
                    if token_increase >= threshold:
                        self.log_info(f"🚨 Session startup token threshold exceeded: {token_increase} >= {threshold}")
                        # 閾値超過時は履歴ファイルを作成してから削除（ImplementationDesignHookと同様）
                        super()._rename_expired_marker(marker_path)
                        return False
                    else:
                        self.log_info(f"✅ Session startup within token threshold: {token_increase}/{threshold}")
                        
                except Exception as e:
                    self.log_error(f"Error checking token threshold: {e}")
            
        return True  # マーカー存在かつ閾値内の場合はスキップ





    def mark_session_startup_processed(self, session_id: str, input_data: Dict[str, Any] = None) -> bool:
        """
        セッション開始時の規約確認を処理済みとしてマーク（トークン情報付き）
        
        Args:
            session_id: セッションID
            input_data: 入力データ（トークン情報用）
            
        Returns:
            マーク成功の場合True
        """
        try:
            marker_path = self.get_session_startup_marker_path(session_id)
            
            # 個別token_thresholdによる制御のため、マーカーリネーム処理は削除
            
            # 現在のトークン数を取得
            current_tokens = 0
            if input_data:
                current_tokens = super()._get_current_context_size(input_data.get('transcript_path')) or 0
            
            # セッション開始時の情報をマーカーファイルに記録
            from datetime import datetime
            marker_data = {
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
                'hook_type': 'session_startup',
                'tokens': current_tokens
            }
            
            with open(marker_path, 'w') as f:
                import json
                json.dump(marker_data, f)
                
            self.log_info(f"✅ Created session startup marker with {current_tokens} tokens: {marker_path}")
            return True
        except Exception as e:
            self.log_error(f"Failed to create session startup marker: {e}")
            return False

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """
        セッション開始時の処理対象かどうかを判定（設定ファイル対応）
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理対象の場合True
        """
        self.log_info(f"📋 SessionStartupHook - Input data keys: {input_data.keys()}")
        
        # 設定で無効化されている場合はスキップ
        if not self.config.get('enabled', True):
            self.log_info("❌ Session startup hook is disabled in config")
            return False
        
        # セッションIDを取得
        session_id = input_data.get('session_id', '')
        if not session_id:
            self.log_info("❌ No session_id found, skipping")
            return False
        
        self.log_info(f"🔍 Session ID: {session_id}")
        
        # once_per_sessionが有効で既に処理済みの場合はスキップ
        if self.config.get('behavior', {}).get('once_per_session', True):
            if self.is_session_startup_processed(session_id, input_data):
                self.log_info(f"✅ Session startup already processed for: {session_id}")
                return False
        
        self.log_info(f"🚀 New session detected, requires startup processing: {session_id}")
        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """
        セッション開始時の規約確認処理を実行
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理結果 {'decision': 'block'/'approve', 'reason': 'メッセージ'}
        """
        session_id = input_data.get('session_id', '')
        
        self.log_info(f"🎯 Processing session startup for: {session_id}")
        
        # 設定ファイルからメッセージを構築（実行回数に応じて変更）
        message = self._build_message(session_id)
        
        # ImplementationDesignHookと同様のJSON応答方式でブロッキング
        self.log_info(f"📋 SESSION STARTUP BLOCKING: Session '{session_id}' requires startup confirmation")
        
        # ブロッキング前にマーカーファイルを作成（ImplementationDesignHookと同じタイミング）
        self.mark_session_startup_processed(session_id, input_data)
        
        # JSON応答でブロック
        return {
            'decision': 'block',
            'reason': message
        }

    def _get_execution_count(self, session_id: str) -> int:
        """
        セッション内での実行回数を取得
        
        Args:
            session_id: セッションID
            
        Returns:
            実行回数（1から開始）
        """
        count = 0
        marker_base = self.get_session_startup_marker_path(session_id)
        temp_dir = marker_base.parent
        marker_prefix = marker_base.name
        
        # 現在のマーカーファイルと.expired_履歴ファイルをカウント
        for file_path in temp_dir.glob(f"{marker_prefix}*"):
            if file_path.name.startswith(marker_prefix):
                count += 1
        
        # 実行前の状態では、次回実行予定の回数を返す
        # 現在のマーカーファイルが存在する場合は次回が2回目以降
        return count + 1 if count > 0 else 1
    
    def _build_message(self, session_id: str) -> str:
        """
        設定ファイルからメッセージを構築（実行回数に応じて変更）
        
        Args:
            session_id: セッションID
            
        Returns:
            構築されたメッセージ文字列
        """
        execution_count = self._get_execution_count(session_id)
        
        # messages 構造から適切なメッセージを選択
        messages_config = self.config.get('messages', {})
        
        if execution_count == 1:
            # 1回目
            message_config = messages_config.get('first_time', {})
        else:
            # 2回目以降
            message_config = messages_config.get('repeated', {})
        
        title = message_config.get('title', 'セッション開始時の確認')
        main_text = message_config.get('main_text', '設定ファイルを確認してください。')
        
        # メッセージを構築
        message = title + "\n\n" + main_text
        
        self.log_info(f"🎯 Built message for execution #{execution_count}: {title[:50]}...")
        
        return message


def main():
    """メインエントリーポイント"""
    hook = SessionStartupHook(debug=False)
    sys.exit(hook.run())


if __name__ == "__main__":
    main()