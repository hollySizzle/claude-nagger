"""Discord通知機能のテスト"""

import os
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock, create_autospec
from src.infrastructure.notifiers.discord_notifier import DiscordNotifier
from src.infrastructure.config.config_manager import ConfigManager


class TestDiscordNotifier:
    """DiscordNotifierのテスト"""
    
    @pytest.fixture
    def mock_config_manager(self):
        """モックのConfigManager"""
        mock_cm = Mock(spec=ConfigManager)
        mock_cm.get_notification_settings.return_value = {
            'discord': {
                'enabled': True,
                'webhook_url': 'https://discord.com/api/webhooks/test/webhook',
                'thread_id': '123456789',
                'thread_name': 'test-thread',
                'mention_everyone': False
            }
        }
        return mock_cm
    
    @pytest.fixture
    def notifier(self, mock_config_manager):
        """テスト用のDiscordNotifierインスタンス"""
        return DiscordNotifier(config_manager=mock_config_manager)
    
    def test_init(self, notifier):
        """初期化のテスト"""
        assert notifier.agent_name is not None
        assert notifier.session_id is not None
        assert notifier.config is not None
    
    def test_load_config(self, notifier):
        """設定読み込みのテスト"""
        config = notifier.config
        assert config['DISCORD_WEBHOOK_URL'] == 'https://discord.com/api/webhooks/test/webhook'
        assert config['DISCORD_THREAD_ID'] == '123456789'
        assert config['THREAD_NAME'] == 'test-thread'
        assert config['DISCORD_MENTION_EVERYONE'] == 'false'
    
    def test_load_config_no_settings(self):
        """設定がない場合のテスト"""
        mock_cm = Mock(spec=ConfigManager)
        mock_cm.get_notification_settings.return_value = {}
        notifier = DiscordNotifier(config_manager=mock_cm)
        # デフォルト値が設定される
        assert notifier.config.get('THREAD_NAME') == 'general'
    
    def test_load_config_with_env_expansion(self):
        """環境変数展開のテスト"""
        with patch.dict(os.environ, {'DISCORD_WEBHOOK_URL': 'https://test.webhook'}):
            mock_cm = Mock(spec=ConfigManager)
            mock_cm.get_notification_settings.return_value = {
                'discord': {
                    'webhook_url': '${DISCORD_WEBHOOK_URL}',
                    'thread_id': '999',
                    'mention_everyone': True
                }
            }
            notifier = DiscordNotifier(config_manager=mock_cm)
            assert notifier.config['DISCORD_WEBHOOK_URL'] == 'https://test.webhook'
            assert notifier.config['DISCORD_THREAD_ID'] == '999'
            assert notifier.config['DISCORD_MENTION_EVERYONE'] == 'true'
    
    def test_get_session_id_from_session_manager(self, mock_config_manager):
        """SessionManagerからセッションID取得のテスト"""
        mock_session_manager = Mock()
        mock_session_manager.session_id = 'test-session-123'
        mock_session_manager.agent_name = 'Test-Agent'

        with patch('src.infrastructure.notifiers.discord_notifier.get_session_manager', return_value=mock_session_manager):
            notifier = DiscordNotifier(config_manager=mock_config_manager)
            assert notifier.session_id == 'test-session-123'
    
    def test_get_session_id_fallback(self, mock_config_manager):
        """セッションIDのフォールバックテスト"""
        with patch.dict(os.environ, {}, clear=True):
            notifier = DiscordNotifier(config_manager=mock_config_manager)
            assert notifier.session_id == str(os.getpid())
    
    def test_get_agent_name_from_session_manager(self, mock_config_manager):
        """SessionManagerからエージェント名取得のテスト"""
        mock_session_manager = Mock()
        mock_session_manager.session_id = 'test-session'
        mock_session_manager.agent_name = 'Mochi-1234'

        with patch('src.infrastructure.notifiers.discord_notifier.get_session_manager', return_value=mock_session_manager):
            notifier = DiscordNotifier(config_manager=mock_config_manager)
            assert notifier.agent_name == 'Mochi-1234'
    
    @pytest.mark.asyncio
    async def test_send_message_success(self, notifier):
        """メッセージ送信成功のテスト"""
        with patch('src.infrastructure.notifiers.discord_notifier.aiohttp') as mock_aiohttp:
            # Mock レスポンス
            mock_response = AsyncMock()
            mock_response.status = 204
            
            # Mock post context manager
            class MockPostContext:
                async def __aenter__(self):
                    return mock_response
                async def __aexit__(self, *args):
                    return None
            
            # Mock session
            mock_session = AsyncMock()
            mock_session.post = lambda *args, **kwargs: MockPostContext()
            
            # Mock ClientSession context manager
            class MockClientSession:
                def __init__(self, *args, **kwargs):
                    pass
                async def __aenter__(self):
                    return mock_session
                async def __aexit__(self, *args):
                    return None
            
            mock_aiohttp.ClientSession = MockClientSession
            
            result = await notifier.send_message("test message")
            
            assert result['success'] is True
            assert result['message'] == "test message"
            assert result['agent_name'] == notifier.agent_name
    
    @pytest.mark.asyncio
    async def test_send_message_with_thread(self, notifier):
        """スレッドIDを指定した送信のテスト"""
        with patch('src.infrastructure.notifiers.discord_notifier.aiohttp') as mock_aiohttp:
            mock_response = AsyncMock()
            mock_response.status = 204
            
            class MockPostContext:
                async def __aenter__(self):
                    return mock_response
                async def __aexit__(self, *args):
                    return None
            
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=MockPostContext())
            
            class MockClientSession:
                def __init__(self, *args, **kwargs):
                    pass
                async def __aenter__(self):
                    return mock_session
                async def __aexit__(self, *args):
                    return None
            
            mock_aiohttp.ClientSession = MockClientSession
            
            result = await notifier.send_message(
                "test message",
                thread_id="999888777"
            )
            
            # URLにthread_idが含まれることを確認
            call_args = mock_session.post.call_args
            assert "thread_id=999888777" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_send_message_with_mention(self, notifier):
        """@everyoneメンション付き送信のテスト"""
        with patch('src.infrastructure.notifiers.discord_notifier.aiohttp') as mock_aiohttp:
            mock_response = AsyncMock()
            mock_response.status = 204
            
            class MockPostContext:
                async def __aenter__(self):
                    return mock_response
                async def __aexit__(self, *args):
                    return None
            
            mock_session = AsyncMock()
            mock_session.post = Mock(return_value=MockPostContext())
            
            class MockClientSession:
                def __init__(self, *args, **kwargs):
                    pass
                async def __aenter__(self):
                    return mock_session
                async def __aexit__(self, *args):
                    return None
            
            mock_aiohttp.ClientSession = MockClientSession
            
            result = await notifier.send_message(
                "test message",
                mention_everyone=True
            )
            
            # ペイロードに@everyoneが含まれることを確認
            call_args = mock_session.post.call_args
            payload = call_args[1]['json']
            assert '@everyone' in payload['content']
            assert payload['allowed_mentions'] == {'parse': ['everyone']}
    
    @pytest.mark.asyncio
    async def test_send_message_no_webhook(self):
        """Webhook URLが設定されていない場合のテスト"""
        mock_cm = Mock(spec=ConfigManager)
        mock_cm.get_notification_settings.return_value = {'discord': {}}
        notifier = DiscordNotifier(config_manager=mock_cm)
        result = await notifier.send_message("test message")
        
        assert result['success'] is False
        assert 'not configured' in result['error']
    
    @pytest.mark.asyncio
    async def test_send_message_http_error(self, notifier):
        """HTTP エラーのテスト"""
        with patch('src.infrastructure.notifiers.discord_notifier.aiohttp') as mock_aiohttp:
            # Mock レスポンス
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value="Internal Server Error")
            
            # Mock post context manager
            class MockPostContext:
                async def __aenter__(self):
                    return mock_response
                async def __aexit__(self, *args):
                    return None
            
            # Mock session
            mock_session = AsyncMock()
            mock_session.post = lambda *args, **kwargs: MockPostContext()
            
            # Mock ClientSession context manager
            class MockClientSession:
                def __init__(self, *args, **kwargs):
                    pass
                async def __aenter__(self):
                    return mock_session
                async def __aexit__(self, *args):
                    return None
            
            mock_aiohttp.ClientSession = MockClientSession
            
            result = await notifier.send_message("test message")
            
            assert result['success'] is False
            assert "HTTP 500" in result['error']
    
    @pytest.mark.asyncio
    async def test_send_message_exception(self, notifier):
        """例外発生時のテスト"""
        with patch('src.infrastructure.notifiers.discord_notifier.aiohttp') as mock_aiohttp:
            mock_aiohttp.ClientSession.side_effect = Exception("Connection error")
            
            result = await notifier.send_message("test message")
            
            assert result['success'] is False
            assert "Connection error" in result['error']
    
    def test_send_sync(self, notifier):
        """同期送信のテスト"""
        # AsyncMockを使う
        with patch.object(notifier, 'send_message', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {
                'success': True,
                'message': 'test',
                'agent_name': 'test-agent'
            }
            
            # 同期実行
            result = notifier.send_sync("test message")
            
            assert result['success'] is True
            assert result['message'] == 'test'
            assert result['agent_name'] == 'test-agent'
    
    def test_main_success(self, mock_config_manager, capsys):
        """CLIメイン関数の成功テスト"""
        with patch('sys.argv', ['discord_notifier.py', 'Test notification']):
            with patch.object(DiscordNotifier, 'send_sync') as mock_send:
                mock_send.return_value = {
                    'success': True,
                    'message': 'Test notification',
                    'agent_name': 'test-agent'
                }
                
                with pytest.raises(SystemExit) as excinfo:
                    from src.infrastructure.notifiers.discord_notifier import main
                    main()
                
                assert excinfo.value.code == 0
                captured = capsys.readouterr()
                assert "Message sent to Discord" in captured.err
    
    def test_main_failure(self, mock_config_manager, capsys):
        """CLIメイン関数の失敗テスト"""
        with patch('sys.argv', ['discord_notifier.py', 'Test notification']):
            with patch.object(DiscordNotifier, 'send_sync') as mock_send:
                mock_send.return_value = {
                    'success': False,
                    'error': 'Connection failed'
                }
                
                with pytest.raises(SystemExit) as excinfo:
                    from src.infrastructure.notifiers.discord_notifier import main
                    main()
                
                assert excinfo.value.code == 0
                captured = capsys.readouterr()
                assert "Failed to send Discord message" in captured.err