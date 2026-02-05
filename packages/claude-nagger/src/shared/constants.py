"""共通定数"""

# suggest-rules機能で使用するファイル名
SUGGESTED_RULES_FILENAME = "suggested_rules.yaml"

# フォールバックマッチングのTTL（分）
# 古いtask_spawnエントリが誤マッチするのを防ぐ（issue_5955）
TASK_SPAWN_TTL_MINUTES = 5

# 有効なROLE値のホワイトリスト（issue_5955）
# config.yamlのsubagent_typesと同期すること
# 大文字小文字を区別する（Bashはconfig.yamlでの定義に従う）
VALID_ROLE_VALUES = frozenset([
    # 標準ロール（小文字）
    "coder",
    "tester",
    "reviewer",
    "researcher",
    "architect",
    "scribe",
    "conductor",
    "planner",
    "ops",
    "debug",
    # Claude Code標準サブエージェントタイプ（大文字開始）
    "Bash",
    "Explore",
    "Plan",
])
