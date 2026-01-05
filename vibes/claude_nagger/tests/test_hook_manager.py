"""hook_manager.py のテスト"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.services.hook_manager import HookManager


class TestHookManagerInit:
    """HookManager初期化のテスト"""

    def test_init_default_claude_dir(self):
        """デフォルトでカレントディレクトリの.claudeを使用"""
        manager = HookManager()
        assert manager.claude_dir == Path.cwd() / ".claude"

    def test_init_custom_claude_dir(self, tmp_path):
        """カスタムディレクトリを指定可能"""
        manager = HookManager(claude_dir=tmp_path)
        assert manager.claude_dir == tmp_path

    def test_init_sets_settings_files(self, tmp_path):
        """設定ファイルパスが正しく設定される"""
        manager = HookManager(claude_dir=tmp_path)
        assert manager.settings_file == tmp_path / "settings.json"
        assert manager.settings_local_file == tmp_path / "settings.local.json"


class TestLoadSettings:
    """load_settings メソッドのテスト"""

    def test_load_nonexistent_file(self, tmp_path):
        """存在しないファイルは空の設定を返す"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.load_settings()
        assert result == {"hooks": {}}

    def test_load_existing_file(self, tmp_path):
        """存在するファイルを読み込む"""
        settings = {"hooks": {"PreToolUse": []}}
        (tmp_path / "settings.json").write_text(json.dumps(settings))

        manager = HookManager(claude_dir=tmp_path)
        result = manager.load_settings()

        assert result == settings

    def test_load_invalid_json(self, tmp_path):
        """無効なJSONは空の設定を返す"""
        (tmp_path / "settings.json").write_text("invalid json")

        manager = HookManager(claude_dir=tmp_path)
        result = manager.load_settings()

        assert result == {"hooks": {}}

    def test_load_local_file(self, tmp_path):
        """local=Trueでローカル設定を読み込む"""
        settings = {"hooks": {"PreToolUse": [{"matcher": "Edit"}]}}
        (tmp_path / "settings.local.json").write_text(json.dumps(settings))

        manager = HookManager(claude_dir=tmp_path)
        result = manager.load_settings(local=True)

        assert result == settings


class TestSaveSettings:
    """save_settings メソッドのテスト"""

    def test_save_creates_directory(self, tmp_path):
        """ディレクトリがなければ作成する"""
        claude_dir = tmp_path / "new_dir"
        manager = HookManager(claude_dir=claude_dir)

        result = manager.save_settings({"hooks": {}})

        assert result['success'] is True
        assert claude_dir.exists()

    def test_save_creates_file(self, tmp_path):
        """設定ファイルを作成する"""
        manager = HookManager(claude_dir=tmp_path)
        settings = {"hooks": {"PreToolUse": []}}

        result = manager.save_settings(settings)

        assert result['success'] is True
        assert (tmp_path / "settings.json").exists()
        saved = json.loads((tmp_path / "settings.json").read_text())
        assert saved == settings

    def test_save_local_file(self, tmp_path):
        """local=Trueでローカル設定に保存"""
        manager = HookManager(claude_dir=tmp_path)
        settings = {"hooks": {"PreToolUse": []}}

        result = manager.save_settings(settings, local=True)

        assert result['success'] is True
        assert (tmp_path / "settings.local.json").exists()

    def test_save_exception(self, tmp_path):
        """保存エラー時は失敗を返す"""
        manager = HookManager(claude_dir=tmp_path)

        with patch('builtins.open', side_effect=Exception('write error')):
            with patch.object(Path, 'mkdir'):
                result = manager.save_settings({})

        assert result['success'] is False
        assert 'error' in result


class TestAddHook:
    """add_hook メソッドのテスト"""

    def test_invalid_event(self, tmp_path):
        """無効なイベントはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.add_hook("InvalidEvent", "Edit", "echo test")

        assert result['success'] is False
        assert "無効なイベント" in result['error']

    def test_add_new_hook(self, tmp_path):
        """新規フックを追加"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.add_hook("PreToolUse", "Edit", "echo test")

        assert result['success'] is True
        assert "追加しました" in result['message']

        # 保存された内容を確認
        saved = json.loads((tmp_path / "settings.json").read_text())
        assert "PreToolUse" in saved['hooks']

    def test_add_hook_with_timeout(self, tmp_path):
        """タイムアウト付きでフックを追加"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.add_hook("PreToolUse", "Edit", "echo test", timeout=30)

        assert result['success'] is True

        saved = json.loads((tmp_path / "settings.json").read_text())
        hook = saved['hooks']['PreToolUse'][0]['hooks'][0]
        assert hook['timeout'] == 30

    def test_add_duplicate_hook(self, tmp_path):
        """重複するフックはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test")
        result = manager.add_hook("PreToolUse", "Edit", "echo test")

        assert result['success'] is False
        assert "既に登録" in result['error']

    def test_add_hook_to_existing_matcher(self, tmp_path):
        """既存のマッチャーに追加"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo first")
        result = manager.add_hook("PreToolUse", "Edit", "echo second")

        assert result['success'] is True

        saved = json.loads((tmp_path / "settings.json").read_text())
        hooks = saved['hooks']['PreToolUse'][0]['hooks']
        assert len(hooks) == 2

    def test_add_hook_local(self, tmp_path):
        """ローカル設定にフックを追加"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.add_hook("PreToolUse", "Edit", "echo test", local=True)

        assert result['success'] is True
        assert (tmp_path / "settings.local.json").exists()


class TestRemoveHook:
    """remove_hook メソッドのテスト"""

    def test_invalid_event(self, tmp_path):
        """無効なイベントはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.remove_hook("InvalidEvent", "Edit", "test")

        assert result['success'] is False

    def test_remove_nonexistent_event(self, tmp_path):
        """存在しないイベントはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.remove_hook("PreToolUse", "Edit", "test")

        assert result['success'] is False
        assert "存在しません" in result['error']

    def test_remove_hook(self, tmp_path):
        """フックを削除"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test")
        result = manager.remove_hook("PreToolUse", "Edit", "echo test")

        assert result['success'] is True
        assert "削除しました" in result['message']

    def test_remove_hook_partial_match(self, tmp_path):
        """部分一致で削除"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test command")
        result = manager.remove_hook("PreToolUse", "Edit", "test")

        assert result['success'] is True

    def test_remove_nonexistent_hook(self, tmp_path):
        """存在しないフックはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test")
        result = manager.remove_hook("PreToolUse", "Edit", "nonexistent")

        assert result['success'] is False
        assert "見つかりませんでした" in result['error']

    def test_remove_clears_empty_matcher(self, tmp_path):
        """空になったマッチャーエントリを削除"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test")
        manager.remove_hook("PreToolUse", "Edit", "test")

        saved = json.loads((tmp_path / "settings.json").read_text())
        assert len(saved['hooks']['PreToolUse']) == 0


class TestListHooks:
    """list_hooks メソッドのテスト"""

    def test_list_empty(self, tmp_path):
        """フックがない場合は空"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.list_hooks()

        assert result == {'hooks': {}}

    def test_list_all(self, tmp_path):
        """全フックを一覧"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test")

        result = manager.list_hooks()

        assert "PreToolUse" in result['hooks']

    def test_list_specific_event(self, tmp_path):
        """特定のイベントのフックを一覧"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo pre")
        manager.add_hook("PostToolUse", "Edit", "echo post")

        result = manager.list_hooks(event="PreToolUse")

        assert "PreToolUse" in result['hooks']
        assert "PostToolUse" not in result['hooks']

    def test_list_invalid_event(self, tmp_path):
        """無効なイベントはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.list_hooks(event="InvalidEvent")

        assert result['success'] is False


class TestClearHooks:
    """clear_hooks メソッドのテスト"""

    def test_clear_all(self, tmp_path):
        """全フックをクリア"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo test")
        result = manager.clear_hooks()

        assert result['success'] is True
        assert "全て" in result['message']

    def test_clear_specific_event(self, tmp_path):
        """特定のイベントをクリア"""
        manager = HookManager(claude_dir=tmp_path)
        manager.add_hook("PreToolUse", "Edit", "echo pre")
        manager.add_hook("PostToolUse", "Edit", "echo post")

        result = manager.clear_hooks(event="PreToolUse")

        assert result['success'] is True

        saved = json.loads((tmp_path / "settings.json").read_text())
        assert saved['hooks']['PreToolUse'] == []
        assert len(saved['hooks']['PostToolUse']) == 1

    def test_clear_invalid_event(self, tmp_path):
        """無効なイベントはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.clear_hooks(event="InvalidEvent")

        assert result['success'] is False

    def test_clear_nonexistent_event(self, tmp_path):
        """存在しないイベントはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.clear_hooks(event="PreToolUse")

        assert result['success'] is False


class TestImportHooks:
    """import_hooks メソッドのテスト"""

    def test_import_nonexistent_file(self, tmp_path):
        """存在しないファイルはエラー"""
        manager = HookManager(claude_dir=tmp_path)
        result = manager.import_hooks(tmp_path / "nonexistent.json")

        assert result['success'] is False
        assert "存在しません" in result['error']

    def test_import_invalid_json(self, tmp_path):
        """無効なJSONはエラー"""
        source = tmp_path / "source.json"
        source.write_text("invalid json")

        manager = HookManager(claude_dir=tmp_path)
        result = manager.import_hooks(source)

        assert result['success'] is False
        assert "JSON" in result['error']

    def test_import_no_hooks(self, tmp_path):
        """フックがないファイルはエラー"""
        source = tmp_path / "source.json"
        source.write_text(json.dumps({"other": "data"}))

        manager = HookManager(claude_dir=tmp_path)
        result = manager.import_hooks(source)

        assert result['success'] is False
        assert "含まれていません" in result['error']

    def test_import_hooks(self, tmp_path):
        """フックをインポート"""
        source = tmp_path / "source.json"
        source_data = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo test"}]}
                ]
            }
        }
        source.write_text(json.dumps(source_data))

        claude_dir = tmp_path / "claude"
        manager = HookManager(claude_dir=claude_dir)
        result = manager.import_hooks(source)

        assert result['success'] is True
        assert "インポートしました" in result['message']

    def test_import_merges_existing(self, tmp_path):
        """既存のフックにマージ"""
        source = tmp_path / "source.json"
        source_data = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo new"}]}
                ]
            }
        }
        source.write_text(json.dumps(source_data))

        claude_dir = tmp_path / "claude"
        manager = HookManager(claude_dir=claude_dir)
        manager.add_hook("PreToolUse", "Edit", "echo existing")

        result = manager.import_hooks(source)

        assert result['success'] is True

        saved = json.loads((claude_dir / "settings.json").read_text())
        hooks = saved['hooks']['PreToolUse'][0]['hooks']
        assert len(hooks) == 2

    def test_import_skips_duplicates(self, tmp_path):
        """重複はスキップ"""
        source = tmp_path / "source.json"
        source_data = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo same"}]}
                ]
            }
        }
        source.write_text(json.dumps(source_data))

        claude_dir = tmp_path / "claude"
        manager = HookManager(claude_dir=claude_dir)
        manager.add_hook("PreToolUse", "Edit", "echo same")

        result = manager.import_hooks(source)

        assert result['success'] is True
        assert "0個" in result['message']

    def test_import_skips_invalid_events(self, tmp_path):
        """無効なイベントはスキップ"""
        source = tmp_path / "source.json"
        source_data = {
            "hooks": {
                "InvalidEvent": [
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo test"}]}
                ]
            }
        }
        source.write_text(json.dumps(source_data))

        claude_dir = tmp_path / "claude"
        manager = HookManager(claude_dir=claude_dir)
        result = manager.import_hooks(source)

        assert result['success'] is True
        assert "0個" in result['message']
