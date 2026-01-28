"""Stop hook: セッション終了時に規約提案をバックグラウンド実行"""

import glob as std_glob
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.hooks.base_hook import BaseHook
from domain.services.rule_suggester import RuleSuggester, PatternSuggestion
from shared.structured_logging import DEFAULT_LOG_DIR
from shared.constants import SUGGESTED_RULES_FILENAME

logger = logging.getLogger(__name__)


class SuggestRulesTrigger(BaseHook):
    """Stop hook: セッション終了時に規約提案をバックグラウンド実行

    フロー:
      1. hook_input_*.json件数チェック（閾値未満→スキップ）
      2. 閾値以上→バックグラウンドプロセス起動（nohup）
      3. hook自体は即座にexit 0（セッション終了をブロックしない）
    """

    DEFAULT_MIN_INPUTS = 10
    DEFAULT_MODEL = "sonnet"

    def __init__(
        self,
        min_inputs: Optional[int] = None,
        model: Optional[str] = None,
    ):
        """初期化

        Args:
            min_inputs: バックグラウンド処理起動の最小hook_input件数
            model: claude --printで使用するモデル名
        """
        super().__init__(debug=True)
        self.min_inputs = min_inputs or self.DEFAULT_MIN_INPUTS
        self.model = model or self.DEFAULT_MODEL

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """hook_input件数が閾値以上か確認"""
        count = self._count_hook_inputs()
        if count < self.min_inputs:
            self.log_info(
                f"hook入力{count}件 < 閾値{self.min_inputs}件, スキップ"
            )
            return False
        self.log_info(
            f"hook入力{count}件 >= 閾値{self.min_inputs}件, バックグラウンド処理起動"
        )
        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """バックグラウンドプロセスを起動して即座に終了"""
        self._launch_background()
        return {"decision": "approve", "reason": ""}

    def _count_hook_inputs(self) -> int:
        """hook_input_*.jsonの件数をカウント"""
        pattern = str(self.log_dir / "hook_input_*.json")
        return len(std_glob.glob(pattern))

    def _launch_background(self) -> None:
        """バックグラウンド処理をnohup起動

        セッション終了をブロックしないよう、子プロセスを分離して起動。
        """
        python_exec = sys.executable
        module_path = "domain.hooks.suggest_rules_trigger"
        cmd = [
            "nohup", python_exec, "-m", module_path,
            "--background",
            "--model", self.model,
        ]
        env = os.environ.copy()
        # PYTHONPATHにsrcディレクトリを追加
        src_dir = str(Path(__file__).resolve().parent.parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_dir}:{existing}" if existing else src_dir

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            self.log_info("バックグラウンドプロセス起動完了")
        except Exception as e:
            self.log_error(f"バックグラウンドプロセス起動失敗: {e}")


def _build_prompt(
    file_suggestions: List[PatternSuggestion],
    command_suggestions: List[PatternSuggestion],
    stats: Dict[str, Any],
) -> str:
    """RuleSuggester分析結果からclaude --print用プロンプトを構築"""
    lines = [
        "以下はClaude Codeセッション中のhook入力の統計分析結果です。",
        "この統計に基づき、プロジェクト規約候補をYAML形式で提案してください。",
        "",
        "## 統計情報",
        f"- 分析対象: {stats['total_inputs']}件のhook入力",
        f"- ファイル操作: {stats.get('file_inputs', 0)}件",
        f"- コマンド実行: {stats.get('command_inputs', 0)}件",
        "",
    ]

    if file_suggestions:
        lines.append("## ファイルパターン（頻度順）")
        for s in file_suggestions:
            examples = ", ".join(s.examples[:3]) if s.examples else ""
            example_str = f"  例: {examples}" if examples else ""
            lines.append(f"- `{s.pattern}` ({s.count}回){example_str}")
        lines.append("")

    if command_suggestions:
        lines.append("## コマンドパターン（頻度順）")
        for s in command_suggestions:
            examples = ", ".join(s.examples[:3]) if s.examples else ""
            example_str = f"  例: {examples}" if examples else ""
            lines.append(f"- `{s.pattern}` ({s.count}回){example_str}")
        lines.append("")

    lines.extend([
        "## 出力形式",
        "以下のYAML形式で出力してください。```yaml と ``` で囲んでください。",
        "",
        "```yaml",
        "rules:",
        "  - name: \"規約名\"",
        "    patterns:  # ファイル規約の場合",
        "      - \"glob_pattern\"",
        "    commands:  # コマンド規約の場合",
        "      - \"command_prefix\"",
        "    severity: warn",
        "    message: |",
        "      このファイル/コマンドに関する規約メッセージ",
        "```",
        "",
        "注意:",
        "- 頻度の高いパターンを優先してください",
        "- messageはプロジェクト規約として有用な内容にしてください",
        "- 規約名は日本語でわかりやすく記述してください",
        "- 最大10件まで出力してください",
    ])

    return "\n".join(lines)


def _extract_yaml_from_output(output: str) -> Optional[str]:
    """claude --print出力からYAMLブロックを抽出"""
    # ```yaml ... ``` ブロックを探す
    import re
    match = re.search(r"```yaml\s*\n(.*?)```", output, re.DOTALL)
    if match:
        return match.group(1).strip()

    # ```ブロックなしでもYAMLっぽい内容を探す
    if "rules:" in output:
        # rules: で始まる行以降を抽出
        lines = output.split("\n")
        yaml_lines = []
        in_yaml = False
        for line in lines:
            if line.strip().startswith("rules:"):
                in_yaml = True
            if in_yaml:
                yaml_lines.append(line)
        if yaml_lines:
            return "\n".join(yaml_lines)

    return None


def _fallback_yaml(
    file_suggestions: List[PatternSuggestion],
    command_suggestions: List[PatternSuggestion],
    stats: Dict[str, Any],
) -> str:
    """claude CLI非存在時のフォールバック: Python統計のみでYAML生成"""
    import yaml

    MAX_RULES = 10

    # ファイルとコマンドの候補を統合し、頻度順でソート
    all_suggestions = list(file_suggestions) + list(command_suggestions)
    all_suggestions.sort(key=lambda s: s.count, reverse=True)
    all_suggestions = all_suggestions[:MAX_RULES]

    rules = []
    for s in all_suggestions:
        if s.category == "file":
            rules.append({
                "name": f"{s.pattern} 編集規約",
                "patterns": [s.pattern],
                "severity": "warn",
                "message": (
                    f"# {s.count}回の編集を検出（自動提案）\n"
                    "このファイルを変更する場合は規約を確認してください"
                ),
            })
        else:
            rules.append({
                "name": f"{s.pattern} コマンド規約",
                "commands": [s.pattern],
                "severity": "warn",
                "message": (
                    f"# {s.count}回の実行を検出（自動提案）\n"
                    "このコマンドを実行する場合は規約を確認してください"
                ),
            })

    if not rules:
        return ""

    data = {"rules": rules}
    yaml_body = yaml.dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )

    today = datetime.now().strftime("%Y-%m-%d")
    header = (
        f"# suggest-rules 自動提案（Python統計のみ）\n"
        f"# 生成日: {today}\n"
        f"# 分析対象: {stats['total_inputs']}件のhook入力\n"
        f"# 注: claude CLIが見つからないためLLM分析なし\n"
        f"\n"
    )
    return header + yaml_body


def _save_suggested_rules(content: str, header: str = "") -> Path:
    """suggested_rules.yamlに保存"""
    output_dir = Path.cwd() / ".claude-nagger"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / SUGGESTED_RULES_FILENAME

    full_content = header + content if header else content
    output_path.write_text(full_content, encoding="utf-8")
    logger.info(f"規約候補を保存: {output_path}")
    return output_path


def run_background_analysis(model: str = "sonnet") -> int:
    """バックグラウンド処理本体

    1. RuleSuggester.analyze() で統計前処理
    2. 前処理結果を構造化プロンプトに整形
    3. claude --print 実行（存在する場合）
    4. LLM出力からYAML抽出
    5. .claude-nagger/suggested_rules.yaml に保存

    Args:
        model: claude --printで使用するモデル名

    Returns:
        0: 成功, 1: エラー
    """
    try:
        # 1. 統計前処理
        suggester = RuleSuggester()
        result = suggester.analyze()

        stats = result["stats"]
        file_suggestions = result["file_suggestions"]
        command_suggestions = result["command_suggestions"]

        if not file_suggestions and not command_suggestions:
            logger.info("規約候補なし、処理終了")
            return 0

        # 2. claude CLI存在チェック
        claude_path = shutil.which("claude")
        if not claude_path:
            logger.info("claude CLIが見つかりません。Python統計のみで出力")
            yaml_content = _fallback_yaml(
                file_suggestions, command_suggestions, stats
            )
            if yaml_content:
                _save_suggested_rules(yaml_content)
            return 0

        # 3. プロンプト整形
        prompt = _build_prompt(file_suggestions, command_suggestions, stats)

        # 4. claude --print 実行
        cmd = [
            claude_path, "--print",
            "--model", model,
            "-p", prompt,
        ]
        logger.info(f"claude --print 実行 (model={model})")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            logger.warning(
                f"claude --print 失敗 (rc={proc.returncode}): {proc.stderr[:200]}"
            )
            # フォールバック
            yaml_content = _fallback_yaml(
                file_suggestions, command_suggestions, stats
            )
            if yaml_content:
                _save_suggested_rules(yaml_content)
            return 0

        # 5. YAML抽出 + 検証
        yaml_content = _extract_yaml_from_output(proc.stdout)
        if yaml_content:
            # YAML構文検証（不正な場合フォールバック）
            try:
                import yaml
                yaml.safe_load(yaml_content)
            except yaml.YAMLError:
                logger.warning("抽出YAMLの構文検証失敗。フォールバック使用")
                yaml_content = None
        if not yaml_content:
            logger.warning("claude出力からYAML抽出失敗。フォールバック使用")
            yaml_content = _fallback_yaml(
                file_suggestions, command_suggestions, stats
            )
            if yaml_content:
                _save_suggested_rules(yaml_content)
            return 0

        # ヘッダ付きで保存
        today = datetime.now().strftime("%Y-%m-%d")
        header = (
            f"# suggest-rules 自動提案（LLM分析済み）\n"
            f"# 生成日: {today}\n"
            f"# 分析対象: {stats['total_inputs']}件のhook入力\n"
            f"# モデル: {model}\n"
            f"\n"
        )
        _save_suggested_rules(yaml_content, header)
        logger.info("バックグラウンド処理完了")
        return 0

    except Exception as e:
        logger.error(f"バックグラウンド処理エラー: {e}")
        return 1


def main():
    """エントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--background", action="store_true",
        help="バックグラウンド処理を実行",
    )
    parser.add_argument(
        "--model", default=SuggestRulesTrigger.DEFAULT_MODEL,
        help="claude --printで使用するモデル",
    )
    args = parser.parse_args()

    if args.background:
        # バックグラウンド処理モード
        sys.exit(run_background_analysis(model=args.model))
    else:
        # 通常のStop hookモード
        hook = SuggestRulesTrigger(model=args.model)
        sys.exit(hook.run())


if __name__ == "__main__":
    main()
