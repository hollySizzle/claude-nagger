"""pytest設定 - テストモジュールのパス設定"""

import subprocess
import sys
import warnings
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


def pytest_sessionstart(session):
    """Editable installの同期チェック

    claude-nagger CLIが参照するソースパスとワークスペースのソースパスが
    一致しない場合、警告を出す。不一致はCLI版とソース版で異なるコードが
    実行される原因となる(issue #5862)。

    CIで失敗させるには: pytest -W error::UserWarning
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import domain.hooks.session_startup_hook as m; print(m.__file__)"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            imported_path = Path(result.stdout.strip()).resolve()
            expected_path = (src_dir / "domain" / "hooks" / "session_startup_hook.py").resolve()
            if imported_path != expected_path:
                warnings.warn(
                    f"Editable install乖離検出: "
                    f"CLI参照={imported_path}, "
                    f"ワークスペース={expected_path}. "
                    f"'pip install -e {project_root}' で同期してください",
                    UserWarning,
                    stacklevel=1
                )
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass  # CI環境等でclaude-naggerが未インストールの場合は無視
