#!/usr/bin/env python3
"""フィクスチャキャプチャスクリプト

/tmp/claude/からテストフィクスチャを取り込む
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# 相対インポート用
import sys
sys.path.insert(0, str(Path(__file__).parent))
from sanitizer import FixtureSanitizer


class FixtureCapture:
    """フィクスチャキャプチャ管理"""
    
    # キャプチャ元ディレクトリ
    SOURCE_DIR = Path("/tmp/claude")
    
    # フィクスチャ保存先
    FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "claude_code"
    
    # イベント種別の推定パターン
    EVENT_PATTERNS = {
        'pre_tool_use': ['PreToolUse', 'tool_input'],
        'post_tool_use': ['PostToolUse', 'tool_result'],
    }
    
    # ツール種別の推定パターン
    TOOL_PATTERNS = {
        'edit': ['Edit', 'file_path', 'old_string', 'new_string'],
        'write': ['Write', 'content'],
        'bash': ['Bash', 'command'],
        'read': ['Read'],
        'glob': ['Glob', 'pattern'],
        'grep': ['Grep'],
    }
    
    def __init__(self, source_dir: Path = None, fixture_dir: Path = None):
        """
        初期化
        
        Args:
            source_dir: キャプチャ元ディレクトリ
            fixture_dir: フィクスチャ保存先
        """
        self.source_dir = source_dir or self.SOURCE_DIR
        self.fixture_dir = fixture_dir or self.FIXTURE_DIR
        self.sanitizer = FixtureSanitizer()
    
    def detect_event_type(self, data: dict) -> str:
        """
        JSONデータからイベント種別を推定
        
        Args:
            data: パース済みJSONデータ
            
        Returns:
            イベント種別（pre_tool_use/post_tool_use/unknown）
        """
        json_str = json.dumps(data)
        
        for event_type, patterns in self.EVENT_PATTERNS.items():
            if any(pattern in json_str for pattern in patterns):
                return event_type
        
        return 'unknown'
    
    def detect_tool_type(self, data: dict) -> str:
        """
        JSONデータからツール種別を推定
        
        Args:
            data: パース済みJSONデータ
            
        Returns:
            ツール種別（edit/write/bash等/unknown）
        """
        # tool_nameフィールドから直接取得を試行
        tool_name = data.get('tool_name', '')
        if tool_name:
            return tool_name.lower()
        
        json_str = json.dumps(data)
        
        for tool_type, patterns in self.TOOL_PATTERNS.items():
            if any(pattern in json_str for pattern in patterns):
                return tool_type
        
        return 'unknown'
    
    def get_captured_files(self) -> List[Path]:
        """
        キャプチャ元ディレクトリのJSONファイル一覧を取得
        
        Returns:
            JSONファイルパスのリスト（更新日時順）
        """
        if not self.source_dir.exists():
            return []
        
        files = list(self.source_dir.glob("*.json"))
        # 更新日時でソート（新しい順）
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return files
    
    def generate_fixture_name(self, data: dict, scenario: str = None) -> str:
        """
        フィクスチャファイル名を生成
        
        Args:
            data: パース済みJSONデータ
            scenario: シナリオ名（任意）
            
        Returns:
            ファイル名
        """
        event_type = self.detect_event_type(data)
        tool_type = self.detect_tool_type(data)
        date_str = datetime.now().strftime("%Y%m%d")
        
        if scenario:
            return f"{event_type}_{tool_type}_{scenario}_{date_str}.json"
        else:
            return f"{event_type}_{tool_type}_{date_str}.json"
    
    def capture_latest(self, 
                       count: int = 1, 
                       sanitize: bool = True,
                       scenario: str = None) -> List[Path]:
        """
        最新のキャプチャデータをフィクスチャとして保存
        
        Args:
            count: 取り込むファイル数
            sanitize: サニタイズを実行するか
            scenario: シナリオ名（ファイル名に含める）
            
        Returns:
            保存したファイルパスのリスト
        """
        captured_files = self.get_captured_files()
        if not captured_files:
            print("No captured files found in /tmp/claude/")
            return []
        
        saved_files = []
        
        for i, source_file in enumerate(captured_files[:count]):
            try:
                with open(source_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                event_type = self.detect_event_type(data)
                tool_type = self.detect_tool_type(data)
                
                # 保存先ディレクトリ
                dest_dir = self.fixture_dir / event_type / tool_type
                dest_dir.mkdir(parents=True, exist_ok=True)
                
                # ファイル名生成
                fixture_name = self.generate_fixture_name(data, scenario)
                dest_path = dest_dir / fixture_name
                
                # 重複回避
                counter = 1
                while dest_path.exists():
                    base_name = fixture_name.replace('.json', f'_{counter}.json')
                    dest_path = dest_dir / base_name
                    counter += 1
                
                # サニタイズして保存
                if sanitize:
                    sanitized_data = self.sanitizer.sanitize_dict(data)
                    with open(dest_path, 'w', encoding='utf-8') as f:
                        json.dump(sanitized_data, f, ensure_ascii=False, indent=2)
                else:
                    shutil.copy2(source_file, dest_path)
                
                print(f"Captured: {source_file.name} -> {dest_path}")
                saved_files.append(dest_path)
                
            except Exception as e:
                print(f"Error processing {source_file}: {e}")
        
        return saved_files
    
    def list_fixtures(self) -> dict:
        """
        現在のフィクスチャ一覧を取得
        
        Returns:
            イベント・ツール別のフィクスチャ数
        """
        result = {}
        
        for event_dir in self.fixture_dir.iterdir():
            if not event_dir.is_dir() or event_dir.name.startswith('.'):
                continue
            
            result[event_dir.name] = {}
            
            for tool_dir in event_dir.iterdir():
                if not tool_dir.is_dir():
                    continue
                
                fixtures = list(tool_dir.glob("*.json"))
                result[event_dir.name][tool_dir.name] = len(fixtures)
        
        return result
    
    def validate_fixture(self, fixture_path: Path) -> dict:
        """
        フィクスチャの検証
        
        Args:
            fixture_path: フィクスチャファイルパス
            
        Returns:
            検証結果
        """
        result = {
            'valid': False,
            'errors': [],
            'warnings': []
        }
        
        try:
            with open(fixture_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 秘密情報チェック
            json_str = json.dumps(data)
            
            # ホームディレクトリパスが残っていないか
            if '/Users/' in json_str and '/Users/testuser' not in json_str:
                result['warnings'].append("Potential home directory path found")
            
            # セッションIDが残っていないか（サニタイズ後以外）
            import re
            uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
            uuids = re.findall(uuid_pattern, json_str)
            real_uuids = [u for u in uuids if u != '00000000-0000-0000-0000-000000000000']
            if real_uuids:
                result['warnings'].append(f"Potential session IDs found: {real_uuids[:3]}")
            
            result['valid'] = len(result['errors']) == 0
            
        except json.JSONDecodeError as e:
            result['errors'].append(f"Invalid JSON: {e}")
        except Exception as e:
            result['errors'].append(f"Error: {e}")
        
        return result


def main():
    """CLI エントリーポイント"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Capture Claude Code fixtures')
    parser.add_argument('--count', '-n', type=int, default=1,
                       help='Number of files to capture')
    parser.add_argument('--sanitize', '-s', action='store_true', default=True,
                       help='Sanitize captured data')
    parser.add_argument('--no-sanitize', action='store_false', dest='sanitize',
                       help='Skip sanitization (dangerous!)')
    parser.add_argument('--scenario', help='Scenario name for fixture')
    parser.add_argument('--list', '-l', action='store_true',
                       help='List current fixtures')
    parser.add_argument('--validate', '-v', help='Validate a fixture file')
    
    args = parser.parse_args()
    
    capture = FixtureCapture()
    
    if args.list:
        fixtures = capture.list_fixtures()
        print("\nCurrent fixtures:")
        for event, tools in fixtures.items():
            print(f"\n  {event}/")
            for tool, count in tools.items():
                print(f"    {tool}/: {count} files")
        return
    
    if args.validate:
        result = capture.validate_fixture(Path(args.validate))
        print(f"\nValidation result: {'PASSED' if result['valid'] else 'FAILED'}")
        if result['errors']:
            print("Errors:")
            for e in result['errors']:
                print(f"  - {e}")
        if result['warnings']:
            print("Warnings:")
            for w in result['warnings']:
                print(f"  - {w}")
        return
    
    # デフォルト: キャプチャ実行
    saved = capture.capture_latest(
        count=args.count,
        sanitize=args.sanitize,
        scenario=args.scenario
    )
    
    if saved:
        print(f"\nCaptured {len(saved)} fixture(s)")
    else:
        print("\nNo files captured")


if __name__ == '__main__':
    main()
