"""セッション開始時の規約確認フック"""

import copy
import json
import sys
import os
import tempfile
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.hooks.base_hook import BaseHook, MarkerPatterns
from domain.services.subagent_marker_manager import SubagentMarkerManager
from shared.constants import SUGGESTED_RULES_FILENAME


def _deep_copy_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """辞書の深いコピー（ネスト・リスト対応）"""
    return copy.deepcopy(d)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """overrideの値でbaseを深くマージ（in-place）

    ネストされた辞書は再帰的にマージし、それ以外は上書き。
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value



class SessionStartupHook(BaseHook):
    """セッション開始時のAI協働規約確認フック"""

    def __init__(self, *args, **kwargs):
        """初期化"""
        super().__init__(debug=True)
        self.config = self._load_config()
        # subagentコンテキスト（should_processで設定、processで参照）
        self._is_subagent = False
        self._resolved_config = None
        self._current_agent_id = None
        self._current_agent_type = None
        
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

    def is_session_processed_context_aware(self, session_id: str, input_data: Dict[str, Any]) -> bool:
        """SessionStartupHookは独自のマーカー機構を使用するため、
        BaseHookのセッションチェックをバイパスしてshould_processに委ねる。
        subagent対応のため、常にFalseを返す。
        """
        return False
        
    def get_session_startup_marker_path(self, session_id: str) -> Path:
        """
        セッション開始確認マーカーファイルのパスを取得
        
        Args:
            session_id: セッションID
            
        Returns:
            マーカーファイルのパス
        """
        temp_dir = Path(tempfile.gettempdir())
        marker_name = MarkerPatterns.format_session_startup(session_id)
        return temp_dir / marker_name

    def _get_subagent_startup_marker_path(self, session_id: str, agent_id: str) -> Path:
        """subagent別のstartup処理済みマーカーパスを取得

        ライフサイクルマーカー（subagents/）とは別ディレクトリに配置。

        Args:
            session_id: セッションID
            agent_id: サブエージェントID

        Returns:
            マーカーファイルのパス
        """
        return SubagentMarkerManager.BASE_DIR / session_id / "startup" / f"{agent_id}.json"

    def _is_subagent_startup_processed(self, session_id: str, agent_id: str) -> bool:
        """subagent別のstartup処理済み判定

        Args:
            session_id: セッションID
            agent_id: サブエージェントID

        Returns:
            処理済みの場合True
        """
        marker_path = self._get_subagent_startup_marker_path(session_id, agent_id)
        exists = marker_path.exists()
        self.log_info(f"📋 Subagent startup marker check: {marker_path} -> {'EXISTS' if exists else 'NOT_EXISTS'}")
        return exists

    def _mark_subagent_startup_processed(self, session_id: str, agent_id: str, agent_type: str) -> bool:
        """subagent別のstartup処理済みマーカー作成

        Args:
            session_id: セッションID
            agent_id: サブエージェントID
            agent_type: サブエージェント種別

        Returns:
            作成成功の場合True
        """
        try:
            marker_path = self._get_subagent_startup_marker_path(session_id, agent_id)
            marker_path.parent.mkdir(parents=True, exist_ok=True)

            marker_data = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "agent_id": agent_id,
                "agent_type": agent_type,
                "hook_type": "session_startup_subagent",
            }
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, ensure_ascii=False)

            self.log_info(f"✅ Created subagent startup marker: {marker_path}")
            return True
        except Exception as e:
            self.log_error(f"Failed to create subagent startup marker: {e}")
            return False

    def _resolve_subagent_config(self, agent_type: str) -> Dict[str, Any]:
        """subagent種別に応じたoverride設定を解決

        解決順序: base → subagent_default → subagent_types.{type}

        Args:
            agent_type: サブエージェント種別

        Returns:
            解決済み設定辞書
        """
        overrides = self.config.get("overrides", {})
        subagent_default = overrides.get("subagent_default", {})
        subagent_types = overrides.get("subagent_types", {})
        type_specific = subagent_types.get(agent_type, {})

        # base設定をコピー
        resolved = {
            "enabled": self.config.get("enabled", True),
            "messages": _deep_copy_dict(self.config.get("messages", {})),
            "behavior": _deep_copy_dict(self.config.get("behavior", {})),
        }

        # subagent_defaultで上書き
        _deep_merge(resolved, subagent_default)

        # subagent_types.{type}でさらに上書き
        _deep_merge(resolved, type_specific)

        self.log_info(f"🔧 Resolved subagent config for '{agent_type}': enabled={resolved.get('enabled')}")
        return resolved

    def is_session_startup_processed(self, session_id: str, input_data: Dict[str, Any] = None) -> bool:
        """
        セッション開始時の規約確認が既に処理済みか確認（トークン閾値対応）
        
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
                    with open(marker_path, 'r') as f:
                        marker_data = json.load(f)
                        last_tokens = marker_data.get('tokens', 0)
                    
                    token_increase = current_tokens - last_tokens
                    
                    if token_increase >= threshold:
                        self.log_info(f"🚨 Session startup token threshold exceeded: {token_increase} >= {threshold}")
                        # 閾値超過時は履歴ファイルを作成してから削除
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
            
            # 現在のトークン数を取得
            current_tokens = 0
            if input_data:
                current_tokens = super()._get_current_context_size(input_data.get('transcript_path')) or 0
            
            # セッション開始時の情報をマーカーファイルに記録
            marker_data = {
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
                'hook_type': 'session_startup',
                'tokens': current_tokens
            }
            
            with open(marker_path, 'w') as f:
                json.dump(marker_data, f)
                
            self.log_info(f"✅ Created session startup marker with {current_tokens} tokens: {marker_path}")
            return True
        except Exception as e:
            self.log_error(f"Failed to create session startup marker: {e}")
            return False

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """
        セッション開始時の処理対象かどうかを判定（設定ファイル対応・subagent override対応）

        Trueを返す場合、以下のインスタンス属性をprocess()用に設定する:
        - _is_subagent (bool): subagentコンテキストか否か
        - _resolved_config (dict|None): subagent時のoverride解決済み設定
        - _current_agent_id (str|None): subagentのagent_id
        - _current_agent_type (str|None): subagentのagent_type
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理対象の場合True
        """
        self.log_info(f"📋 SessionStartupHook - Input data keys: {input_data.keys()}")
        
        # Taskツール（subagent生成）はスキップ（subagent自身のツール呼び出しで発火する）
        tool_name = input_data.get('tool_name', '')
        if tool_name == 'Task':
            self.log_debug("Skipping Task tool (subagent spawn)")
            return False
        
        # 設定で無効化されている場合はスキップ（base設定）
        if not self.config.get('enabled', True):
            self.log_info("❌ Session startup hook is disabled in config")
            return False
        
        # セッションIDを取得
        session_id = input_data.get('session_id', '')
        if not session_id:
            self.log_info("❌ No session_id found, skipping")
            return False
        
        self.log_info(f"🔍 Session ID: {session_id}")

        # subagentマーカー検出
        manager = SubagentMarkerManager(session_id)
        if manager.is_subagent_active():
            active = manager.get_active_subagent()
            if active:
                agent_type = active.get("agent_type", "unknown")
                agent_id = active.get("agent_id", "")

                self.log_info(f"🤖 Subagent detected: type={agent_type}, id={agent_id}")

                # override設定を解決
                resolved = self._resolve_subagent_config(agent_type)

                # override設定でenabled: falseの場合はスキップ
                if not resolved.get("enabled", True):
                    self.log_info(f"❌ Subagent type '{agent_type}' is disabled by overrides")
                    return False

                # subagent別処理済みチェック
                if self._is_subagent_startup_processed(session_id, agent_id):
                    self.log_info(f"✅ Subagent startup already processed: {agent_id}")
                    return False

                # subagentコンテキストを保存して後続processで使用
                self._is_subagent = True
                self._resolved_config = resolved
                self._current_agent_id = agent_id
                self._current_agent_type = agent_type

                self.log_info(f"🚀 New subagent requires startup processing: {agent_type}/{agent_id}")
                return True

        # main agentフロー（既存ロジック）
        self._is_subagent = False
        self._resolved_config = None

        # once_per_sessionが有効で既に処理済みの場合はスキップ
        if self.config.get('behavior', {}).get('once_per_session', True):
            if self.is_session_startup_processed(session_id, input_data):
                self.log_info(f"✅ Session startup already processed for: {session_id}")
                return False
        
        self.log_info(f"🚀 New session detected, requires startup processing: {session_id}")
        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """
        セッション開始時の規約確認処理を実行（subagent override対応）

        前提: should_process()がTrueを返した後に呼び出すこと。
        should_process()が設定した_is_subagent, _resolved_config等を参照する。
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理結果 {'decision': 'block'/'approve', 'reason': 'メッセージ'}
        """
        session_id = input_data.get('session_id', '')
        
        self.log_info(f"🎯 Processing session startup for: {session_id} (subagent={self._is_subagent})")
        
        # suggested_rules.yamlを一度だけ読み込み
        suggested_rules_data = self._load_suggested_rules()
        
        # メッセージを構築（ロード結果を引数で渡す）
        message = self._build_message(session_id, suggested_rules_data=suggested_rules_data)
        
        self.log_info(f"📋 SESSION STARTUP BLOCKING: Session '{session_id}' requires startup confirmation")
        
        if self._is_subagent:
            # subagent: subagent別マーカーを作成
            self._mark_subagent_startup_processed(
                session_id, self._current_agent_id, self._current_agent_type
            )
        else:
            # main agent: 既存のマーカーを作成
            self.mark_session_startup_processed(session_id, input_data)
        
        # 通知済みのsuggested_rules.yamlをアーカイブ
        if suggested_rules_data is not None:
            self._archive_suggested_rules()
        
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
        return count + 1 if count > 0 else 1
    
    def _build_message(self, session_id: str, suggested_rules_data: Optional[Dict[str, Any]] = None) -> str:
        """
        設定ファイルからメッセージを構築（subagent override対応）
        
        Args:
            session_id: セッションID
            suggested_rules_data: ロード済みのsuggested_rulesデータ（Noneなら提案なし）
            
        Returns:
            構築されたメッセージ文字列
        """
        # subagentの場合は解決済みconfigを使用
        if self._is_subagent and self._resolved_config:
            config_to_use = self._resolved_config
            # subagentは常に初回扱い
            execution_count = 1
        else:
            config_to_use = self.config
            execution_count = self._get_execution_count(session_id)
        
        # messages 構造から適切なメッセージを選択
        messages_config = config_to_use.get('messages', {})
        
        if execution_count == 1:
            message_config = messages_config.get('first_time', {})
        else:
            message_config = messages_config.get('repeated', {})
        
        title = message_config.get('title', 'セッション開始時の確認')
        main_text = message_config.get('main_text', '設定ファイルを確認してください。')
        
        # メッセージを構築
        message = title + "\n\n" + main_text
        
        # suggested_rules.yaml の提案サマリーを統合
        if suggested_rules_data:
            summary = self._build_suggested_rules_summary(suggested_rules_data)
            if summary:
                message += "\n\n" + summary
        
        self.log_info(f"🎯 Built message for execution #{execution_count}: {title[:50]}...")
        
        return message

    def _get_suggested_rules_path(self) -> Path:
        """suggested_rules.yamlのパスを返す"""
        return Path.cwd() / ".claude-nagger" / SUGGESTED_RULES_FILENAME

    def _load_suggested_rules(self) -> Optional[Dict[str, Any]]:
        """suggested_rules.yamlを読み込む。存在しない場合はNone"""
        rules_path = self._get_suggested_rules_path()
        if not rules_path.exists():
            return None

        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            self.log_info(f"📋 suggested_rules.yaml を検出: {rules_path}")
            return data
        except Exception as e:
            self.log_error(f"❌ suggested_rules.yaml 読み込み失敗: {e}")
            return None

    def _build_suggested_rules_summary(self, rules_data: Dict[str, Any]) -> str:
        """規約提案データからサマリーメッセージを構築"""
        rules = rules_data.get('rules', [])
        if not rules:
            return ""

        lines = [
            "---",
            "📋 規約提案があります（suggested_rules.yaml）",
            f"提案数: {len(rules)}件",
            "",
        ]

        for i, rule in enumerate(rules, 1):
            name = rule.get('name', '(名前なし)')
            severity = rule.get('severity', 'warn')
            message = rule.get('message', '').strip().split('\n')[0]

            patterns = rule.get('patterns', [])
            commands = rule.get('commands', [])

            target = ""
            if patterns:
                target = f"パターン: {', '.join(patterns[:3])}"
            elif commands:
                target = f"コマンド: {', '.join(commands[:3])}"

            lines.append(f"{i}. [{severity}] {name}")
            if target:
                lines.append(f"   {target}")
            if message:
                lines.append(f"   → {message}")

        lines.extend([
            "",
            "確認後、file_conventions.yaml / command_conventions.yaml に追記してください。",
        ])

        return "\n".join(lines)

    def _archive_suggested_rules(self) -> bool:
        """通知済みのsuggested_rules.yamlをリネーム"""
        rules_path = self._get_suggested_rules_path()
        if not rules_path.exists():
            return False

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived_name = f".suggested_rules.yaml.notified_{timestamp}"
        archived_path = rules_path.parent / archived_name

        try:
            rules_path.rename(archived_path)
            self.log_info(f"📦 suggested_rules.yaml をアーカイブ: {archived_path}")
            return True
        except Exception as e:
            self.log_error(f"❌ suggested_rules.yaml アーカイブ失敗: {e}")
            return False


def main():
    """メインエントリーポイント"""
    hook = SessionStartupHook(debug=False)
    sys.exit(hook.run())


if __name__ == "__main__":
    main()