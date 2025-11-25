"""ドキュメント参照チェックサービス"""

from typing import Dict, List
from pathlib import Path
import re
from ..entities.document_entity import Document


class ReferenceChecker:
    """参照チェックサービス"""

    def __init__(self):
        self.vibes_ref_pattern = re.compile(r'@vibes/([^\s\)]+\.md)')
        self.relative_ref_pattern = re.compile(r'\[.*?\]\((?:\.\.?/[^\)]+|[^@\s][^\)]*\.md)\)')

    def check_file(self, file_path: Path) -> Dict:
        """単一ファイルの参照チェック"""
        errors = []
        warnings = []
        
        try:
            document = Document(file_path)
            if not document.exists():
                return {'errors': [f"ファイルが存在しません: {file_path}"], 'warnings': []}
            
            content = document.read()
            
            # @vibes/記法の参照チェック
            vibes_refs = self.vibes_ref_pattern.findall(content)
            for ref in vibes_refs:
                # スクリプトディレクトリから相対的にdocsディレクトリを取得
                docs_dir = Path(__file__).parent.parent.parent.parent.parent / "docs"
                ref_path = docs_dir / ref
                if not ref_path.exists():
                    errors.append(f"参照先が存在しません: @vibes/{ref}")
            
            # 相対パス参照チェック（INDEX.md以外）
            if document.name != 'INDEX.md':
                relative_refs = self.relative_ref_pattern.findall(content)
                for ref in relative_refs:
                    warnings.append(f"非推奨の相対パス参照: {ref}")
            
        except Exception as e:
            errors.append(f"ファイル読み込みエラー: {str(e)}")
        
        return {'errors': errors, 'warnings': warnings}

    def check_all(self, directory: Path) -> Dict:
        """全ファイル一括チェック"""
        results = []
        
        # tempsディレクトリは除外
        for md_file in directory.rglob("*.md"):
            relative_path = md_file.relative_to(directory)
            if not str(relative_path).startswith('temps/'):
                result = self.check_file(md_file)
                results.append({
                    'file': str(md_file),
                    'errors': result['errors'],
                    'warnings': result['warnings']
                })
        
        return {
            'success': all(not r['errors'] for r in results),
            'results': results
        }