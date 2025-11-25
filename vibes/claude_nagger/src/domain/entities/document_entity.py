"""ドキュメントエンティティ"""

from pathlib import Path
from typing import Optional, List


class Document:
    """ドキュメントエンティティクラス"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._content: Optional[str] = None

    def read(self) -> str:
        """ファイル内容読み込み"""
        if self._content is None:
            self._content = self.path.read_text(encoding='utf-8')
        return self._content

    def write(self, content: str) -> None:
        """ファイル内容書き込み"""
        self.path.write_text(content, encoding='utf-8')
        self._content = content

    def exists(self) -> bool:
        """ファイル存在確認"""
        return self.path.exists()

    def is_markdown(self) -> bool:
        """Markdownファイルかチェック"""
        return self.path.suffix == '.md'

    def is_plantuml(self) -> bool:
        """PlantUMLファイルかチェック"""
        return self.path.suffix == '.pu'

    def get_lines(self) -> List[str]:
        """行のリストとして取得"""
        return self.read().split('\n')

    def get_relative_path(self, base: Path) -> Path:
        """相対パス取得"""
        return self.path.relative_to(base)

    @property
    def name(self) -> str:
        """ファイル名取得"""
        return self.path.name

    @property
    def stem(self) -> str:
        """拡張子なしファイル名取得"""
        return self.path.stem

    @property
    def parent(self) -> Path:
        """親ディレクトリ取得"""
        return self.path.parent