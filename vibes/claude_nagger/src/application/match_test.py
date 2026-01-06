#!/usr/bin/env python3
"""パターンマッチングテストコマンド"""

import sys
from typing import Optional


class MatchTestCommand:
    """
    パターンマッチングのdry-run検証コマンド
    
    ユースケース:
    - 記法不明時の事前検証
    - 問合せ対応時のデバッグ
    - 設定変更時の動作確認
    """
    
    def __init__(
        self,
        file_path: Optional[str] = None,
        command: Optional[str] = None,
        pattern: Optional[str] = None
    ):
        """
        Args:
            file_path: テスト対象のファイルパス
            command: テスト対象のコマンド
            pattern: マッチングパターン
        """
        self.file_path = file_path
        self.command = command
        self.pattern = pattern
    
    def execute(self) -> int:
        """コマンド実行"""
        # 入力検証
        if not self.pattern:
            print("❌ Error: --pattern is required", file=sys.stderr)
            return 1
        
        if not self.file_path and not self.command:
            print("❌ Error: Either --file or --command is required", file=sys.stderr)
            return 1
        
        if self.file_path and self.command:
            print("❌ Error: Cannot specify both --file and --command", file=sys.stderr)
            return 1
        
        # マッチング実行
        if self.file_path:
            return self._test_file_pattern()
        else:
            return self._test_command_pattern()
    
    def _test_file_pattern(self) -> int:
        """ファイルパターンマッチテスト"""
        from domain.services.file_convention_matcher import FileConventionMatcher
        
        matcher = FileConventionMatcher(rules_file=None, debug=False)
        patterns = [self.pattern]
        
        matched = matcher.matches_pattern(self.file_path, patterns)
        
        self._print_result("File", self.file_path, matched)
        return 0
    
    def _test_command_pattern(self) -> int:
        """コマンドパターンマッチテスト"""
        from domain.services.command_convention_matcher import CommandConventionMatcher
        
        matcher = CommandConventionMatcher(rules_file=None, debug=False)
        patterns = [self.pattern]
        
        matched = matcher.matches_pattern(self.command, patterns)
        
        self._print_result("Command", self.command, matched)
        return 0
    
    def _print_result(self, target_type: str, target: str, matched: bool) -> None:
        """結果を整形出力"""
        result_icon = "✅ MATCH" if matched else "❌ NO MATCH"
        
        print(f"Pattern: {self.pattern}")
        print(f"{target_type}: {target}")
        print(f"Result: {result_icon}")
