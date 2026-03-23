"""バージョン情報

pyproject.tomlから動的に取得（単一ソース）
"""

try:
    from importlib.metadata import version
    __version__ = version("claude-nagger")
except Exception:
    __version__ = "0.4.0"  # 未インストール時のフォールバック
