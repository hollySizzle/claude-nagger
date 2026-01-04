#!/usr/bin/env python3
"""フック出力スキーマ検証テスト

subprocessでフックを実行し、出力JSONのスキーマを検証する
"""

import pytest
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional


# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent


class HookSchemaValidator:
    """フック出力スキーマバリデータ"""
    
    # Claude Code v2 フック出力スキーマ
    REQUIRED_FIELDS = ['decision']
    
    OPTIONAL_FIELDS = [
        'reason', 
        'hookEventName', 
        'permissionDecision', 
        'permissionDecisionReason'
    ]
    
    VALID_DECISIONS = ['approve', 'block', 'allow', 'warn']
    VALID_PERMISSION_DECISIONS = ['allow', 'deny']
    
    def validate(self, output: str) -> Dict[str, Any]:
        """
        フック出力を検証
        
        Args:
            output: フックの標準出力
            
        Returns:
            検証結果辞書
        """
        result = {
            'valid': False,
            'errors': [],
            'warnings': [],
            'data': None
        }
        
        # 空出力は許可（処理対象外の場合）
        if not output.strip():
            result['valid'] = True
            result['warnings'].append('Empty output (hook skipped)')
            return result
        
        # JSON パース
        try:
            data = json.loads(output.strip())
            result['data'] = data
        except json.JSONDecodeError as e:
            result['errors'].append(f'Invalid JSON: {e}')
            return result
        
        # 必須フィールド検証
        for field in self.REQUIRED_FIELDS:
            if field not in data:
                result['errors'].append(f'Missing required field: {field}')
        
        # decision値の検証
        if 'decision' in data:
            if data['decision'] not in self.VALID_DECISIONS:
                result['errors'].append(
                    f"Invalid decision value: {data['decision']}. "
                    f"Expected one of: {self.VALID_DECISIONS}"
                )
        
        # permissionDecision値の検証（存在する場合）
        if 'permissionDecision' in data:
            if data['permissionDecision'] not in self.VALID_PERMISSION_DECISIONS:
                result['errors'].append(
                    f"Invalid permissionDecision: {data['permissionDecision']}. "
                    f"Expected one of: {self.VALID_PERMISSION_DECISIONS}"
                )
        
        # decision と permissionDecision の整合性
        if 'decision' in data and 'permissionDecision' in data:
            decision = data['decision']
            perm_decision = data['permissionDecision']
            
            # approve/allow と allow, block と deny の対応をチェック
            if decision in ['approve', 'allow'] and perm_decision != 'allow':
                result['warnings'].append(
                    f"Inconsistent decisions: decision={decision}, "
                    f"permissionDecision={perm_decision}"
                )
            elif decision == 'block' and perm_decision != 'deny':
                result['warnings'].append(
                    f"Inconsistent decisions: decision={decision}, "
                    f"permissionDecision={perm_decision}"
                )
        
        result['valid'] = len(result['errors']) == 0
        return result


class HookRunner:
    """フック実行ヘルパー"""
    
    def __init__(self, hook_script: Path):
        """
        初期化
        
        Args:
            hook_script: 実行するフックスクリプトのパス
        """
        self.hook_script = hook_script
        self.validator = HookSchemaValidator()
    
    def run_with_fixture(self, fixture_path: Path, timeout: int = 10) -> Dict[str, Any]:
        """
        フィクスチャを入力としてフックを実行
        
        Args:
            fixture_path: フィクスチャJSONファイルのパス
            timeout: タイムアウト秒数
            
        Returns:
            実行結果辞書
        """
        result = {
            'success': False,
            'stdout': '',
            'stderr': '',
            'return_code': None,
            'validation': None
        }
        
        try:
            with open(fixture_path, 'r', encoding='utf-8') as f:
                input_data = f.read()
            
            process = subprocess.run(
                [sys.executable, str(self.hook_script)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=PROJECT_ROOT
            )
            
            result['stdout'] = process.stdout
            result['stderr'] = process.stderr
            result['return_code'] = process.returncode
            result['success'] = process.returncode == 0
            
            # 出力スキーマ検証
            result['validation'] = self.validator.validate(process.stdout)
            
        except subprocess.TimeoutExpired:
            result['success'] = False
            result['stderr'] = f'Timeout after {timeout} seconds'
        except Exception as e:
            result['success'] = False
            result['stderr'] = str(e)
        
        return result
    
    def run_with_data(self, input_data: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        """
        辞書データを入力としてフックを実行
        
        Args:
            input_data: 入力データ辞書
            timeout: タイムアウト秒数
            
        Returns:
            実行結果辞書
        """
        result = {
            'success': False,
            'stdout': '',
            'stderr': '',
            'return_code': None,
            'validation': None
        }
        
        try:
            input_json = json.dumps(input_data, ensure_ascii=False)
            
            process = subprocess.run(
                [sys.executable, str(self.hook_script)],
                input=input_json,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=PROJECT_ROOT
            )
            
            result['stdout'] = process.stdout
            result['stderr'] = process.stderr
            result['return_code'] = process.returncode
            result['success'] = process.returncode == 0
            
            # 出力スキーマ検証
            result['validation'] = self.validator.validate(process.stdout)
            
        except subprocess.TimeoutExpired:
            result['success'] = False
            result['stderr'] = f'Timeout after {timeout} seconds'
        except Exception as e:
            result['success'] = False
            result['stderr'] = str(e)
        
        return result


# === pytest テストケース ===

class TestHookSchemaValidator:
    """HookSchemaValidator のユニットテスト"""
    
    @pytest.fixture
    def validator(self):
        return HookSchemaValidator()
    
    def test_valid_approve_output(self, validator):
        """正常な approve 出力の検証"""
        output = json.dumps({
            'decision': 'approve',
            'reason': 'Test approved',
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'allow',
            'permissionDecisionReason': 'Test approved'
        })
        
        result = validator.validate(output)
        assert result['valid'] is True
        assert len(result['errors']) == 0
    
    def test_valid_block_output(self, validator):
        """正常な block 出力の検証"""
        output = json.dumps({
            'decision': 'block',
            'reason': 'Test blocked',
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': 'Test blocked'
        })
        
        result = validator.validate(output)
        assert result['valid'] is True
        assert len(result['errors']) == 0
    
    def test_minimal_valid_output(self, validator):
        """最小限の有効な出力の検証"""
        output = json.dumps({'decision': 'approve'})
        
        result = validator.validate(output)
        assert result['valid'] is True
    
    def test_missing_decision(self, validator):
        """decision フィールド欠落の検証"""
        output = json.dumps({'reason': 'Test'})
        
        result = validator.validate(output)
        assert result['valid'] is False
        assert any('Missing required field: decision' in e for e in result['errors'])
    
    def test_invalid_decision_value(self, validator):
        """無効な decision 値の検証"""
        output = json.dumps({'decision': 'invalid_value'})
        
        result = validator.validate(output)
        assert result['valid'] is False
        assert any('Invalid decision value' in e for e in result['errors'])
    
    def test_empty_output(self, validator):
        """空出力の検証（スキップケース）"""
        result = validator.validate('')
        
        assert result['valid'] is True
        assert any('Empty output' in w for w in result['warnings'])
    
    def test_invalid_json(self, validator):
        """不正なJSONの検証"""
        result = validator.validate('not a json')
        
        assert result['valid'] is False
        assert any('Invalid JSON' in e for e in result['errors'])
    
    def test_inconsistent_decisions_warning(self, validator):
        """decision と permissionDecision の不整合警告"""
        output = json.dumps({
            'decision': 'approve',
            'permissionDecision': 'deny'  # 不整合
        })
        
        result = validator.validate(output)
        # エラーではなく警告
        assert result['valid'] is True
        assert any('Inconsistent' in w for w in result['warnings'])


class TestImplementationDesignHookIntegration:
    """ImplementationDesignHook の結合テスト"""
    
    @pytest.fixture
    def hook_runner(self):
        hook_path = PROJECT_ROOT / 'src' / 'domain' / 'hooks' / 'implementation_design_hook.py'
        return HookRunner(hook_path)
    
    @pytest.fixture
    def fixture_dir(self):
        return PROJECT_ROOT / 'tests' / 'fixtures' / 'claude_code'
    
    def test_hook_with_non_matching_input(self, hook_runner):
        """マッチしない入力での実行テスト"""
        input_data = {
            'session_id': '00000000-0000-0000-0000-000000000000',
            'tool_input': {
                'file_path': '/some/random/file.txt'
            }
        }
        
        result = hook_runner.run_with_data(input_data)
        
        # 正常終了（処理対象外でスキップ）
        assert result['success'] is True
        # 空出力またはスキーマ準拠出力
        if result['stdout'].strip():
            assert result['validation']['valid'] is True
    
    def test_hook_with_design_doc_input(self, hook_runner):
        """設計書ファイルでの実行テスト"""
        input_data = {
            'session_id': '00000000-0000-0000-0000-000000000000',
            'tool_input': {
                'file_path': '/workspace/vibes/docs/実装設計書.pu'
            }
        }
        
        result = hook_runner.run_with_data(input_data)
        
        # 正常終了
        assert result['success'] is True
        # 出力がある場合はスキーマ準拠
        if result['stdout'].strip():
            assert result['validation']['valid'] is True
    
    def test_hook_output_schema_compliance(self, hook_runner):
        """出力スキーマ準拠テスト"""
        # マッチするファイルパスでフックをトリガー
        input_data = {
            'session_id': '00000000-0000-0000-0000-000000000000',
            'tool_name': 'Edit',
            'tool_input': {
                'file_path': '/workspace/vibes/docs/specs/実装設計書.pu',
                'old_string': 'test',
                'new_string': 'updated'
            }
        }
        
        result = hook_runner.run_with_data(input_data)
        
        # 出力がある場合のみスキーマ検証
        if result['stdout'].strip():
            validation = result['validation']
            assert validation['valid'] is True, f"Schema errors: {validation['errors']}"
            
            # decision フィールドの存在確認
            if validation['data']:
                assert 'decision' in validation['data']


class TestCapturedFixtures:
    """キャプチャ済みフィクスチャを使用したテスト"""
    
    @pytest.fixture
    def fixture_dir(self):
        return PROJECT_ROOT / 'tests' / 'fixtures' / 'claude_code'
    
    def get_all_fixtures(self, fixture_dir: Path):
        """全フィクスチャファイルを取得"""
        fixtures = []
        for json_file in fixture_dir.glob('**/*.json'):
            if not json_file.name.startswith('.'):
                fixtures.append(json_file)
        return fixtures
    
    def test_fixtures_are_valid_json(self, fixture_dir):
        """全フィクスチャがパース可能なJSONであることを確認"""
        fixtures = self.get_all_fixtures(fixture_dir)
        
        for fixture in fixtures:
            try:
                with open(fixture, 'r', encoding='utf-8') as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {fixture}: {e}")
    
    def test_fixtures_are_sanitized(self, fixture_dir):
        """フィクスチャがサニタイズ済みであることを確認"""
        fixtures = self.get_all_fixtures(fixture_dir)
        
        # チェック対象パターン（サニタイズされていない場合に検出）
        dangerous_patterns = [
            r'/Users/(?!testuser)',  # testuser以外のホームディレクトリ
            r'/home/(?!testuser)',
            r'sk-[a-zA-Z0-9]{20,}',  # APIキー
            r'xoxb-',  # Slackトークン
        ]
        
        import re
        
        for fixture in fixtures:
            with open(fixture, 'r', encoding='utf-8') as f:
                content = f.read()
            
            for pattern in dangerous_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    pytest.fail(
                        f"Potentially unsanitized data in {fixture}: "
                        f"pattern '{pattern}' found"
                    )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
