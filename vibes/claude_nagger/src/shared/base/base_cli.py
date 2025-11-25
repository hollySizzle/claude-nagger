"""基本CLIクラス - 全CLIコンポーネントの基底クラス"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
import logging


class BaseCLI(ABC):
    """CLIコンポーネントの基底クラス"""

    def __init__(self):
        self.working_dir = Path.cwd()
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """ロガー設定"""
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger

    @abstractmethod
    def show_menu(self) -> str:
        """メニュー表示（サブクラスで実装）"""
        pass

    @abstractmethod
    def run_interactive(self):
        """対話的実行（サブクラスで実装）"""
        pass

    def print_success(self, message: str):
        """成功メッセージ表示"""
        print(f"✅ {message}")
        self.logger.info(message)

    def print_error(self, message: str):
        """エラーメッセージ表示"""
        print(f"❌ {message}")
        self.logger.error(message)

    def print_warning(self, message: str):
        """警告メッセージ表示"""
        print(f"⚠️  {message}")
        self.logger.warning(message)

    def print_info(self, message: str):
        """情報メッセージ表示"""
        print(f"ℹ️  {message}")
        self.logger.info(message)

    def print_progress(self, message: str):
        """進捗メッセージ表示"""
        print(f"🔄 {message}")
        self.logger.info(message)