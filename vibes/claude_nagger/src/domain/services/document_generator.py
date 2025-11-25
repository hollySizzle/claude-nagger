"""ドキュメント生成サービス"""

from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

import re


class DocumentGenerator:
    """ドキュメント生成サービス"""

    CATEGORIES = {
        'rules': '規約類',
        'specs': '技術仕様書',
        'tasks': '定型タスク手順書',
        'logics': 'ビジネスロジック',
        'apis': '外部連携仕様書',
        'temps': '一時ドキュメント'
    }

    def __init__(self, config_manager=None):
        if config_manager:
            self.config = config_manager
            self.doc_root = self.config.get_doc_root()
        else:
            # 後方互換性のためのフォールバック
            from ...infrastructure.config.config_manager import ConfigManager
            self.config = ConfigManager()
            self.doc_root = self.config.get_doc_root()

    def generate(self, category: str, filename: str, title: str = None) -> Dict:
        """新規ドキュメント生成"""
        try:
            if category not in self.CATEGORIES:
                return {'success': False, 'error': f"無効なカテゴリ: {category}"}
            
            # tempsカテゴリの場合はタイムスタンプ付与
            if category == 'temps':
                timestamp = datetime.now().strftime('%m%d%H%M_')
                filename = timestamp + filename
            
            file_path = self.doc_root / category / f"{filename}.md"
            
            if file_path.exists():
                return {'success': False, 'error': f"ファイルが既に存在します: {file_path}"}
            
            # テンプレート読み込み
            template_path = self.doc_root / category / "_template.md"
            if not template_path.exists():
                return {'success': False, 'error': f"テンプレートが存在しません: {template_path}"}
            
            content = template_path.read_text(encoding='utf-8')
            
            # タイトル置換
            if title:
                content = re.sub(r'\[TODO: [^\]]+\]', title, content)
            
            # tempsの場合は日付も置換
            if category == 'temps':
                tokyo_tz = pytz.timezone('Asia/Tokyo')
                timestamp = datetime.now(tokyo_tz).strftime('%Y-%m-%d')
                content = content.replace('${timestamp}', timestamp)
            
            # ファイル作成
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
            
            return {'success': True, 'file_path': str(file_path)}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}