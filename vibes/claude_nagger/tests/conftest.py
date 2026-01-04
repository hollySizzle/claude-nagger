"""pytest設定 - テストモジュールのパス設定"""

import sys
from pathlib import Path

# プロジェクトルートをPYTHONPATHに追加（from src.xxx形式のインポート用）
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# srcディレクトリもPYTHONPATHに追加（from infrastructure.xxx形式のインポート用）
src_dir = project_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
