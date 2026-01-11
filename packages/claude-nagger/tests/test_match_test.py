#!/usr/bin/env python3
"""match-testコマンドのテスト"""

import pytest
from io import StringIO
from unittest.mock import patch
from application.match_test import MatchTestCommand


class TestMatchTestCommand:
    """MatchTestCommandのテスト"""
    
    def test_file_pattern_match(self):
        """ファイルパターンがマッチする場合"""
        cmd = MatchTestCommand(
            file_path="app/views/test.erb",
            pattern="app/views/**/*.erb"
        )
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cmd.execute()
        
        assert result == 0
        output = mock_stdout.getvalue()
        assert "Pattern: app/views/**/*.erb" in output
        assert "File: app/views/test.erb" in output
        assert "✅ MATCH" in output
    
    def test_file_pattern_no_match(self):
        """ファイルパターンがマッチしない場合"""
        cmd = MatchTestCommand(
            file_path="app/models/user.rb",
            pattern="app/views/**/*.erb"
        )
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cmd.execute()
        
        assert result == 0
        output = mock_stdout.getvalue()
        assert "❌ NO MATCH" in output
    
    def test_command_pattern_match(self):
        """コマンドパターンがマッチする場合"""
        cmd = MatchTestCommand(
            command="git push origin main",
            pattern="git push*"
        )
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cmd.execute()
        
        assert result == 0
        output = mock_stdout.getvalue()
        assert "Pattern: git push*" in output
        assert "Command: git push origin main" in output
        assert "✅ MATCH" in output
    
    def test_command_pattern_no_match(self):
        """コマンドパターンがマッチしない場合"""
        cmd = MatchTestCommand(
            command="npm install",
            pattern="git push*"
        )
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cmd.execute()
        
        assert result == 0
        output = mock_stdout.getvalue()
        assert "❌ NO MATCH" in output
    
    def test_missing_pattern_error(self):
        """パターン未指定エラー"""
        cmd = MatchTestCommand(
            file_path="test.txt",
            pattern=None
        )
        
        with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            result = cmd.execute()
        
        assert result == 1
        assert "--pattern is required" in mock_stderr.getvalue()
    
    def test_missing_target_error(self):
        """ターゲット未指定エラー"""
        cmd = MatchTestCommand(
            pattern="*.txt"
        )
        
        with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            result = cmd.execute()
        
        assert result == 1
        assert "Either --file or --command is required" in mock_stderr.getvalue()
    
    def test_both_targets_error(self):
        """両方指定エラー"""
        cmd = MatchTestCommand(
            file_path="test.txt",
            command="git status",
            pattern="*.txt"
        )
        
        with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            result = cmd.execute()
        
        assert result == 1
        assert "Cannot specify both --file and --command" in mock_stderr.getvalue()
    
    def test_glob_star_pattern(self):
        """**パターンのテスト"""
        cmd = MatchTestCommand(
            file_path="src/domain/services/file_convention_matcher.py",
            pattern="src/**/*.py"
        )
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cmd.execute()
        
        assert result == 0
        assert "✅ MATCH" in mock_stdout.getvalue()
    
    def test_single_star_pattern(self):
        """*パターンのテスト"""
        cmd = MatchTestCommand(
            file_path="test.py",
            pattern="*.py"
        )
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            result = cmd.execute()
        
        assert result == 0
        assert "✅ MATCH" in mock_stdout.getvalue()
