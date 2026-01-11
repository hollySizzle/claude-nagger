"""規約マッチング処理の基底クラス"""

from abc import ABC, abstractmethod
from typing import List


class BaseConventionMatcher(ABC):
    """規約マッチング処理の基底クラス"""
    
    @abstractmethod
    def matches_pattern(self, target: str, patterns: List[str]) -> bool:
        """
        対象がパターンにマッチするか確認
        
        Args:
            target: チェック対象の文字列
            patterns: パターンリスト
            
        Returns:
            マッチする場合True
        """
        pass