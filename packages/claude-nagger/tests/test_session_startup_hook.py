"""session_startup_hook.py のテスト"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from src.domain.hooks.session_startup_hook import SessionStartupHook, main


class TestSessionStartupHookInit:
    """SessionStartupHook初期化のテスト"""

    def test_init_calls_super(self):
        """初期化時にsuperが呼ばれる"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()
            assert hook.debug is True

    def test_init_loads_config(self):
        """初期化時に設定が読み込まれる"""
        with patch.object(SessionStartupHook, '_load_config', return_value={'enabled': True}) as mock_load:
            hook = SessionStartupHook()
            mock_load.assert_called_once()
            assert hook.config == {'enabled': True}

    # NOTE: session_marker_prefix はMarkerPatternsクラスへ移行したため、
    # 関連テストは削除。パターンのテストはtest_base_hook.py::TestMarkerPatternsを参照。


class TestLoadConfig:
    """_load_config メソッドのテスト"""

    def test_load_nonexistent_config(self):
        """存在しない設定ファイルは空辞書を返す"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

        # 実際の_load_configを呼び出すテスト
        with patch('pathlib.Path.exists', return_value=False):
            result = hook._load_config()

        assert result == {}

    def test_load_config_exception(self):
        """設定読み込みエラー時は空辞書を返す"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', side_effect=Exception('read error')):
                result = hook._load_config()

        assert result == {}

    def test_load_project_config_priority(self, tmp_path):
        """プロジェクト設定(.claude-nagger/config.yaml)が優先される"""
        # プロジェクト設定ディレクトリを作成
        project_config_dir = tmp_path / ".claude-nagger"
        project_config_dir.mkdir()
        project_config = project_config_dir / "config.yaml"
        project_config.write_text("""
session_startup:
  enabled: true
  message: "project config message"
""")
        
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()
        
        # カレントディレクトリをtmp_pathに変更してテスト
        with patch('pathlib.Path.cwd', return_value=tmp_path):
            result = hook._load_config()
        
        assert result.get('enabled') is True
        assert result.get('message') == "project config message"

    def test_fallback_to_default_config(self, tmp_path):
        """プロジェクト設定がない場合はデフォルト設定を使用"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()
        
        # プロジェクト設定が存在しないディレクトリ
        with patch('pathlib.Path.cwd', return_value=tmp_path):
            # デフォルト設定ファイルが存在する場合
            default_config = Path(__file__).parent.parent / "rules" / "session_startup_settings.yaml"
            if default_config.exists():
                result = hook._load_config()
                # デフォルト設定が読み込まれることを確認
                assert isinstance(result, dict)


class TestGetSessionStartupMarkerPath:
    """get_session_startup_marker_path メソッドのテスト"""

    def test_marker_path_format(self):
        """マーカーパスのフォーマットが正しい"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()
            path = hook.get_session_startup_marker_path('test-session-123')

        assert path == Path('/tmp/claude_session_startup_test-session-123')

    # NOTE: カスタムプレフィックス機能はMarkerPatternsクラスへ移行したため削除。
    # パターンはMarkerPatterns.SESSION_STARTUPで一元管理。


class TestIsSessionStartupProcessed:
    """is_session_startup_processed メソッドのテスト"""

    def test_no_session_id_returns_false(self):
        """セッションIDがない場合はFalse"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()
            result = hook.is_session_startup_processed('')

        assert result is False

    def test_marker_not_exists_returns_false(self):
        """マーカーがない場合はFalse"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            with patch.object(Path, 'exists', return_value=False):
                result = hook.is_session_startup_processed('test-session')

        assert result is False

    def test_marker_exists_returns_true(self):
        """マーカーが存在する場合はTrue（閾値チェックなし）"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            with patch.object(Path, 'exists', return_value=True):
                result = hook.is_session_startup_processed('test-session', {})

        assert result is True

    def test_token_threshold_exceeded(self, tmp_path):
        """トークン閾値超過時はFalse"""
        config = {'behavior': {'token_threshold': 1000}}
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()

            marker_path = tmp_path / 'marker'
            marker_path.write_text(json.dumps({'tokens': 500}))

            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                with patch.object(hook.__class__.__bases__[0], '_get_current_context_size', return_value=2000):
                    with patch.object(hook.__class__.__bases__[0], '_rename_expired_marker'):
                        result = hook.is_session_startup_processed(
                            'test-session',
                            {'transcript_path': '/tmp/transcript'}
                        )

            assert result is False

    def test_token_within_threshold(self, tmp_path):
        """トークン閾値内はTrue"""
        config = {'behavior': {'token_threshold': 10000}}
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()

            marker_path = tmp_path / 'marker'
            marker_path.write_text(json.dumps({'tokens': 500}))

            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                with patch.object(hook.__class__.__bases__[0], '_get_current_context_size', return_value=1000):
                    result = hook.is_session_startup_processed(
                        'test-session',
                        {'transcript_path': '/tmp/transcript'}
                    )

            assert result is True


class TestMarkSessionStartupProcessed:
    """mark_session_startup_processed メソッドのテスト"""

    def test_creates_marker_file(self, tmp_path):
        """マーカーファイルを作成する"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            marker_path = tmp_path / 'marker'
            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                result = hook.mark_session_startup_processed('test-session')

        assert result is True
        assert marker_path.exists()

    def test_marker_contains_session_info(self, tmp_path):
        """マーカーにセッション情報が含まれる"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            marker_path = tmp_path / 'marker'
            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                hook.mark_session_startup_processed('test-session-123')

        data = json.loads(marker_path.read_text())
        assert data['session_id'] == 'test-session-123'
        assert data['hook_type'] == 'session_startup'
        assert 'timestamp' in data
        assert 'tokens' in data

    def test_marker_includes_token_count(self, tmp_path):
        """マーカーにトークン数が含まれる"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            marker_path = tmp_path / 'marker'
            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                with patch.object(hook.__class__.__bases__[0], '_get_current_context_size', return_value=5000):
                    hook.mark_session_startup_processed(
                        'test-session',
                        {'transcript_path': '/tmp/transcript'}
                    )

        data = json.loads(marker_path.read_text())
        assert data['tokens'] == 5000

    def test_mark_failure_returns_false(self):
        """マーク失敗時はFalse"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            with patch.object(hook, 'get_session_startup_marker_path', side_effect=Exception('error')):
                result = hook.mark_session_startup_processed('test-session')

        assert result is False


class TestShouldProcess:
    """should_process メソッドのテスト"""

    def test_disabled_returns_false(self):
        """無効化されている場合はFalse"""
        config = {'enabled': False}
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()
            result = hook.should_process({'session_id': 'test'})

        assert result is False

    def test_no_session_id_returns_false(self):
        """セッションIDがない場合はFalse"""
        with patch.object(SessionStartupHook, '_load_config', return_value={'enabled': True}):
            hook = SessionStartupHook()
            result = hook.should_process({})

        assert result is False

    def test_already_processed_returns_false(self):
        """処理済みの場合はFalse"""
        config = {'enabled': True, 'behavior': {'once_per_session': True}}
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()

            with patch.object(hook, 'is_session_startup_processed', return_value=True):
                result = hook.should_process({'session_id': 'test'})

        assert result is False

    def test_new_session_returns_true(self):
        """新規セッションはTrue"""
        config = {'enabled': True, 'behavior': {'once_per_session': True}}
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()

            with patch.object(hook, 'is_session_startup_processed', return_value=False):
                result = hook.should_process({'session_id': 'new-session'})

        assert result is True

    def test_once_per_session_disabled(self):
        """once_per_session無効時は常にTrue"""
        config = {'enabled': True, 'behavior': {'once_per_session': False}}
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()
            result = hook.should_process({'session_id': 'test'})

        assert result is True


class TestProcess:
    """process メソッドのテスト"""

    def test_returns_block_decision(self):
        """blockの決定を返す"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            with patch.object(hook, 'mark_session_startup_processed', return_value=True):
                with patch.object(hook, '_build_message', return_value='Test message'):
                    result = hook.process({'session_id': 'test'})

        assert result['decision'] == 'block'
        assert result['reason'] == 'Test message'

    def test_marks_session_processed(self):
        """処理済みとしてマークする"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            with patch.object(hook, 'mark_session_startup_processed', return_value=True) as mock_mark:
                with patch.object(hook, '_build_message', return_value=''):
                    hook.process({'session_id': 'test'})

            mock_mark.assert_called_once()


class TestGetExecutionCount:
    """_get_execution_count メソッドのテスト"""

    def test_first_execution(self, tmp_path):
        """初回実行時は1"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            marker_path = tmp_path / 'marker'
            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                count = hook._get_execution_count('test')

        assert count == 1

    def test_second_execution(self, tmp_path):
        """マーカー存在時は2回目以降"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            # マーカーファイルを作成
            marker_path = tmp_path / 'claude_session_startup_test'
            marker_path.touch()

            with patch.object(hook, 'get_session_startup_marker_path', return_value=marker_path):
                count = hook._get_execution_count('test')

        assert count == 2


class TestBuildMessage:
    """_build_message メソッドのテスト"""

    def test_first_time_message(self):
        """初回メッセージの構築"""
        config = {
            'messages': {
                'first_time': {
                    'title': '初回タイトル',
                    'main_text': '初回本文'
                }
            }
        }
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()

            with patch.object(hook, '_get_execution_count', return_value=1):
                message = hook._build_message('test')

        assert '初回タイトル' in message
        assert '初回本文' in message

    def test_repeated_message(self):
        """2回目以降のメッセージの構築"""
        config = {
            'messages': {
                'repeated': {
                    'title': 'リピートタイトル',
                    'main_text': 'リピート本文'
                }
            }
        }
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            hook = SessionStartupHook()

            with patch.object(hook, '_get_execution_count', return_value=2):
                message = hook._build_message('test')

        assert 'リピートタイトル' in message
        assert 'リピート本文' in message

    def test_default_message(self):
        """設定がない場合のデフォルトメッセージ"""
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            hook = SessionStartupHook()

            with patch.object(hook, '_get_execution_count', return_value=1):
                message = hook._build_message('test')

        assert 'セッション開始時の確認' in message


class TestMain:
    """main関数のテスト"""

    def test_main_runs_hook(self):
        """mainがフックを実行する"""
        mock_hook = MagicMock()
        mock_hook.run.return_value = 0

        with patch.object(SessionStartupHook, '__init__', lambda self, **kwargs: None):
            with patch.object(SessionStartupHook, 'run', return_value=0):
                with patch('sys.exit') as mock_exit:
                    with patch('logging.basicConfig'):
                        main()

                mock_exit.assert_called_once_with(0)
