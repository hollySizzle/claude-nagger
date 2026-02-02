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
    """フック出力スキーマバリデータ（Claude Code公式スキーマ対応）"""

    # Claude Code 公式フック出力スキーマ
    # 新形式: hookSpecificOutput を使用
    # ask: UIでツール呼び出しを確認するようユーザーに求める
    VALID_PERMISSION_DECISIONS = ['allow', 'deny', 'ask']
    # 全イベント名（ClaudeCodeHooks.md より）
    VALID_HOOK_EVENT_NAMES = [
        'PreToolUse',       # ツール実行前
        'PostToolUse',      # ツール実行後
        'PermissionRequest',# 許可リクエスト
        'Notification',     # 通知
        'Stop',             # 停止
        'SubagentStop',     # サブエージェント停止
        'UserPromptSubmit', # ユーザープロンプト送信
        'PreCompact',       # コンパクト前
        'SessionStart',     # セッション開始
        'SessionEnd',       # セッション終了
    ]

    def validate(self, output: str) -> Dict[str, Any]:
        """
        フック出力を検証（公式スキーマ対応）

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

        # hookSpecificOutput の存在確認
        if 'hookSpecificOutput' not in data:
            result['errors'].append('Missing required field: hookSpecificOutput')
            return result

        hook_output = data['hookSpecificOutput']

        # hookEventName の検証
        if 'hookEventName' not in hook_output:
            result['errors'].append('Missing hookSpecificOutput.hookEventName')
        elif hook_output['hookEventName'] not in self.VALID_HOOK_EVENT_NAMES:
            result['warnings'].append(
                f"Unknown hookEventName: {hook_output['hookEventName']}"
            )

        # permissionDecision の検証
        if 'permissionDecision' not in hook_output:
            result['errors'].append('Missing hookSpecificOutput.permissionDecision')
        elif hook_output['permissionDecision'] not in self.VALID_PERMISSION_DECISIONS:
            result['errors'].append(
                f"Invalid permissionDecision: {hook_output['permissionDecision']}. "
                f"Expected one of: {self.VALID_PERMISSION_DECISIONS}"
            )

        # permissionDecisionReason の検証（オプション）
        if 'permissionDecisionReason' in hook_output:
            if not isinstance(hook_output['permissionDecisionReason'], str):
                result['warnings'].append(
                    'permissionDecisionReason should be a string'
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
        # subprocess用の環境変数（PYTHONPATHを明示設定）
        import os
        self._env = os.environ.copy()
        self._env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

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
                cwd=PROJECT_ROOT,
                env=self._env
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
                cwd=PROJECT_ROOT,
                env=self._env
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
    """HookSchemaValidator のユニットテスト（公式スキーマ対応）"""

    @pytest.fixture
    def validator(self):
        return HookSchemaValidator()

    def test_valid_allow_output(self, validator):
        """正常な allow 出力の検証（hookSpecificOutput形式）"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'allow',
                'permissionDecisionReason': 'Test approved'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is True
        assert len(result['errors']) == 0

    def test_valid_deny_output(self, validator):
        """正常な deny 出力の検証（hookSpecificOutput形式）"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': 'Test blocked'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is True
        assert len(result['errors']) == 0

    def test_minimal_valid_output(self, validator):
        """最小限の有効な出力の検証"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'allow'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is True

    def test_missing_hook_specific_output(self, validator):
        """hookSpecificOutput フィールド欠落の検証"""
        output = json.dumps({'reason': 'Test'})

        result = validator.validate(output)
        assert result['valid'] is False
        assert any('Missing required field: hookSpecificOutput' in e for e in result['errors'])

    def test_missing_permission_decision(self, validator):
        """permissionDecision フィールド欠落の検証"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is False
        assert any('Missing hookSpecificOutput.permissionDecision' in e for e in result['errors'])

    def test_invalid_permission_decision_value(self, validator):
        """無効な permissionDecision 値の検証"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'invalid_value'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is False
        assert any('Invalid permissionDecision' in e for e in result['errors'])

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

    def test_unknown_hook_event_name_warning(self, validator):
        """未知の hookEventName での警告"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'UnknownEvent',
                'permissionDecision': 'allow'
            }
        })

        result = validator.validate(output)
        # エラーではなく警告
        assert result['valid'] is True
        assert any('Unknown hookEventName' in w for w in result['warnings'])


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


class TestHooksWithCapturedFixtures:
    """キャプチャ済みフィクスチャを使用したフック実行テスト"""
    
    @pytest.fixture
    def fixture_dir(self):
        return PROJECT_ROOT / 'tests' / 'fixtures' / 'claude_code'
    
    @pytest.fixture
    def hook_runner(self):
        """implementation_design_hook用のHookRunner"""
        hook_path = PROJECT_ROOT / 'src' / 'domain' / 'hooks' / 'implementation_design_hook.py'
        return HookRunner(hook_path)
    
    def get_all_fixtures(self, fixture_dir: Path):
        """全フィクスチャファイルを取得"""
        fixtures = []
        for json_file in fixture_dir.glob('**/*.json'):
            if not json_file.name.startswith('.'):
                fixtures.append(json_file)
        return fixtures
    
    def get_fixtures_by_tool(self, fixture_dir: Path):
        """ツールタイプ別にフィクスチャを分類"""
        fixtures_by_tool = {}
        for json_file in fixture_dir.glob('**/*.json'):
            if json_file.name.startswith('.'):
                continue
            # パス構造: .../pre_tool_use/{tool_name}/filename.json
            tool_name = json_file.parent.name
            if tool_name not in fixtures_by_tool:
                fixtures_by_tool[tool_name] = []
            fixtures_by_tool[tool_name].append(json_file)
        return fixtures_by_tool
    
    def test_all_fixtures_produce_valid_output(self, hook_runner, fixture_dir):
        """全フィクスチャでフック実行し、出力スキーマ準拠を確認"""
        fixtures = self.get_all_fixtures(fixture_dir)
        assert len(fixtures) > 0, "No fixtures found"
        
        errors = []
        for fixture in fixtures:
            result = hook_runner.run_with_fixture(fixture)
            
            # 実行エラーチェック
            if not result['success']:
                errors.append(f"{fixture.name}: Execution failed - {result['stderr']}")
                continue
            
            # 出力がある場合はスキーマ検証
            if result['stdout'].strip():
                validation = result['validation']
                if not validation['valid']:
                    errors.append(
                        f"{fixture.name}: Schema validation failed - {validation['errors']}"
                    )
        
        if errors:
            pytest.fail(f"Fixture test failures:\n" + "\n".join(errors))
    
    def test_fixtures_by_tool_type(self, hook_runner, fixture_dir):
        """各ツールタイプ別にフィクスチャでフック実行テスト"""
        fixtures_by_tool = self.get_fixtures_by_tool(fixture_dir)
        assert len(fixtures_by_tool) > 0, "No fixtures found"
        
        results_summary = {}
        
        for tool_name, fixtures in fixtures_by_tool.items():
            tool_results = {
                'total': len(fixtures),
                'success': 0,
                'skipped': 0,
                'failed': 0,
                'errors': []
            }
            
            for fixture in fixtures:
                result = hook_runner.run_with_fixture(fixture)
                
                if not result['success']:
                    tool_results['failed'] += 1
                    tool_results['errors'].append(
                        f"{fixture.name}: {result['stderr']}"
                    )
                elif not result['stdout'].strip():
                    # 空出力 = スキップ
                    tool_results['skipped'] += 1
                    tool_results['success'] += 1
                else:
                    validation = result['validation']
                    if validation['valid']:
                        tool_results['success'] += 1
                    else:
                        tool_results['failed'] += 1
                        tool_results['errors'].append(
                            f"{fixture.name}: {validation['errors']}"
                        )
            
            results_summary[tool_name] = tool_results
        
        # 失敗があればレポート
        all_errors = []
        for tool_name, results in results_summary.items():
            if results['failed'] > 0:
                all_errors.append(
                    f"{tool_name}: {results['failed']}/{results['total']} failed"
                )
                all_errors.extend(f"  - {e}" for e in results['errors'])
        
        if all_errors:
            pytest.fail(f"Tool type test failures:\n" + "\n".join(all_errors))
    
    def test_output_schema_validation_details(self, hook_runner, fixture_dir):
        """出力スキーマ検証の詳細テスト"""
        fixtures = self.get_all_fixtures(fixture_dir)
        assert len(fixtures) > 0, "No fixtures found"
        
        schema_stats = {
            'total': 0,
            'valid': 0,
            'empty': 0,
            'has_decision': 0,
            'has_permission_decision': 0,
            'decisions': {}
        }
        
        for fixture in fixtures:
            result = hook_runner.run_with_fixture(fixture)
            schema_stats['total'] += 1
            
            if not result['success']:
                continue
            
            if not result['stdout'].strip():
                schema_stats['empty'] += 1
                schema_stats['valid'] += 1
                continue
            
            validation = result['validation']
            if validation['valid']:
                schema_stats['valid'] += 1
                
                if validation['data']:
                    data = validation['data']
                    if 'decision' in data:
                        schema_stats['has_decision'] += 1
                        decision = data['decision']
                        schema_stats['decisions'][decision] = \
                            schema_stats['decisions'].get(decision, 0) + 1
                    
                    if 'permissionDecision' in data:
                        schema_stats['has_permission_decision'] += 1
        
        # 全て有効であることを確認
        assert schema_stats['valid'] == schema_stats['total'], \
            f"Some outputs are invalid: {schema_stats['valid']}/{schema_stats['total']}"


class TestHookSchemaValidatorAskDecision:
    """ask decision のテスト"""

    @pytest.fixture
    def validator(self):
        return HookSchemaValidator()

    def test_valid_ask_output(self, validator):
        """正常な ask 出力の検証（ユーザー確認要求）"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'ask',
                'permissionDecisionReason': 'ユーザー確認が必要です'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is True
        assert len(result['errors']) == 0


class TestExitCodeBehavior:
    """終了コードの挙動テスト

    Claude Code Hooks APIの終了コード仕様:
    - 終了コード0: 成功（stdoutはJSON出力として解析）
    - 終了コード2: ブロッキングエラー（stderrがClaudeへ表示）
    - その他（1等）: ノンブロッキングエラー（stderr表示後も続行）
    """

    @pytest.fixture
    def hook_runner(self):
        hook_path = PROJECT_ROOT / 'src' / 'domain' / 'hooks' / 'implementation_design_hook.py'
        return HookRunner(hook_path)

    def test_exit_code_0_success(self, hook_runner):
        """終了コード0: 正常終了

        処理対象外の入力で空出力・終了コード0を確認
        """
        input_data = {
            'session_id': '00000000-0000-0000-0000-000000000000',
            'tool_input': {
                'file_path': '/some/unrelated/file.txt'
            }
        }

        result = hook_runner.run_with_data(input_data)

        assert result['return_code'] == 0, f"Expected exit code 0, got {result['return_code']}"
        assert result['success'] is True

    def test_exit_code_0_with_valid_json(self, hook_runner):
        """終了コード0でJSON出力がある場合のスキーマ検証"""
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

        # 終了コード0の場合、出力があればJSON検証
        if result['return_code'] == 0 and result['stdout'].strip():
            assert result['validation']['valid'] is True, \
                f"Schema validation failed: {result['validation']['errors']}"

    def test_exit_code_interpretation(self):
        """終了コードの解釈テスト（仕様確認）

        終了コードの意味:
        - 0: 成功（success=True）
        - 2: ブロッキングエラー（特別扱い）
        - 1,その他: ノンブロッキングエラー
        """
        # 仕様の文書化テスト
        exit_code_meanings = {
            0: 'success',      # stdoutのJSON解析、処理続行
            2: 'blocking',     # stderrをClaudeへ、処理ブロック
            1: 'non_blocking', # stderrを表示、処理続行
        }

        assert exit_code_meanings[0] == 'success'
        assert exit_code_meanings[2] == 'blocking'
        assert exit_code_meanings[1] == 'non_blocking'


class TestAllHookEventNames:
    """全イベント名対応テスト"""

    @pytest.fixture
    def validator(self):
        return HookSchemaValidator()

    @pytest.mark.parametrize("event_name", [
        'PreToolUse',
        'PostToolUse',
        'PermissionRequest',
        'Notification',
        'Stop',
        'SubagentStop',
        'UserPromptSubmit',
        'PreCompact',
        'SessionStart',
        'SessionEnd',
    ])
    def test_valid_event_names(self, validator, event_name):
        """各イベント名が有効として認識される"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': event_name,
                'permissionDecision': 'allow'
            }
        })

        result = validator.validate(output)
        assert result['valid'] is True
        # 既知のイベント名なので警告なし
        assert not any('Unknown hookEventName' in w for w in result['warnings'])

    def test_all_event_names_in_validator(self, validator):
        """バリデータに全イベント名が含まれている"""
        expected_events = [
            'PreToolUse', 'PostToolUse', 'PermissionRequest',
            'Notification', 'Stop', 'SubagentStop',
            'UserPromptSubmit', 'PreCompact', 'SessionStart', 'SessionEnd'
        ]

        for event in expected_events:
            assert event in validator.VALID_HOOK_EVENT_NAMES, \
                f"Missing event name: {event}"


class TestPermissionModeFixtures:
    """permission_mode フィクスチャのテスト

    Claude Code Hooks API の permission_mode:
    - default: 標準モード（ユーザー確認あり）
    - plan: プランモード
    - acceptEdits: 編集自動承認
    - dontAsk: 確認なし
    - bypassPermissions: 許可バイパス
    """

    @pytest.fixture
    def fixture_dir(self):
        return PROJECT_ROOT / 'tests' / 'fixtures' / 'claude_code' / 'permission_mode'

    @pytest.fixture
    def hook_runner(self):
        hook_path = PROJECT_ROOT / 'src' / 'domain' / 'hooks' / 'implementation_design_hook.py'
        return HookRunner(hook_path)

    VALID_PERMISSION_MODES = [
        'default',
        'plan',
        'acceptEdits',
        'dontAsk',
        'bypassPermissions',
    ]

    def test_permission_mode_fixtures_exist(self, fixture_dir):
        """permission_mode フィクスチャディレクトリが存在する"""
        assert fixture_dir.exists(), f"Fixture directory not found: {fixture_dir}"

    def test_all_permission_modes_have_fixtures(self, fixture_dir):
        """全 permission_mode のフィクスチャが存在する"""
        fixtures = list(fixture_dir.glob('*.json'))
        assert len(fixtures) >= 5, \
            f"Expected at least 5 permission_mode fixtures, found {len(fixtures)}"

    @pytest.mark.parametrize("mode", VALID_PERMISSION_MODES)
    def test_permission_mode_fixture_content(self, fixture_dir, mode):
        """各 permission_mode フィクスチャの内容検証"""
        # モード名に対応するフィクスチャを検索
        fixtures = list(fixture_dir.glob('*.json'))

        # いずれかのフィクスチャに該当モードが含まれているか確認
        found = False
        for fixture in fixtures:
            with open(fixture, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('permission_mode') == mode:
                found = True
                # 基本フィールドの存在確認
                assert 'session_id' in data
                assert 'hook_event_name' in data
                break

        assert found, f"No fixture found for permission_mode: {mode}"

    def test_permission_mode_fixtures_run_successfully(self, hook_runner, fixture_dir):
        """permission_mode フィクスチャでフック実行が成功する"""
        fixtures = list(fixture_dir.glob('*.json'))

        for fixture in fixtures:
            result = hook_runner.run_with_fixture(fixture)

            # 実行成功（終了コード0）
            assert result['success'] is True, \
                f"Hook execution failed for {fixture.name}: {result['stderr']}"


class TestPermissionDecisions:
    """許可決定（permissionDecision）のテスト"""

    @pytest.fixture
    def validator(self):
        return HookSchemaValidator()

    @pytest.mark.parametrize("decision", ['allow', 'deny', 'ask'])
    def test_valid_permission_decisions(self, validator, decision):
        """各許可決定が有効として認識される"""
        output = json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': decision
            }
        })

        result = validator.validate(output)
        assert result['valid'] is True
        assert len(result['errors']) == 0

    def test_all_decisions_in_validator(self, validator):
        """バリデータに全許可決定が含まれている"""
        expected_decisions = ['allow', 'deny', 'ask']

        for decision in expected_decisions:
            assert decision in validator.VALID_PERMISSION_DECISIONS, \
                f"Missing permission decision: {decision}"


class TestSessionStartupHookReplay:
    """フィクスチャリプレイによるsession_startup_hookのE2Eテスト

    SubagentMarkerManagerで事前にマーカーを作成し、
    キャプチャ済みフィクスチャをsession_startup_hookに流して
    出力を検証する。issue_5779の名前空間マッチングE2E検証を含む。

    注意: subprocessで実行されるhookは実際のBASE_DIR（/tmp/claude-nagger-{uid}/）を
    参照するため、テストでは実ディレクトリにマーカーを作成し、テスト後にクリーンアップする。
    """

    FIXTURE_SESSION_ID = "00000000-0000-0000-0000-000000000000"

    @pytest.fixture
    def hook_runner(self):
        """session_startup_hook用のHookRunner"""
        hook_path = PROJECT_ROOT / 'src' / 'domain' / 'hooks' / 'session_startup_hook.py'
        return HookRunner(hook_path)

    @pytest.fixture
    def subagent_fixture_path(self):
        """subagentフィクスチャのパス"""
        return (
            PROJECT_ROOT / 'tests' / 'fixtures' / 'claude_code'
            / 'pre_tool_use' / 'read' / 'pre_tool_use_read_subagent_20260127.json'
        )

    @pytest.fixture
    def marker_manager(self):
        """SubagentMarkerManagerのテスト用インスタンス（実ディレクトリ使用）

        subprocessで実行されるhookと同じBASE_DIRを使用するため、
        実際の/tmp/claude-nagger-{uid}/ディレクトリにマーカーを作成する。
        テスト後に自動クリーンアップする。
        """
        from src.domain.services.subagent_marker_manager import SubagentMarkerManager

        manager = SubagentMarkerManager(self.FIXTURE_SESSION_ID)
        yield manager

        # クリーンアップ: subagentマーカーとstartupマーカーを削除
        manager.cleanup()
        # startup処理済みマーカーも削除
        startup_dir = SubagentMarkerManager.BASE_DIR / self.FIXTURE_SESSION_ID / "startup"
        if startup_dir.exists():
            import shutil
            shutil.rmtree(startup_dir, ignore_errors=True)
        # main agent用マーカーも削除（session_startup_hook由来）
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        for marker_file in temp_dir.glob(f"claude_nagger_session_startup_{self.FIXTURE_SESSION_ID}*"):
            try:
                marker_file.unlink()
            except Exception:
                pass

    def test_replay_subagent_coder_namespaced_type(
        self, hook_runner, subagent_fixture_path, marker_manager
    ):
        """名前空間付きagent_type（my-plugin:coder）のE2Eリプレイ検証

        issue_5779: 名前空間付きagent_typeが短いキー（coder）にマッチし、
        coder subagent規約のメッセージが返ることを確認する。
        """
        # マーカーを事前作成（名前空間付きagent_type）
        marker_manager.create_marker(
            agent_id="test-agent-001",
            agent_type="my-plugin:coder"
        )
        assert marker_manager.is_subagent_active(), "マーカーが作成されていない"

        # フィクスチャをsession_startup_hookに流す
        result = hook_runner.run_with_fixture(subagent_fixture_path)

        # 正常終了の確認
        assert result['success'] is True, (
            f"Hook実行失敗: return_code={result['return_code']}, "
            f"stderr={result['stderr']}"
        )
        assert result['return_code'] == 0

        # 出力がある場合はスキーマ準拠を確認
        stdout = result['stdout'].strip()
        if stdout:
            assert result['validation']['valid'] is True, (
                f"スキーマ検証失敗: {result['validation']['errors']}"
            )

            # JSON出力を解析してcoder subagent規約のメッセージを確認
            output_data = json.loads(stdout)
            # decision == "block" でブロック出力であることを確認
            if 'decision' in output_data:
                assert output_data['decision'] == 'block', (
                    f"Expected decision='block', got '{output_data['decision']}'"
                )
                # coder subagent規約の内容が含まれていることを確認
                reason = output_data.get('reason', '')
                assert 'coder subagent規約' in reason or 'coder' in reason.lower(), (
                    f"coder subagent規約のメッセージが含まれていない: {reason[:200]}"
                )

    def test_replay_subagent_disabled_type(
        self, hook_runner, subagent_fixture_path, marker_manager
    ):
        """enabled: falseのsubagent種別（Explore）はスキップされることを確認

        config.yamlでExploreはenabled: falseなので、
        hookが処理対象外として空出力またはスキップすることを検証する。
        """
        # Explore種別のマーカーを事前作成
        marker_manager.create_marker(
            agent_id="test-agent-explore",
            agent_type="Explore"
        )
        assert marker_manager.is_subagent_active(), "マーカーが作成されていない"

        # フィクスチャをsession_startup_hookに流す
        result = hook_runner.run_with_fixture(subagent_fixture_path)

        # 正常終了の確認
        assert result['success'] is True, (
            f"Hook実行失敗: return_code={result['return_code']}, "
            f"stderr={result['stderr']}"
        )
        assert result['return_code'] == 0

        # Explore（disabled）の場合は空出力またはスキーマ準拠出力
        stdout = result['stdout'].strip()
        if stdout:
            # 出力がある場合もスキーマ準拠であること
            assert result['validation']['valid'] is True, (
                f"スキーマ検証失敗: {result['validation']['errors']}"
            )
            # blockでないこと（disabledなのでブロックされない）
            try:
                output_data = json.loads(stdout)
                # Explore用のブロックメッセージが含まれていないこと
                reason = output_data.get('reason', '')
                assert 'Explore' not in reason, (
                    f"disabled種別のメッセージが出力されている: {reason[:200]}"
                )
            except json.JSONDecodeError:
                pass  # JSON以外の出力は許容

    def test_replay_subagent_conductor_role(
        self, hook_runner, subagent_fixture_path, marker_manager
    ):
        """conductor roleのsubagentがconductor固有規約を受け取ることを確認

        general-purposeのagent_typeでrole=conductorのマーカーを作成し、
        session_startup_hookがconductor subagent規約のブロックメッセージを返すことを検証する。
        """
        # conductor roleのマーカーを事前作成
        marker_manager.create_marker(
            agent_id="test-agent-conductor",
            agent_type="general-purpose"
        )
        # roleフィールドを設定
        marker_manager.update_marker("test-agent-conductor", role="conductor")

        assert marker_manager.is_subagent_active(), "マーカーが作成されていない"

        # フィクスチャをsession_startup_hookに流す
        result = hook_runner.run_with_fixture(subagent_fixture_path)

        # 正常終了の確認
        assert result['success'] is True, (
            f"Hook実行失敗: return_code={result['return_code']}, "
            f"stderr={result['stderr']}"
        )
        assert result['return_code'] == 0

        # conductor subagent規約のメッセージが返ることを確認
        stdout = result['stdout'].strip()
        if stdout:
            assert result['validation']['valid'] is True, (
                f"スキーマ検証失敗: {result['validation']['errors']}"
            )

            output_data = json.loads(stdout)
            if 'decision' in output_data:
                assert output_data['decision'] == 'block', (
                    f"Expected decision='block', got '{output_data['decision']}'"
                )
                reason = output_data.get('reason', '')
                assert 'conductor subagent規約' in reason, (
                    f"conductor subagent規約のメッセージが含まれていない: {reason[:200]}"
                )
                # conductor固有の制約が含まれていることを確認
                assert '直接作業を実行しない' in reason, (
                    f"conductor固有の制約（直接作業禁止）が含まれていない: {reason[:200]}"
                )

    def test_replay_no_subagent_marker(
        self, hook_runner, subagent_fixture_path, marker_manager
    ):
        """マーカーなし状態でのリプレイ: main agentフローが返ることを確認

        subagentマーカーが存在しない場合、session_startup_hookは
        main agentとしての通常フロー（セッション開始メッセージ）を返す。
        """
        # マーカーなし状態を確認
        assert not marker_manager.is_subagent_active(), "マーカーが存在してはいけない"

        # フィクスチャをsession_startup_hookに流す
        result = hook_runner.run_with_fixture(subagent_fixture_path)

        # 正常終了の確認
        assert result['success'] is True, (
            f"Hook実行失敗: return_code={result['return_code']}, "
            f"stderr={result['stderr']}"
        )
        assert result['return_code'] == 0

        # main agentフロー: 出力がある場合はスキーマ準拠かつmain agentメッセージ
        stdout = result['stdout'].strip()
        if stdout:
            assert result['validation']['valid'] is True, (
                f"スキーマ検証失敗: {result['validation']['errors']}"
            )

            try:
                output_data = json.loads(stdout)
                if 'decision' in output_data:
                    # main agentフローではblock（セッション開始メッセージ）
                    assert output_data['decision'] == 'block'
                    reason = output_data.get('reason', '')
                    # subagent固有のメッセージが含まれていないこと
                    assert 'subagent規約' not in reason and 'coder subagent規約' not in reason, (
                        f"subagent用メッセージがmain agentフローで出力されている: {reason[:200]}"
                    )
            except json.JSONDecodeError:
                pass  # JSON以外の出力は許容


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
