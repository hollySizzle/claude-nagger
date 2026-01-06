"""Discord通知機能の実装"""

import os
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiohttp

# 絶対インポートを使用（uv tool install / pip install 両環境対応）
from infrastructure.config.config_manager import ConfigManager
from shared.utils import get_session_manager


class DiscordNotifier:
    """Discord通知クラス"""
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        初期化
        
        Args:
            config_manager: ConfigManagerインスタンス（省略時は新規作成）
        """
        self.config_manager = config_manager or ConfigManager()
        self.session_manager = get_session_manager()
        self.config = self._load_config()
        # SessionManagerから取得
        self.session_id = self.session_manager.session_id
        self.agent_name = self.session_manager.agent_name
    
    def _load_config(self) -> Dict[str, str]:
        """
        設定を読み込む
        
        Returns:
            Discord設定の辞書
        """
        config = {}
        
        # config.json5から設定を読み込み
        notification_settings = self.config_manager.get_notification_settings()
        discord_settings = notification_settings.get('discord', {})
        
        # 各設定項目を環境変数展開して読み込み
        for key, value in discord_settings.items():
            if key == 'enabled':
                continue
            
            # 環境変数展開
            if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                env_var = value[2:-1]
                value = os.environ.get(env_var, '')
            
            # 設定キーを大文字に変換してconfig辞書に追加
            if key == 'thread_name':
                config_key = 'THREAD_NAME'
            elif key.upper().startswith('DISCORD_'):
                config_key = key.upper()
            else:
                config_key = f'DISCORD_{key.upper()}'
            
            # bool値は文字列に変換
            if isinstance(value, bool):
                value = str(value).lower()
            
            if value:  # 空でない値のみ設定
                config[config_key] = str(value)
        
        # デフォルト値の設定
        if 'THREAD_NAME' not in config:
            config['THREAD_NAME'] = 'general'
        
        return config
    
    async def send_message(
        self,
        message: str,
        webhook_url: Optional[str] = None,
        thread_id: Optional[str] = None,
        thread_name: Optional[str] = None,
        mention_everyone: bool = False
    ) -> Dict[str, Any]:
        """
        Discordにメッセージを送信
        
        Args:
            message: 送信するメッセージ
            webhook_url: Webhook URL（省略時は環境変数から取得）
            thread_id: スレッドID（省略時は環境変数から取得）
            thread_name: スレッド名（省略時は環境変数から取得、デフォルト: general）
            mention_everyone: @everyoneメンション
            
        Returns:
            実行結果
        """
        # 設定の取得
        webhook_url = webhook_url or self.config.get('DISCORD_WEBHOOK_URL')
        thread_id = thread_id or self.config.get('DISCORD_THREAD_ID')
        thread_name = thread_name or self.config.get('THREAD_NAME', 'general')
        
        if self.config.get('DISCORD_MENTION_EVERYONE') == 'true':
            mention_everyone = True
        
        if not webhook_url:
            return {
                'success': False,
                'error': 'Discord webhook not configured'
            }
        
        # タイムスタンプ
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # メンション文字列
        mention_prefix = '@everyone ' if mention_everyone else ''
        
        # メッセージフォーマット
        if thread_id:
            formatted_message = f"{mention_prefix}🤖 **{self.agent_name}** [{timestamp}] {message}"
        else:
            formatted_message = f"{mention_prefix}[{thread_name.strip()}] 🤖 **{self.agent_name}** [{timestamp}] {message}"
        
        # ペイロード作成
        payload = {'content': formatted_message}
        
        # メンション設定
        if mention_everyone:
            payload['allowed_mentions'] = {'parse': ['everyone']}
        
        # URLの構築（スレッドID対応）
        target_url = webhook_url
        if thread_id:
            target_url = f"{webhook_url}?thread_id={thread_id}"
        
        # 送信
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(target_url, json=payload) as response:
                    if response.status == 204 or response.status == 200:
                        return {
                            'success': True,
                            'agent_name': self.agent_name,
                            'message': message
                        }
                    else:
                        error_text = await response.text()
                        return {
                            'success': False,
                            'error': f"HTTP {response.status}: {error_text}"
                        }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_sync(
        self,
        message: str,
        webhook_url: Optional[str] = None,
        thread_id: Optional[str] = None,
        thread_name: Optional[str] = None,
        mention_everyone: bool = False
    ) -> Dict[str, Any]:
        """
        同期的にDiscordにメッセージを送信
        
        Args:
            message: 送信するメッセージ
            webhook_url: Webhook URL
            thread_id: スレッドID
            thread_name: スレッド名
            mention_everyone: @everyoneメンション
            
        Returns:
            実行結果
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.send_message(
                    message=message,
                    webhook_url=webhook_url,
                    thread_id=thread_id,
                    thread_name=thread_name,
                    mention_everyone=mention_everyone
                )
            )
        finally:
            loop.close()


def main():
    """CLIエントリーポイント"""
    # メッセージ取得（引数またはデフォルト）
    message = sys.argv[1] if len(sys.argv) > 1 else 'hello'
    
    # 通知送信
    notifier = DiscordNotifier()
    result = notifier.send_sync(message)
    
    if result['success']:
        print(f"Message sent to Discord [{result['agent_name']}]: {result['message']}", file=sys.stderr)
    else:
        print(f"Failed to send Discord message: {result['error']}", file=sys.stderr)
    
    # フックの実行を妨げないよう正常終了
    sys.exit(0)


if __name__ == '__main__':
    main()