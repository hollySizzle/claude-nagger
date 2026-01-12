"""pytest設定 - テストモジュールのパス設定"""

import sys
from pathlib import Path

# プロジェクトルートとsrcディレクトリのパス
project_root = Path(__file__).parent.parent
src_dir = project_root / "src"

# 古いeditable installなど不正なパスを除去
# （/tmp/claude_nagger等、別ディレクトリのsrcが混入する問題への対策）
sys.path = [p for p in sys.path if "claude_nagger" not in p or str(project_root) in p]

# 正しいパスを先頭に追加（既存の場合は一度削除してから先頭へ）
for path in [str(src_dir), str(project_root)]:
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
