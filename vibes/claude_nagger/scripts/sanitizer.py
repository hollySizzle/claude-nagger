#!/usr/bin/env python3
"""秘密情報サニタイズスクリプト

Claude Codeのフィクスチャデータから秘密情報を削除・マスクする
"""

import json
import re
import os
from pathlib import Path
from typing import Any, Dict, List


class FixtureSanitizer:
    """フィクスチャデータのサニタイザー"""
    
    # マスク対象パターン
    PATTERNS = {
        # ファイルパス（ホームディレクトリ）
        'home_path': (r'/Users/[^/\s"]+', '/Users/testuser'),
        'home_path_linux': (r'/home/[^/\s"]+', '/home/testuser'),
        
        # セッションID
        'session_id': (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 
                       '00000000-0000-0000-0000-000000000000'),
        
        # タイムスタンプ（ISOフォーマット）
        'timestamp_iso': (r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', '2026-01-01T00:00:00'),
        
        # タイムスタンプ（ファイル名用）
        'timestamp_file': (r'\d{8}_\d{6}_\d+', '20260101_000000_000000'),
        
        # APIキー等（明示的なパターン）
        'api_key': (r'(sk-[a-zA-Z0-9]{20,}|xoxb-[a-zA-Z0-9-]+)', 'REDACTED_API_KEY'),
        
        # Discord Webhook URL
        'discord_webhook': (r'https://discord\.com/api/webhooks/[^\s"]+', 
                           'https://discord.com/api/webhooks/REDACTED'),
        
        # 環境変数内の秘密情報
        'env_secret': (r'"(DISCORD_WEBHOOK_URL|API_KEY|SECRET_KEY|PASSWORD)":\s*"[^"]*"',
                      r'"\1": "REDACTED"'),
    }
    
    # 完全削除するキー
    REMOVE_KEYS = [
        'api_key', 'secret', 'password', 'token', 'webhook_url',
        'private_key', 'credentials', 'auth_token'
    ]
    
    def __init__(self, additional_patterns: Dict[str, tuple] = None):
        """
        初期化
        
        Args:
            additional_patterns: 追加のマスクパターン
        """
        self.patterns = dict(self.PATTERNS)
        if additional_patterns:
            self.patterns.update(additional_patterns)
    
    def sanitize_string(self, text: str) -> str:
        """
        文字列内の秘密情報をサニタイズ
        
        Args:
            text: 入力文字列
            
        Returns:
            サニタイズ済み文字列
        """
        result = text
        for name, (pattern, replacement) in self.patterns.items():
            result = re.sub(pattern, replacement, result)
        return result
    
    def sanitize_dict(self, data: Dict[str, Any], path: str = '') -> Dict[str, Any]:
        """
        辞書データを再帰的にサニタイズ
        
        Args:
            data: 入力辞書
            path: 現在のパス（デバッグ用）
            
        Returns:
            サニタイズ済み辞書
        """
        result = {}
        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key
            
            # 削除対象キーはスキップ
            if any(remove_key in key.lower() for remove_key in self.REMOVE_KEYS):
                result[key] = "REDACTED"
                continue
            
            if isinstance(value, dict):
                result[key] = self.sanitize_dict(value, current_path)
            elif isinstance(value, list):
                result[key] = self.sanitize_list(value, current_path)
            elif isinstance(value, str):
                result[key] = self.sanitize_string(value)
            else:
                result[key] = value
        
        return result
    
    def sanitize_list(self, data: List[Any], path: str = '') -> List[Any]:
        """
        リストデータを再帰的にサニタイズ
        
        Args:
            data: 入力リスト
            path: 現在のパス（デバッグ用）
            
        Returns:
            サニタイズ済みリスト
        """
        result = []
        for i, item in enumerate(data):
            current_path = f"{path}[{i}]"
            
            if isinstance(item, dict):
                result.append(self.sanitize_dict(item, current_path))
            elif isinstance(item, list):
                result.append(self.sanitize_list(item, current_path))
            elif isinstance(item, str):
                result.append(self.sanitize_string(item))
            else:
                result.append(item)
        
        return result
    
    def sanitize_json(self, json_str: str) -> str:
        """
        JSON文字列をサニタイズ
        
        Args:
            json_str: 入力JSON文字列
            
        Returns:
            サニタイズ済みJSON文字列
        """
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                sanitized = self.sanitize_dict(data)
            elif isinstance(data, list):
                sanitized = self.sanitize_list(data)
            else:
                return self.sanitize_string(json_str)
            
            return json.dumps(sanitized, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            # JSONでない場合は文字列としてサニタイズ
            return self.sanitize_string(json_str)
    
    def sanitize_file(self, input_path: Path, output_path: Path = None) -> Path:
        """
        ファイルをサニタイズして保存
        
        Args:
            input_path: 入力ファイルパス
            output_path: 出力ファイルパス（省略時は入力を上書き）
            
        Returns:
            出力ファイルパス
        """
        output_path = output_path or input_path
        
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        sanitized = self.sanitize_json(content)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(sanitized)
        
        return output_path


def main():
    """CLI エントリーポイント"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Sanitize fixture files')
    parser.add_argument('input', help='Input file or directory')
    parser.add_argument('-o', '--output', help='Output file or directory')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')
    
    args = parser.parse_args()
    
    sanitizer = FixtureSanitizer()
    input_path = Path(args.input)
    
    if input_path.is_file():
        if args.dry_run:
            with open(input_path, 'r', encoding='utf-8') as f:
                original = f.read()
            sanitized = sanitizer.sanitize_json(original)
            print(sanitized)
        else:
            output_path = Path(args.output) if args.output else None
            result = sanitizer.sanitize_file(input_path, output_path)
            print(f"Sanitized: {result}")
    
    elif input_path.is_dir():
        output_dir = Path(args.output) if args.output else input_path
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for json_file in input_path.glob('**/*.json'):
            relative = json_file.relative_to(input_path)
            output_file = output_dir / relative
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            if args.dry_run:
                print(f"Would sanitize: {json_file}")
            else:
                sanitizer.sanitize_file(json_file, output_file)
                print(f"Sanitized: {output_file}")


if __name__ == '__main__':
    main()
