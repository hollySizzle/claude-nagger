#!/usr/bin/env python3
"""permission_mode スマートスキップ機能テスト

issue #4475: permission_modeによるスマートスキップ
"""

import pytest
import json
import sys
from pathlib import Path

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from shared.permission_mode import (
    PermissionMode,
    PermissionModeBehavior,
    DEFAULT_MODE_BEHAVIORS,
)


class TestPermissionModeEnum:
    """PermissionMode Enumのテスト"""

    def test_all_modes_defined(self):
        """全モードが定義されている"""
        expected_modes = ['default', 'plan', 'acceptEdits', 'dontAsk', 'bypassPermissions']
        for mode_str in expected_modes:
            mode = PermissionMode.from_string(mode_str)
            assert mode != PermissionMode.UNKNOWN, f"Mode {mode_str} should be defined"

    def test_from_string_valid_modes(self):
        """文字列からの変換テスト（有効な値）"""
        assert PermissionMode.from_string('default') == PermissionMode.DEFAULT
        assert PermissionMode.from_string('plan') == PermissionMode.PLAN
        assert PermissionMode.from_string('acceptEdits') == PermissionMode.ACCEPT_EDITS
        assert PermissionMode.from_string('dontAsk') == PermissionMode.DONT_ASK
        assert PermissionMode.from_string('bypassPermissions') == PermissionMode.BYPASS_PERMISSIONS

    def test_from_string_unknown_mode(self):
        """文字列からの変換テスト（不明な値）"""
        assert PermissionMode.from_string('unknown_mode') == PermissionMode.UNKNOWN
        assert PermissionMode.from_string('') == PermissionMode.UNKNOWN
        assert PermissionMode.from_string('BYPASS') == PermissionMode.UNKNOWN


class TestPermissionModeBehaviorEnum:
    """PermissionModeBehavior Enumのテスト"""

    def test_all_behaviors_defined(self):
        """全挙動が定義されている"""
        expected_behaviors = ['normal', 'skip', 'warn_only', 'log_only']
        for behavior_str in expected_behaviors:
            behavior = PermissionModeBehavior(behavior_str)
            assert behavior is not None


class TestDefaultModeBehaviors:
    """デフォルトのモード別挙動マッピングテスト"""

    def test_bypass_permissions_skips(self):
        """bypassPermissionsはSKIP"""
        assert DEFAULT_MODE_BEHAVIORS[PermissionMode.BYPASS_PERMISSIONS] == PermissionModeBehavior.SKIP

    def test_dont_ask_warns_only(self):
        """dontAskはWARN_ONLY"""
        assert DEFAULT_MODE_BEHAVIORS[PermissionMode.DONT_ASK] == PermissionModeBehavior.WARN_ONLY

    def test_default_is_normal(self):
        """defaultはNORMAL"""
        assert DEFAULT_MODE_BEHAVIORS[PermissionMode.DEFAULT] == PermissionModeBehavior.NORMAL

    def test_plan_is_normal(self):
        """planはNORMAL"""
        assert DEFAULT_MODE_BEHAVIORS[PermissionMode.PLAN] == PermissionModeBehavior.NORMAL

    def test_accept_edits_is_normal(self):
        """acceptEditsはNORMAL"""
        assert DEFAULT_MODE_BEHAVIORS[PermissionMode.ACCEPT_EDITS] == PermissionModeBehavior.NORMAL


class TestBaseHookPermissionMode:
    """BaseHookのpermission_mode関連メソッドテスト"""

    @pytest.fixture
    def concrete_hook(self):
        """テスト用の具象Hookクラス"""
        from domain.hooks.base_hook import BaseHook

        class TestHook(BaseHook):
            def should_process(self, input_data):
                return True

            def process(self, input_data):
                return {'decision': 'approve', 'reason': 'test'}

        return TestHook()

    def test_get_permission_mode_default(self, concrete_hook):
        """permission_modeがdefaultの場合"""
        input_data = {'permission_mode': 'default'}
        mode = concrete_hook.get_permission_mode(input_data)
        assert mode == PermissionMode.DEFAULT

    def test_get_permission_mode_bypass(self, concrete_hook):
        """permission_modeがbypassPermissionsの場合"""
        input_data = {'permission_mode': 'bypassPermissions'}
        mode = concrete_hook.get_permission_mode(input_data)
        assert mode == PermissionMode.BYPASS_PERMISSIONS

    def test_get_permission_mode_dont_ask(self, concrete_hook):
        """permission_modeがdontAskの場合"""
        input_data = {'permission_mode': 'dontAsk'}
        mode = concrete_hook.get_permission_mode(input_data)
        assert mode == PermissionMode.DONT_ASK

    def test_get_permission_mode_missing(self, concrete_hook):
        """permission_modeがない場合"""
        input_data = {}
        mode = concrete_hook.get_permission_mode(input_data)
        assert mode == PermissionMode.UNKNOWN

    def test_get_behavior_bypass_is_skip(self, concrete_hook):
        """bypassPermissionsの挙動はSKIP"""
        behavior = concrete_hook.get_permission_mode_behavior(PermissionMode.BYPASS_PERMISSIONS)
        assert behavior == PermissionModeBehavior.SKIP

    def test_get_behavior_dont_ask_is_warn_only(self, concrete_hook):
        """dontAskの挙動はWARN_ONLY"""
        behavior = concrete_hook.get_permission_mode_behavior(PermissionMode.DONT_ASK)
        assert behavior == PermissionModeBehavior.WARN_ONLY

    def test_get_behavior_with_config_override(self, concrete_hook):
        """設定ファイルでの挙動オーバーライド"""
        config_behaviors = {'default': 'skip'}  # defaultをskipに変更
        behavior = concrete_hook.get_permission_mode_behavior(
            PermissionMode.DEFAULT,
            config_behaviors
        )
        assert behavior == PermissionModeBehavior.SKIP

    def test_should_skip_bypass_permissions(self, concrete_hook):
        """bypassPermissionsでスキップ判定"""
        input_data = {'permission_mode': 'bypassPermissions'}
        should_skip, behavior = concrete_hook.should_skip_by_permission_mode(input_data)
        assert should_skip is True
        assert behavior == PermissionModeBehavior.SKIP

    def test_should_not_skip_default(self, concrete_hook):
        """defaultではスキップしない"""
        input_data = {'permission_mode': 'default'}
        should_skip, behavior = concrete_hook.should_skip_by_permission_mode(input_data)
        assert should_skip is False
        assert behavior == PermissionModeBehavior.NORMAL

    def test_should_not_skip_dont_ask(self, concrete_hook):
        """dontAskではスキップしないがWARN_ONLY"""
        input_data = {'permission_mode': 'dontAsk'}
        should_skip, behavior = concrete_hook.should_skip_by_permission_mode(input_data)
        assert should_skip is False
        assert behavior == PermissionModeBehavior.WARN_ONLY


class TestPermissionModeWithFixtures:
    """フィクスチャを使用したpermission_modeテスト"""

    @pytest.fixture
    def fixture_dir(self):
        return PROJECT_ROOT / 'tests' / 'fixtures' / 'claude_code' / 'permission_mode'

    def test_bypass_permissions_fixture(self, fixture_dir):
        """bypassPermissionsフィクスチャの検証"""
        fixture_path = fixture_dir / 'pre_tool_use_bypass.json'
        with open(fixture_path, 'r') as f:
            data = json.load(f)

        assert data['permission_mode'] == 'bypassPermissions'
        mode = PermissionMode.from_string(data['permission_mode'])
        assert DEFAULT_MODE_BEHAVIORS[mode] == PermissionModeBehavior.SKIP

    def test_dont_ask_fixture(self, fixture_dir):
        """dontAskフィクスチャの検証"""
        fixture_path = fixture_dir / 'pre_tool_use_dont_ask.json'
        with open(fixture_path, 'r') as f:
            data = json.load(f)

        assert data['permission_mode'] == 'dontAsk'
        mode = PermissionMode.from_string(data['permission_mode'])
        assert DEFAULT_MODE_BEHAVIORS[mode] == PermissionModeBehavior.WARN_ONLY


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
