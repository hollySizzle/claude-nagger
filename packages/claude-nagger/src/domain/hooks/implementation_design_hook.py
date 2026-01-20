"""実装設計書編集フック"""

import sys
import os
from pathlib import Path
from typing import Dict, Any
sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.hooks.base_hook import BaseHook
from domain.services.file_convention_matcher import FileConventionMatcher
from domain.services.command_convention_matcher import CommandConventionMatcher
from infrastructure.config.config_manager import ConfigManager
from shared.structured_logging import get_logger


class ImplementationDesignHook(BaseHook):
    """実装設計書編集時の規約確認フック"""

    def __init__(self, *args, **kwargs):
        """初期化"""
        # デバッグモードを一時的に有効化
        super().__init__(debug=True)
        self.matcher = FileConventionMatcher(debug=True)  # デバッグモードを有効化
        self.command_matcher = CommandConventionMatcher(debug=True)  # コマンド規約マッチャー
        self.config = ConfigManager()
        self.transcript_path = None
        
        # 設定ファイルから閾値を読み込み
        self.thresholds = self.config.get_context_thresholds()
        self.marker_settings = self.config.get_marker_settings()
        
        # 統一ログディレクトリを使用（structured_logging）
        self.impl_logger = get_logger("ImplementationDesignHook")
        self.impl_logger.info("=== ImplementationDesignHook initialized ===", 
                              thresholds=self.thresholds, marker_settings=self.marker_settings)

    def normalize_file_path(self, file_path: str, cwd: str = '') -> str:
        """
        ファイルパスを正規化して絶対パスに変換

        Args:
            file_path: 元のファイルパス（相対/絶対両対応）
            cwd: 現在の作業ディレクトリ（project_dirが未設定の場合のフォールバック）

        Returns:
            正規化された絶対パス

        Note:
            CLAUDE_PROJECT_DIR環境変数を優先的に使用。
            未設定の場合はcwd引数にフォールバック。
        """
        if os.path.isabs(file_path):
            normalized = os.path.normpath(file_path)
            self.log_debug(f"File path is already absolute: {normalized}")
            return normalized

        # project_dir（CLAUDE_PROJECT_DIR）を優先、未設定ならcwdにフォールバック
        base_dir = self.project_dir or cwd or os.getcwd()
        absolute_path = os.path.join(base_dir, file_path)
        normalized = os.path.normpath(absolute_path)
        self.log_debug(f"Converted relative path '{file_path}' to absolute: '{normalized}' (base_dir={base_dir})")
        return normalized

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """
        処理対象かどうかを判定（ファイル編集とコマンド実行の両方）
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理対象の場合True
        """
        self.log_info(f"🚀 should_process() called")
        self.log_info(f"📋 Input data keys: {input_data.keys()}")
        self.impl_logger.info(f"SHOULD_PROCESS START: tool_name={input_data.get('tool_name', 'N/A')}, session_id={input_data.get('session_id', 'N/A')}")
        
        # ツール名を取得
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        
        self.log_info(f"🔧 Tool name: {tool_name}")
        self.log_info(f"📝 Tool input keys: {tool_input.keys()}")
        self.impl_logger.info(f"TOOL DETECTION: tool_name='{tool_name}', tool_input_keys={list(tool_input.keys())}")
        
        # コマンド実行ツールの場合（Bash or serena execute_shell_command）
        if tool_name == 'Bash' or tool_name == 'mcp__serena__execute_shell_command':
            command = tool_input.get('command', '')
            self.log_info(f"💻 Command tool ({tool_name}): {command}")
            self.impl_logger.info(f"COMMAND TOOL DETECTED: tool_name='{tool_name}', command='{command}'")
            if command:
                self.log_info(f"✅ Command tool detected - returning True")
                self.impl_logger.info(f"COMMAND TOOL APPROVED: Proceeding with command processing")
                return True
            else:
                self.impl_logger.warning(f"COMMAND TOOL REJECTED: Empty command")
        
        # ファイル編集/作成ツールの場合 (mcp__serena__create_text_file も含む)
        file_tools = ['Edit', 'Write', 'MultiEdit', 'mcp__serena__create_text_file', 'mcp__serena__replace_regex', 'mcp__filesystem__write_file', 'mcp__filesystem__edit_file']
        if tool_name in file_tools or 'edit' in tool_name.lower() or 'write' in tool_name.lower() or 'create' in tool_name.lower():
            self.impl_logger.info(f"FILE OPERATION TOOL DETECTED: tool_name='{tool_name}'")
        
        # ファイル編集ツールの場合
        file_path = tool_input.get('file_path', '') or tool_input.get('relative_path', '')
        self.log_info(f"📁 Extracted file_path: {file_path}")
        self.impl_logger.info(f"FILE TOOL DETECTED: tool_name='{tool_name}', file_path='{file_path}'")
        
        if not file_path:
            self.log_info(f"❌ No file_path found in tool_input - returning False")
            self.impl_logger.info(f"FILE TOOL REJECTED: No file_path found")
            return False
        
        # cwdから動的に絶対パスを構築
        cwd = input_data.get('cwd', os.getcwd())
        absolute_path = self.normalize_file_path(file_path, cwd)
        
        self.log_info(f"🔍 Processing file path: {absolute_path}")
        
        # transcript_pathを保存（あとで使用）
        self.transcript_path = input_data.get('transcript_path')
        # Transcript path debug log removed
        
        # FileConventionMatcherで規約に該当するか確認（絶対パスを使用）
        rule_info = self.matcher.get_confirmation_message(absolute_path)
        
        # Pattern matching debug removed
        # Target file debug removed
        # Rule matching result debug removed
        
        if rule_info:
            self.log_info(f"✅ RULE MATCHED: {rule_info['rule_name']} - Severity: {rule_info['severity']}")
            self.impl_logger.info(f"FILE RULE MATCHED: {rule_info['rule_name']} (severity: {rule_info['severity']}, threshold: {rule_info.get('token_threshold', 'default')})")
            
            # 規約別のセッション・トークンチェック
            session_id = input_data.get('session_id', '')
            rule_name = rule_info['rule_name']
            self.impl_logger.info(f"RULE MATCHED CHECK: session_id='{session_id}', rule_name='{rule_name}'")
            
            if session_id:
                # 規約別マーカーでトークン閾値チェック
                is_processed = self.is_rule_processed(session_id, rule_name)
                self.impl_logger.info(f"MARKER CHECK: is_rule_processed={is_processed}")
                if is_processed:
                    # 規約固有の閾値設定を取得
                    threshold = self._get_rule_threshold(rule_info)
                    
                    # マーカーファイルから前回のトークン数を取得
                    marker_path = self.get_rule_marker_path(session_id, rule_name)
                    if marker_path.exists():
                        try:
                            import json
                            with open(marker_path, 'r') as f:
                                marker_data = json.load(f)
                                last_tokens = marker_data.get('tokens', 0)
                            
                            # 現在のトークン数を取得
                            current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
                            if current_tokens is not None:
                                token_increase = current_tokens - last_tokens
                                
                                if token_increase < threshold:
                                    self.log_info(f"✅ Rule '{rule_name}' within individual token threshold: {token_increase}/{threshold}, skipping")
                                    self.impl_logger.info(f"INDIVIDUAL TOKEN THRESHOLD SKIP: Rule '{rule_name}' increase {token_increase} < threshold {threshold}, skipping processing")
                                    return False
                                else:
                                    self.log_info(f"🚨 Rule '{rule_name}' individual token threshold exceeded: {token_increase} >= {threshold}, processing")
                                    self.impl_logger.info(f"INDIVIDUAL TOKEN THRESHOLD EXCEEDED: Rule '{rule_name}' increase {token_increase} >= threshold {threshold}, proceeding with processing")
                                    # 古いマーカーをリネーム
                                    self._rename_expired_marker(marker_path)
                        except Exception as e:
                            self.log_error(f"Error checking individual token threshold: {e}")
                    else:
                        self.log_info(f"⚠️ Marker file not found for rule '{rule_name}', proceeding with processing")
            
            return True
        else:
            self.log_info(f"❌ NO RULES MATCHED for file: {absolute_path}")
            self.log_info(f"🔍 Available patterns check:")
            
            # デバッグ: 使用可能な規約パターンを表示
            try:
                self.log_info("Available rule patterns:")
                # FileConventionMatcherの内部状態をデバッグ出力
                if hasattr(self.matcher, 'rules'):
                    for rule in self.matcher.rules:
                        self.log_info(f"  - {rule.name}: {rule.patterns}")
                        # 各パターンでマッチテスト
                        for pattern in rule.patterns:
                            match_result = self.matcher.matches_pattern(absolute_path, [pattern])
                            self.log_info(f"    Pattern '{pattern}' -> Match: {match_result}")
            except Exception as e:
                self.log_error(f"Error debugging rules: {e}")
        
        self.log_info(f"🔚 should_process() finished - returning False")
        self.impl_logger.info(f"SHOULD_PROCESS END: Returning False - No rules matched")
        return False

    def _get_rule_threshold(self, rule_info: Dict[str, Any]) -> int:
        """
        規約情報から個別のトークン閾値を取得
        
        Args:
            rule_info: 規約情報辞書（token_threshold含む）
            
        Returns:
            トークン閾値
        """
        # 規約固有の閾値が設定されている場合はそれを優先
        if rule_info.get('token_threshold') is not None:
            threshold = rule_info['token_threshold']
            self.log_debug(f"Using rule-specific threshold for '{rule_info['rule_name']}': {threshold}")
            self.impl_logger.debug(f"RULE THRESHOLD: Using rule-specific threshold for '{rule_info['rule_name']}': {threshold}")
            return threshold
        
        # フォールバック：severity別のデフォルト閾値を使用
        severity = rule_info.get('severity', 'warn')
        rule_thresholds = self.config.get_context_thresholds().get('rule_thresholds', {
            'block': 20000,
            'stop': 25000,
            'warn': 40000
        })
        
        threshold = rule_thresholds.get(severity, 30000)
        self.log_debug(f"Using default threshold for severity '{severity}': {threshold}")
        return threshold
    
    def _get_command_threshold(self, rule_info: Dict[str, Any]) -> int:
        """
        コマンド規約情報から個別のトークン閾値を取得
        
        Args:
            rule_info: コマンド規約情報辞書（token_threshold含む）
            
        Returns:
            トークン閾値
        """
        # コマンド固有の閾値が設定されている場合はそれを優先
        if rule_info.get('token_threshold') is not None:
            threshold = rule_info['token_threshold']
            self.log_debug(f"Using command-specific threshold for '{rule_info['rule_name']}': {threshold}")
            self.impl_logger.debug(f"COMMAND THRESHOLD: Using command-specific threshold for '{rule_info['rule_name']}': {threshold}")
            return threshold
        
        # フォールバック：デフォルトのコマンド閾値を使用
        command_threshold = self.config.get_context_thresholds().get('command_threshold', 30000)
        self.log_debug(f"Using default command threshold: {command_threshold}")
        return command_threshold
    
    def _normalize_rule_name(self, rule_name: str) -> str:
        """
        規約名をマーカーファイル名用に正規化
        
        Args:
            rule_name: 元の規約名
            
        Returns:
            正規化された規約名
        """
        # 日本語文字や特殊文字をマーカー名用に正規化
        import re
        import hashlib
        
        # 特殊文字を除去し、ハッシュ化で短縮
        normalized = re.sub(r'[^\w\s-]', '', rule_name)
        normalized = re.sub(r'[\s-]+', '_', normalized)
        
        # 長すぎる場合はハッシュ値を使用
        if len(normalized) > 20:
            hash_value = hashlib.md5(rule_name.encode()).hexdigest()[:8]
            normalized = f"{normalized[:12]}_{hash_value}"
        
        self.log_debug(f"Normalized rule name: '{rule_name}' -> '{normalized}'")
        return normalized

    def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        フック処理を実行（ファイル編集とコマンド実行の両方）

        Args:
            input_data: 入力データ

        Returns:
            ClaudeCode Hook出力形式の辞書 {'decision': 'block'/'approve', 'reason': 'メッセージ'}
        """
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        session_id = input_data.get('session_id', '')
        
        # コマンド実行ツールの場合（Bash or serena execute_shell_command）
        if tool_name == 'Bash' or tool_name == 'mcp__serena__execute_shell_command':
            return self._process_command(tool_input, session_id, input_data)
        
        # ファイル編集の場合（既存の処理）
        file_path = tool_input.get('file_path', '') or tool_input.get('relative_path', '')
        
        # cwdから動的に絶対パスを構築
        cwd = input_data.get('cwd', os.getcwd())
        absolute_path = self.normalize_file_path(file_path, cwd)
        
        # Processing file path debug removed
        
        # 規約情報を取得（絶対パスを使用）
        rule_info = self.matcher.get_confirmation_message(absolute_path)
        
        if not rule_info:
            # 規約に該当しない場合は許可
            return {
                'decision': 'approve',
                'reason': 'No rules matched'
            }
        
        # severityに応じて処理を分岐
        severity = rule_info['severity']
        message = rule_info['message']
        rule_name = rule_info['rule_name']
        
        # 規約名別マーカーをチェック
        if session_id and self.is_rule_processed(session_id, rule_name):
            self.log_debug(f"Rule '{rule_name}' already processed in this session, skipping")
            return {
                'decision': 'approve',
                'reason': f'Rule "{rule_name}" within token threshold'
            }
        
        # 規約名別マーカーを作成（ブロック前に）
        if session_id:
            current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
            self.mark_rule_processed(session_id, rule_name, current_tokens or 0)
            self.log_debug(f"Created rule marker for '{rule_name}' before blocking with {current_tokens or 0} tokens")
        
        # JSON応答でブロック（sys.exit使わない）
        self.impl_logger.info(f"FILE RULE BLOCKING: Rule '{rule_name}' (severity: {severity}) blocking file edit: {absolute_path}")
        return {
            'decision': 'block',
            'reason': message
        }
    def run(self) -> int:
        """
        BaseHookのrun()を呼び出してコンテクスト制御を有効化
        規約名別マーカーとコンテクスト制御を併用
        """
        # BaseHookのrun()を呼び出してコンテクスト制御を有効化
        return super().run()
        

    def _process_command(self, tool_input: Dict[str, Any], session_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        コマンド実行時の規約チェック処理

        Args:
            tool_input: ツール入力データ
            session_id: セッションID
            input_data: 全体の入力データ

        Returns:
            ClaudeCode Hook出力形式の辞書 {'decision': 'block'/'approve', 'reason': 'メッセージ'}
        """
        command = tool_input.get('command', '')
        if not command:
            self.log_debug("No command found in tool_input")
            return {
                'decision': 'approve',
                'reason': 'No command found'
            }
        
        self.log_info(f"🔍 Checking command: {command}")
        
        # コマンド規約チェック（先に実行してrule_infoを取得）
        rule_info = self.command_matcher.get_confirmation_message(command)
        
        if not rule_info:
            self.log_info(f"❌ No command rules matched for: {command}")
            self.impl_logger.info(f"COMMAND NO RULE MATCHED: {command}")
            return {
                'decision': 'approve',
                'reason': 'No command rules matched'
            }
        
        # コマンド規約マッチしたログ
        self.impl_logger.info(f"COMMAND RULE MATCHED: {rule_info['rule_name']} (severity: {rule_info['severity']}, threshold: {rule_info.get('token_threshold', 'default')}) for command: {command}")
        
        # セッション内で同じコマンドが既に処理済みかチェック
        if session_id and self.is_command_processed(session_id, command):
            # 規約固有の閾値を取得（コマンド版）
            command_threshold = self._get_command_threshold(rule_info)
            
            # コマンドマーカーファイルから前回のトークン数を取得
            marker_path = self.get_command_marker_path(session_id, command)
            if marker_path.exists():
                try:
                    import json
                    with open(marker_path, 'r') as f:
                        marker_data = json.load(f)
                        last_tokens = marker_data.get('tokens', 0)
                    
                    # 現在のトークン数を取得
                    current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
                    if current_tokens is not None:
                        token_increase = current_tokens - last_tokens
                        
                        if token_increase < command_threshold:
                            self.log_info(f"✅ Command '{command}' within individual token threshold: {token_increase}/{command_threshold}, skipping")
                            self.impl_logger.info(f"INDIVIDUAL COMMAND TOKEN THRESHOLD SKIP: '{command}' increase {token_increase} < threshold {command_threshold}, skipping processing")
                            return {
                                'decision': 'approve',
                                'reason': f'Command within threshold ({token_increase}/{command_threshold})'
                            }
                        else:
                            self.log_info(f"🚨 Command '{command}' individual token threshold exceeded: {token_increase} >= {command_threshold}, processing")
                            self.impl_logger.info(f"INDIVIDUAL COMMAND TOKEN THRESHOLD EXCEEDED: '{command}' increase {token_increase} >= threshold {command_threshold}, proceeding with processing")
                            # 古いマーカーをリネーム
                            self._rename_expired_marker(marker_path)
                except Exception as e:
                    self.log_error(f"Error checking command individual token threshold: {e}")
            else:
                self.log_info(f"⚠️ Command marker file not found for '{command}', proceeding with processing")
        
        # セッション内でコマンドを処理済みとしてマーク
        if session_id:
            current_tokens = self._get_current_context_size(input_data.get('transcript_path'))
            self.mark_command_processed(session_id, command, current_tokens or 0)
            self.log_info(f"📝 Marked command as processed: {command}")
        
        # severityに応じて処理を分岐
        severity = rule_info['severity']
        message = rule_info['message']
        
        self.log_info(f"🚨 Command rule matched - Severity: {severity}, Rule: {rule_info['rule_name']}")
        
        # JSON応答でブロック（SessionStartupHookと同じ形式に統一）
        self.impl_logger.info(f"COMMAND RULE BLOCKING: Rule '{rule_info['rule_name']}' (severity: {severity}) blocking command: {command}")
        return {
            'decision': 'block',
            'reason': message
        }


def main():
    """メインエントリーポイント"""
    # ログをファイルのみに出力（stderrには出力しない）
    import logging
    import os

    # スクリプトが存在するディレクトリを動的に検知
    script_dir = os.path.dirname(os.path.abspath(__file__))
    scripts_root = os.path.join(script_dir, '..', '..', '..')  # src/domain/hooks -> scripts
    scripts_root = os.path.normpath(scripts_root)
    log_dir = os.path.join(scripts_root, 'log')

    # logディレクトリが存在しない場合は作成
    os.makedirs(log_dir, exist_ok=True)

    log_file_path = os.path.join(log_dir, 'hook_debug.log')

    logging.basicConfig(
        level=logging.ERROR,  # ERRORレベル以上のみ
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file_path)
            # StreamHandlerを削除してstderr出力を抑制
        ]
    )
    
    hook = ImplementationDesignHook(debug=False)  # デバッグモード無効
    # BaseHookのrun()メソッドを呼び出してマーカーフロー機能を有効化
    sys.exit(hook.run())


if __name__ == "__main__":
    main()