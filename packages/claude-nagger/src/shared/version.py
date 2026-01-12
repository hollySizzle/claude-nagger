"""バージョン情報

pyproject.tomlから動的に取得（単一ソース）
"""

try:
    from importlib.metadata import version
    __version__ = version("claude-nagger")
except Exception:
    __version__ = "dev"  # 未インストール時のフォールバック
