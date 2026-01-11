#!/usr/bin/env python3
"""サニタイザーのテスト"""

import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from sanitizer import FixtureSanitizer


class TestFixtureSanitizer:
    """FixtureSanitizer のテスト"""
    
    @pytest.fixture
    def sanitizer(self):
        return FixtureSanitizer()
    
    def test_sanitize_home_path_mac(self, sanitizer):
        """macOSホームディレクトリパスのサニタイズ"""
        text = '/Users/realuser/workspace/project'
        result = sanitizer.sanitize_string(text)
        assert '/Users/testuser/' in result
        assert 'realuser' not in result
    
    def test_sanitize_home_path_linux(self, sanitizer):
        """Linuxホームディレクトリパスのサニタイズ"""
        text = '/home/realuser/workspace/project'
        result = sanitizer.sanitize_string(text)
        assert '/home/testuser/' in result
        assert 'realuser' not in result
    
    def test_sanitize_session_id(self, sanitizer):
        """セッションIDのサニタイズ"""
        text = 'session_id: a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        result = sanitizer.sanitize_string(text)
        assert '00000000-0000-0000-0000-000000000000' in result
        assert 'a1b2c3d4' not in result
    
    def test_sanitize_api_key(self, sanitizer):
        """APIキーのサニタイズ"""
        text = 'api_key: sk-abcdefghijklmnopqrstuvwxyz123456'
        result = sanitizer.sanitize_string(text)
        assert 'REDACTED_API_KEY' in result
        assert 'sk-abcdefghij' not in result
    
    def test_sanitize_discord_webhook(self, sanitizer):
        """Discord Webhook URLのサニタイズ"""
        text = 'url: https://discord.com/api/webhooks/123456789/abcdefghijklmnop'
        result = sanitizer.sanitize_string(text)
        assert 'REDACTED' in result
        assert '123456789' not in result
    
    def test_sanitize_dict_removes_sensitive_keys(self, sanitizer):
        """秘密情報キーの削除"""
        data = {
            'normal_key': 'value',
            'api_key': 'secret_value',
            'password': 'my_password',
            'auth_token': 'token123'
        }
        result = sanitizer.sanitize_dict(data)
        
        assert result['normal_key'] == 'value'
        assert result['api_key'] == 'REDACTED'
        assert result['password'] == 'REDACTED'
        assert result['auth_token'] == 'REDACTED'
    
    def test_sanitize_nested_dict(self, sanitizer):
        """ネストした辞書のサニタイズ"""
        data = {
            'level1': {
                'level2': {
                    'file_path': '/Users/realuser/project',
                    'secret': 'sensitive_data'
                }
            }
        }
        result = sanitizer.sanitize_dict(data)
        
        assert '/Users/testuser/' in result['level1']['level2']['file_path']
        assert result['level1']['level2']['secret'] == 'REDACTED'
    
    def test_sanitize_list(self, sanitizer):
        """リストのサニタイズ"""
        data = [
            '/Users/realuser/path1',
            '/Users/anotheruser/path2',
            'normal_string'
        ]
        result = sanitizer.sanitize_list(data)
        
        assert '/Users/testuser/' in result[0]
        assert '/Users/testuser/' in result[1]
        assert result[2] == 'normal_string'
    
    def test_sanitize_json_string(self, sanitizer):
        """JSON文字列のサニタイズ"""
        json_str = json.dumps({
            'session_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            'path': '/Users/realuser/workspace'
        })
        result = sanitizer.sanitize_json(json_str)
        parsed = json.loads(result)
        
        assert parsed['session_id'] == '00000000-0000-0000-0000-000000000000'
        assert '/Users/testuser/' in parsed['path']
    
    def test_sanitize_preserves_structure(self, sanitizer):
        """サニタイズ後も構造が維持されることを確認"""
        data = {
            'tool_input': {
                'file_path': '/Users/user/file.txt',
                'content': 'some content'
            },
            'session_id': 'abcd1234-5678-90ab-cdef-1234567890ab',
            'metadata': {
                'timestamp': '2026-01-04T10:00:00',
                'items': ['item1', '/Users/user/item2']
            }
        }
        result = sanitizer.sanitize_dict(data)
        
        # 構造確認
        assert 'tool_input' in result
        assert 'file_path' in result['tool_input']
        assert 'content' in result['tool_input']
        assert 'metadata' in result
        assert 'items' in result['metadata']
        assert len(result['metadata']['items']) == 2
    
    def test_additional_patterns(self):
        """追加パターンの適用"""
        additional = {
            'custom_pattern': (r'CUSTOM_\d+', 'CUSTOM_REDACTED')
        }
        sanitizer = FixtureSanitizer(additional_patterns=additional)
        
        text = 'value: CUSTOM_12345'
        result = sanitizer.sanitize_string(text)
        assert 'CUSTOM_REDACTED' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
