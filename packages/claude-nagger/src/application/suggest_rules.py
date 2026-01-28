"""suggest-rules CLIコマンド（規約候補YAMLをstdoutに出力）"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from domain.services.rule_suggester import RuleSuggester, PatternSuggestion


class SuggestRulesCommand:
    """規約候補をYAML形式でstdoutに出力するCLIコマンド"""

    def __init__(
        self,
        min_count: int = 3,
        rule_type: Optional[str] = None,
        top: int = 10,
        session_id: Optional[str] = None,
    ):
        """
        初期化

        Args:
            min_count: 最低出現回数フィルタ
            rule_type: 規約種別フィルタ（"file" or "command"、Noneで両方）
            top: 上位N件
            session_id: 特定セッションIDのみ分析
        """
        self.min_count = min_count
        self.rule_type = rule_type
        self.top = top
        self.session_id = session_id

    def execute(self) -> int:
        """コマンド実行"""
        suggester = RuleSuggester(session_id=self.session_id)
        result = suggester.analyze()

        stats = result["stats"]
        file_suggestions = result["file_suggestions"]
        command_suggestions = result["command_suggestions"]

        # type フィルタ
        if self.rule_type == "file":
            command_suggestions = []
        elif self.rule_type == "command":
            file_suggestions = []

        # min-count フィルタ
        file_suggestions = [s for s in file_suggestions if s.count >= self.min_count]
        command_suggestions = [s for s in command_suggestions if s.count >= self.min_count]

        # top-N 制限
        file_suggestions = file_suggestions[:self.top]
        command_suggestions = command_suggestions[:self.top]

        # 0件チェック
        if not file_suggestions and not command_suggestions:
            print("規約候補は見つかりませんでした。", file=sys.stderr)
            if stats["total_inputs"] == 0:
                print("分析対象のhook入力JSONがありません。", file=sys.stderr)
            else:
                print(
                    f"分析対象: {stats['total_inputs']}件のhook入力JSON "
                    f"(min-count={self.min_count})",
                    file=sys.stderr,
                )
            return 0

        # YAML出力
        output = self._format_yaml(file_suggestions, command_suggestions, stats)
        print(output)
        return 0

    def _format_yaml(
        self,
        file_suggestions: list[PatternSuggestion],
        command_suggestions: list[PatternSuggestion],
        stats: dict,
    ) -> str:
        """分析結果をYAML形式にフォーマット"""
        rules = []
        for s in file_suggestions:
            rules.append(self._suggestion_to_rule(s))
        for s in command_suggestions:
            rules.append(self._suggestion_to_rule(s))

        data = {"rules": rules}
        yaml_body = yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # ヘッダコメント
        today = datetime.now().strftime("%Y-%m-%d")
        header = (
            f"# suggest-rules 出力\n"
            f"# 生成日: {today}\n"
            f"# 分析対象: {stats['total_inputs']}件のhook入力JSON\n"
            f"\n"
        )
        return header + yaml_body

    @staticmethod
    def _suggestion_to_rule(suggestion: PatternSuggestion) -> dict:
        """PatternSuggestionをYAMLルール辞書に変換"""
        if suggestion.category == "file":
            return {
                "name": f"{suggestion.pattern} 編集規約",
                "patterns": [suggestion.pattern],
                "severity": "warn",
                "message": (
                    f"# {suggestion.count}回の編集を検出。メッセージを書き換えてください\n"
                    "このファイルを変更する場合は規約を確認してください"
                ),
            }
        else:
            return {
                "name": f"{suggestion.pattern} コマンド規約",
                "commands": [suggestion.pattern],
                "severity": "warn",
                "message": (
                    f"# {suggestion.count}回の実行を検出。メッセージを書き換えてください\n"
                    "このコマンドを実行する場合は規約を確認してください"
                ),
            }
