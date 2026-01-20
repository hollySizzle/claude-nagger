"""セッション管理の共通クラス"""

import os
import sys
import json
import hashlib
import logging
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class SessionManager:
    """セッションIDとエージェント名を管理する共通クラス"""
    
    # エージェント名のリスト（discord_notify.jsと同じ）
    AGENT_NAMES = [
        "キヨマツ", "ヤギヌマ", "イタバ", "キタハシ", "イワモリ", "ロッカク",
        "シモヤマ", "ウニスガ", "タカミチ", "ミサカ", "ダンノ", "コレマツ",
        "ノナミ", "キリウ", "ユタカ", "マイグマ", "モリミツ", "サカガワ", "キマタ"
    ]
    
    def __init__(self):
        """初期化"""
        self._session_id: Optional[str] = None
        self._agent_name: Optional[str] = None
        self._session_data: Optional[Dict[str, Any]] = None
    
    @property
    def session_id(self) -> str:
        """
        セッションIDを取得
        
        優先順位:
        1. stdin からのJSON入力（Claudeフック環境）
        2. 環境変数 CLAUDE_SESSION_ID
        3. 環境変数 SESSION_ID
        4. プロセスID（フォールバック）
        
        Returns:
            セッションID
        """
        if self._session_id is None:
            self._session_id = self._get_session_id()
        return self._session_id
    
    @property
    def agent_name(self) -> str:
        """
        エージェント名を取得
        
        Returns:
            セッションIDから生成されたエージェント名
        """
        if self._agent_name is None:
            self._agent_name = self._generate_agent_name(self.session_id)
        return self._agent_name
    
    @property
    def session_data(self) -> Dict[str, Any]:
        """
        セッションデータを取得（stdin からのJSON）
        
        Returns:
            セッションデータ（利用可能な場合）、それ以外は空の辞書
        """
        if self._session_data is None:
            self._session_data = self._load_session_data()
        return self._session_data
    
    def _get_session_id(self) -> str:
        """
        セッションIDを取得する内部メソッド
        
        Returns:
            セッションID
        """
        # まず stdin からのJSONデータをチェック
        session_data = self.session_data
        if session_data and 'session' in session_data:
            session = session_data['session']
            if isinstance(session, dict) and 'id' in session:
                return session['id']
        

        
        # フォールバック: プロセスID
        return str(os.getpid())
    
    def _load_session_data(self) -> Dict[str, Any]:
        """
        stdin からJSONデータを読み込む
        
        Returns:
            JSONデータ（パース可能な場合）、それ以外は空の辞書
        """
        # stdin が TTY の場合はスキップ
        if sys.stdin.isatty():
            return {}
        
        try:
            # stdin から読み込み
            input_data = sys.stdin.read()
            if input_data:
                return json.loads(input_data)
        except (json.JSONDecodeError, IOError) as e:
            logger.debug(f"stdin JSON読み込み失敗（正常動作）: {e}")
        
        return {}
    
    def _generate_agent_name(self, session_id: str) -> str:
        """
        セッションIDからエージェント名を生成
        
        Args:
            session_id: セッションID
            
        Returns:
            エージェント名（例: "キヨマツ-abc12345"）
        """
        # MD5ハッシュを生成
        hash_obj = hashlib.md5(session_id.encode())
        hash_hex = hash_obj.hexdigest()
        
        # ハッシュ値から名前インデックスを計算
        hash_value = int(hash_hex[:8], 16)
        name_index = hash_value % len(self.AGENT_NAMES)
        
        # 短縮ID（後ろ8文字）
        short_id = session_id[-8:] if len(session_id) >= 8 else session_id
        
        return f"{self.AGENT_NAMES[name_index]}-{short_id}"
    
    def get_session_file_path(self, base_dir: Path, prefix: str = "session", extension: str = "") -> Path:
        """
        セッション固有のファイルパスを生成
        
        Args:
            base_dir: ベースディレクトリ
            prefix: ファイル名のプレフィックス
            extension: ファイル拡張子（ドットを含む）
            
        Returns:
            セッション固有のファイルパス
        """
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{prefix}_{self.session_id}"
        if extension:
            filename += extension
        
        return base_dir / filename
    
    def get_tool_info(self) -> Dict[str, Any]:
        """
        現在のツール情報を取得（フック環境で有用）
        
        Returns:
            ツール名とツール入力を含む辞書
        """
        tool_info = {
            'tool_name': None,
            'tool_input': {}
        }
        
        if self.session_data:
            tool_info['tool_name'] = self.session_data.get('tool_name')
            tool_info['tool_input'] = self.session_data.get('tool_input', {})
        
        return tool_info
    
    def is_file_modified(self, extensions: list = None) -> bool:
        """
        特定の拡張子のファイルが変更されたかチェック
        
        Args:
            extensions: チェックする拡張子のリスト（例: ['.pu', '.puml']）
            
        Returns:
            ファイルが変更された場合 True
        """
        tool_info = self.get_tool_info()
        tool_name = tool_info['tool_name']
        tool_input = tool_info['tool_input']
        
        # ファイル変更を伴うツールかチェック
        if tool_name not in ['Edit', 'MultiEdit', 'Write', 'NotebookEdit']:
            return False
        
        # ファイルパスを取得
        file_path = tool_input.get('file_path', '')
        if not file_path:
            return False
        
        # 拡張子指定がない場合は True
        if not extensions:
            return True
        
        # 拡張子をチェック
        file_path = Path(file_path)
        return file_path.suffix in extensions


# シングルトンインスタンス
_session_manager_instance: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """
    SessionManagerのシングルトンインスタンスを取得
    
    Returns:
        SessionManagerインスタンス
    """
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = SessionManager()
    return _session_manager_instance