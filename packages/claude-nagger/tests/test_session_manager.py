"""session_manager.py のテスト"""

import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.shared.utils.session_manager import SessionManager, get_session_manager


class TestSessionManagerInit:
    """SessionManager初期化のテスト"""

    def test_init(self):
        """初期化テスト"""
        manager = SessionManager()
        assert manager._session_id is None
        assert manager._agent_name is None
        assert manager._session_data is None


class TestSessionId:
    """session_id プロパティのテスト"""

    def test_session_id_from_session_data(self):
        """セッションデータからIDを取得"""
        manager = SessionManager()
        manager._session_data = {
            'session': {'id': 'test-session-id'}
        }

        assert manager.session_id == 'test-session-id'

    def test_session_id_fallback_to_pid(self):
        """フォールバックでプロセスIDを使用"""
        manager = SessionManager()
        manager._session_data = {}

        with patch('os.getpid', return_value=12345):
            assert manager.session_id == '12345'

    def test_session_id_cached(self):
        """セッションIDはキャッシュされる"""
        manager = SessionManager()
        manager._session_id = 'cached-id'

        assert manager.session_id == 'cached-id'


class TestAgentName:
    """agent_name プロパティのテスト"""

    def test_agent_name_generated(self):
        """エージェント名が生成される"""
        manager = SessionManager()
        manager._session_id = 'test-session-123'

        agent_name = manager.agent_name

        # フォーマット確認: "名前-短縮ID"
        assert '-' in agent_name
        # 最初のハイフン以前が名前
        first_dash = agent_name.index('-')
        name_part = agent_name[:first_dash]
        assert name_part in SessionManager.AGENT_NAMES
        # 最後の8文字がID部分
        assert 'sion-123' in agent_name

    def test_agent_name_cached(self):
        """エージェント名はキャッシュされる"""
        manager = SessionManager()
        manager._agent_name = 'cached-name'

        assert manager.agent_name == 'cached-name'

    def test_agent_name_short_session_id(self):
        """短いセッションIDの場合"""
        manager = SessionManager()
        manager._session_id = 'abc'

        agent_name = manager.agent_name

        assert 'abc' in agent_name


class TestSessionData:
    """session_data プロパティのテスト"""

    def test_session_data_from_stdin(self):
        """stdinからデータを読み込む"""
        manager = SessionManager()
        test_data = '{"tool_name": "Edit"}'

        with patch('sys.stdin.isatty', return_value=False):
            with patch('sys.stdin.read', return_value=test_data):
                data = manager.session_data

        assert data == {"tool_name": "Edit"}

    def test_session_data_tty(self):
        """TTYの場合は空の辞書"""
        manager = SessionManager()

        with patch('sys.stdin.isatty', return_value=True):
            data = manager.session_data

        assert data == {}

    def test_session_data_invalid_json(self):
        """無効なJSONは空の辞書"""
        manager = SessionManager()

        with patch('sys.stdin.isatty', return_value=False):
            with patch('sys.stdin.read', return_value='not json'):
                data = manager.session_data

        assert data == {}

    def test_session_data_io_error(self):
        """IOエラー時は空の辞書"""
        manager = SessionManager()

        with patch('sys.stdin.isatty', return_value=False):
            with patch('sys.stdin.read', side_effect=IOError('error')):
                data = manager.session_data

        assert data == {}

    def test_session_data_cached(self):
        """セッションデータはキャッシュされる"""
        manager = SessionManager()
        manager._session_data = {'cached': 'data'}

        assert manager.session_data == {'cached': 'data'}


class TestGenerateAgentName:
    """_generate_agent_name メソッドのテスト"""

    def test_deterministic(self):
        """同じIDから同じ名前が生成される"""
        manager = SessionManager()

        name1 = manager._generate_agent_name('test-session')
        name2 = manager._generate_agent_name('test-session')

        assert name1 == name2

    def test_different_ids_different_names(self):
        """異なるIDから異なる名前が生成される可能性がある"""
        manager = SessionManager()

        name1 = manager._generate_agent_name('session-1')
        name2 = manager._generate_agent_name('session-2')

        # 名前が異なる可能性を確認（ハッシュ依存）
        assert isinstance(name1, str)
        assert isinstance(name2, str)


class TestGetSessionFilePath:
    """get_session_file_path メソッドのテスト"""

    def test_creates_directory(self, tmp_path):
        """ディレクトリを作成する"""
        manager = SessionManager()
        manager._session_id = 'test-session'

        new_dir = tmp_path / 'new_dir'
        path = manager.get_session_file_path(new_dir, 'prefix')

        assert new_dir.exists()
        assert path == new_dir / 'prefix_test-session'

    def test_with_extension(self, tmp_path):
        """拡張子を付与する"""
        manager = SessionManager()
        manager._session_id = 'test-session'

        path = manager.get_session_file_path(tmp_path, 'log', '.txt')

        assert path == tmp_path / 'log_test-session.txt'

    def test_without_extension(self, tmp_path):
        """拡張子なし"""
        manager = SessionManager()
        manager._session_id = 'test-session'

        path = manager.get_session_file_path(tmp_path, 'marker')

        assert path == tmp_path / 'marker_test-session'


class TestGetToolInfo:
    """get_tool_info メソッドのテスト"""

    def test_with_session_data(self):
        """セッションデータがある場合"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/test.py'}
        }

        info = manager.get_tool_info()

        assert info['tool_name'] == 'Edit'
        assert info['tool_input'] == {'file_path': '/test.py'}

    def test_without_session_data(self):
        """セッションデータがない場合"""
        manager = SessionManager()
        manager._session_data = {}

        info = manager.get_tool_info()

        assert info['tool_name'] is None
        assert info['tool_input'] == {}


class TestIsFileModified:
    """is_file_modified メソッドのテスト"""

    def test_edit_tool_with_matching_extension(self):
        """Edit ツールで拡張子が一致"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/test.pu'}
        }

        result = manager.is_file_modified(extensions=['.pu', '.puml'])

        assert result is True

    def test_edit_tool_with_non_matching_extension(self):
        """Edit ツールで拡張子が不一致"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/test.py'}
        }

        result = manager.is_file_modified(extensions=['.pu', '.puml'])

        assert result is False

    def test_non_file_tool(self):
        """ファイル変更ツール以外"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'Read',
            'tool_input': {'file_path': '/test.pu'}
        }

        result = manager.is_file_modified(extensions=['.pu'])

        assert result is False

    def test_no_file_path(self):
        """ファイルパスがない場合"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'Edit',
            'tool_input': {}
        }

        result = manager.is_file_modified(extensions=['.pu'])

        assert result is False

    def test_no_extensions_filter(self):
        """拡張子フィルタなしの場合"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'Write',
            'tool_input': {'file_path': '/test.py'}
        }

        result = manager.is_file_modified()

        assert result is True

    def test_multi_edit_tool(self):
        """MultiEdit ツール"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'MultiEdit',
            'tool_input': {'file_path': '/test.pu'}
        }

        result = manager.is_file_modified(extensions=['.pu'])

        assert result is True

    def test_notebook_edit_tool(self):
        """NotebookEdit ツール"""
        manager = SessionManager()
        manager._session_data = {
            'tool_name': 'NotebookEdit',
            'tool_input': {'file_path': '/test.ipynb'}
        }

        result = manager.is_file_modified(extensions=['.ipynb'])

        assert result is True


class TestGetSessionManager:
    """get_session_manager 関数のテスト"""

    def test_singleton(self):
        """シングルトンインスタンスを返す"""
        # グローバル変数をリセット
        import src.shared.utils.session_manager as sm
        sm._session_manager_instance = None

        manager1 = get_session_manager()
        manager2 = get_session_manager()

        assert manager1 is manager2

    def test_creates_instance(self):
        """インスタンスを作成する"""
        import src.shared.utils.session_manager as sm
        sm._session_manager_instance = None

        manager = get_session_manager()

        assert isinstance(manager, SessionManager)
