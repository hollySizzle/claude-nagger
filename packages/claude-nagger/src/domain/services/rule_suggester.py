"""hook入力JSON分析エンジン（規約候補パターンの統計的抽出）"""

import json
import glob as std_glob
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import Counter

from shared.structured_logging import get_logger, DEFAULT_LOG_DIR
from .file_convention_matcher import FileConventionMatcher
from .command_convention_matcher import CommandConventionMatcher


@dataclass
class PatternSuggestion:
    """規約候補パターン"""
    category: str           # "file" or "command"
    pattern: str            # globパターン or コマンドプレフィックス
    count: int              # 出現回数
    examples: List[str] = field(default_factory=list)  # 元データの例（最大3件）


class RuleSuggester:
    """hook入力JSONを分析し、規約候補パターンを統計的に抽出するサービス"""

    # 分析対象ツール名
    FILE_TOOLS = {"Edit", "Write"}
    COMMAND_TOOLS = {"Bash"}
    # 除外対象: Read, mcp__* などは対象外

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        cwd: Optional[Path] = None,
        file_matcher: Optional[FileConventionMatcher] = None,
        command_matcher: Optional[CommandConventionMatcher] = None,
        session_id: Optional[str] = None,
    ):
        """
        初期化

        Args:
            log_dir: hook_input_*.jsonの格納ディレクトリ
            cwd: 相対パス変換用の作業ディレクトリ
            file_matcher: 既存ファイル規約マッチャー（重複除外用）
            command_matcher: 既存コマンド規約マッチャー（重複除外用）
            session_id: 特定セッションのみ分析（Noneで全セッション対象）
        """
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.cwd = cwd or Path.cwd()
        self.logger = get_logger("RuleSuggester")
        self._file_matcher = file_matcher or FileConventionMatcher()
        self._command_matcher = command_matcher or CommandConventionMatcher()
        self._session_id = session_id

    def analyze(self) -> Dict[str, Any]:
        """
        メイン分析処理

        Returns:
            分析結果（file_suggestions, command_suggestions, stats）
        """
        inputs = self._load_hook_inputs()
        if not inputs:
            self.logger.info("分析対象のhook_input JSONなし")
            return {"file_suggestions": [], "command_suggestions": [], "stats": {"total_inputs": 0}}

        file_paths, commands = self._classify_inputs(inputs)

        # パターン集約
        file_suggestions = self._aggregate_file_patterns(file_paths)
        command_suggestions = self._aggregate_command_prefixes(commands)

        # 既存ルール重複除外
        file_suggestions = self._exclude_existing_file_rules(file_suggestions)
        command_suggestions = self._exclude_existing_command_rules(command_suggestions)

        # 頻度降順ソート
        file_suggestions.sort(key=lambda s: s.count, reverse=True)
        command_suggestions.sort(key=lambda s: s.count, reverse=True)

        self.logger.info(
            f"分析完了: 入力{len(inputs)}件, "
            f"ファイル候補{len(file_suggestions)}件, "
            f"コマンド候補{len(command_suggestions)}件"
        )

        return {
            "file_suggestions": file_suggestions,
            "command_suggestions": command_suggestions,
            "stats": {
                "total_inputs": len(inputs),
                "file_inputs": len(file_paths),
                "command_inputs": len(commands),
            },
        }

    def _load_hook_inputs(self) -> List[Dict[str, Any]]:
        """hook_input_*.jsonを読込（session_id指定時はフィルタ）"""
        if self._session_id:
            pattern = str(self.log_dir / f"hook_input_{self._session_id}_*.json")
        else:
            pattern = str(self.log_dir / "hook_input_*.json")
        files = std_glob.glob(pattern)
        self.logger.info(f"hook_input JSON検出: {len(files)}件 ({self.log_dir})")

        results = []
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append(data)
            except (json.JSONDecodeError, OSError) as e:
                self.logger.warning(f"JSON読込失敗: {filepath} - {e}")
                continue

        return results

    def _classify_inputs(
        self, inputs: List[Dict[str, Any]]
    ) -> Tuple[List[str], List[str]]:
        """
        tool_nameで振り分け

        Returns:
            (file_paths, commands) のタプル
        """
        file_paths: List[str] = []
        commands: List[str] = []

        for data in inputs:
            tool_name = data.get("tool_name", "")
            tool_input = data.get("tool_input", {})

            if tool_name in self.FILE_TOOLS:
                fp = tool_input.get("file_path", "")
                if fp:
                    file_paths.append(fp)
            elif tool_name in self.COMMAND_TOOLS:
                cmd = tool_input.get("command", "")
                if cmd:
                    commands.append(cmd)
            # Read, mcp__* は対象外

        self.logger.info(f"分類結果: ファイル{len(file_paths)}件, コマンド{len(commands)}件")
        return file_paths, commands

    def _to_relative_path(self, file_path: str) -> str:
        """絶対パスをcwdからの相対パスに変換"""
        path = Path(file_path)
        if path.is_absolute():
            try:
                return str(path.relative_to(self.cwd))
            except ValueError:
                # cwd配下にない場合はそのまま返す
                return file_path
        return file_path

    def _aggregate_file_patterns(self, file_paths: List[str]) -> List[PatternSuggestion]:
        """
        ファイルパスをディレクトリ階層+拡張子でglobパターンに集約

        例: src/domain/hooks/base_hook.py, src/domain/hooks/session_startup_hook.py
            → src/domain/hooks/**/*.py (2回)

        拡張子なしファイル（Makefile等）は **/ファイル名 パターンを生成。
        サブディレクトリ包含関係のあるパターンは親パターンにマージする。
        """
        # ディレクトリ+拡張子でグルーピング
        group_counter: Counter = Counter()
        group_examples: Dict[str, List[str]] = {}

        for fp in file_paths:
            rel_path = self._to_relative_path(fp)
            p = Path(rel_path)
            suffix = p.suffix
            parent = str(p.parent) if str(p.parent) != "." else ""

            # globパターン生成
            if not suffix:
                # 拡張子なしファイル（Makefile, Dockerfile等）はファイル名をパターンに使用
                pattern = f"**/{p.name}" if not parent else f"{parent}/**/{p.name}"
            elif parent:
                pattern = f"{parent}/**/*{suffix}"
            else:
                pattern = f"**/*{suffix}"

            group_counter[pattern] += 1
            if pattern not in group_examples:
                group_examples[pattern] = []
            if len(group_examples[pattern]) < 3:
                group_examples[pattern].append(rel_path)

        # サブディレクトリ包含関係のマージ
        # 例: src/domain/hooks/**/*.py が src/domain/hooks/sub/**/*.py を包含
        merged = self._merge_contained_patterns(group_counter, group_examples)

        return merged

    def _merge_contained_patterns(
        self,
        counter: Counter,
        examples: Dict[str, List[str]],
    ) -> List[PatternSuggestion]:
        """
        包含関係のあるglobパターンを親パターンにマージ

        例: src/domain/hooks/**/*.py (3回) と src/domain/hooks/sub/**/*.py (1回)
            → src/domain/hooks/**/*.py (4回) にマージ
        """
        patterns = list(counter.keys())
        merged_into: Dict[str, str] = {}  # child → parent

        for i, child in enumerate(patterns):
            for j, parent in enumerate(patterns):
                if i == j:
                    continue
                # parentがchildを包含するか判定:
                # parent="dir/**/*.py", child="dir/sub/**/*.py" の場合、
                # childのディレクトリがparentのディレクトリ配下かつ拡張子が同一
                if self._pattern_contains(parent, child):
                    # より浅い（短い）パターンを親とする
                    if child not in merged_into:
                        merged_into[child] = parent

        # マージ実行（推移的にtargetを解決）
        final_counter: Counter = Counter()
        final_examples: Dict[str, List[str]] = {}

        for pattern, count in counter.items():
            target = self._resolve_target(merged_into, pattern)
            final_counter[target] += count
            if target not in final_examples:
                final_examples[target] = []
            for ex in examples.get(pattern, []):
                if len(final_examples[target]) < 3:
                    final_examples[target].append(ex)

        return [
            PatternSuggestion(
                category="file",
                pattern=p,
                count=c,
                examples=final_examples.get(p, []),
            )
            for p, c in final_counter.items()
        ]

    @staticmethod
    def _resolve_target(merged_into: Dict[str, str], pattern: str) -> str:
        """推移的にマージ先を辿り最終的なtargetを返す（union-find方式）"""
        target = pattern
        visited = set()
        while target in merged_into:
            if target in visited:
                break  # 循環防止
            visited.add(target)
            target = merged_into[target]
        return target

    @staticmethod
    def _pattern_contains(parent: str, child: str) -> bool:
        """
        親パターンが子パターンを包含するか判定

        条件: 同一拡張子パターンかつ子のディレクトリが親のディレクトリ配下
        例: "src/**/*.py" は "src/domain/**/*.py" を包含
        """
        if parent == child:
            return False

        def _decompose(pattern: str) -> tuple:
            """パターンを (ディレクトリ部分, ファイル部分) に分解"""
            if "/**/" in pattern:
                parts = pattern.split("/**/", 1)
                return parts[0], parts[1]
            elif pattern.startswith("**/"):
                # **/xxx → ルートパターン（ディレクトリ部分なし）
                return "", pattern[3:]
            return None, None

        parent_dir, parent_file = _decompose(parent)
        child_dir, child_file = _decompose(child)

        if parent_file is None or child_file is None:
            return False

        # ファイル部分（拡張子パターン or ファイル名）が一致すること
        if parent_file != child_file:
            return False

        # 親ディレクトリが空（ルート）なら全て包含
        if not parent_dir:
            return bool(child_dir)

        if not child_dir:
            return False

        # 子ディレクトリが親ディレクトリ配下か
        return child_dir.startswith(parent_dir + "/")

    def _extract_command_prefix(self, command: str) -> str:
        """
        コマンドプレフィックスを抽出（第1トークン or パイプ前の第1トークン）

        例:
            "python3 scripts/capture.py" → "python3"
            "ls -la | head -30" → "ls"
            "git commit -m 'fix'" → "git"

        注意: &&/; によるチェーンコマンドは未対応（意図的仕様）。
        チェーンコマンドは先頭コマンドがプレフィックスとなる。
        例: "cd /tmp && git status" → "cd"
        将来的に主コマンド判定が必要な場合は拡張を検討。
        """
        # パイプ前を取得（&&/;チェーンは非分割・先頭コマンドを採用）
        before_pipe = command.split("|")[0].strip()
        # 最初のトークン
        tokens = before_pipe.split()
        return tokens[0] if tokens else command

    def _aggregate_command_prefixes(self, commands: List[str]) -> List[PatternSuggestion]:
        """コマンドプレフィックスで集約"""
        prefix_counter: Counter = Counter()
        prefix_examples: Dict[str, List[str]] = {}

        for cmd in commands:
            prefix = self._extract_command_prefix(cmd)
            prefix_counter[prefix] += 1
            if prefix not in prefix_examples:
                prefix_examples[prefix] = []
            if len(prefix_examples[prefix]) < 3:
                # コマンド全体を例として保存（長すぎる場合は切り詰め）
                example = cmd[:100] + "..." if len(cmd) > 100 else cmd
                prefix_examples[prefix].append(example)

        return [
            PatternSuggestion(
                category="command",
                pattern=f"{prefix}*",
                count=count,
                examples=prefix_examples.get(prefix, []),
            )
            for prefix, count in prefix_counter.items()
        ]

    def _exclude_existing_file_rules(
        self, suggestions: List[PatternSuggestion]
    ) -> List[PatternSuggestion]:
        """
        既存ファイル規約ルールと重複する候補を除外

        注意: 現時点はパターン文字列の完全一致で判定。
        包含関係（例: 既存 src/**/*.py が候補 src/domain/**/*.py を包含）は未考慮。
        将来的にglob包含判定が必要な場合はここを拡張する。
        """
        existing_patterns = set()
        for rule in self._file_matcher.list_rules():
            for p in rule.get("patterns", []):
                existing_patterns.add(p)

        return [
            s for s in suggestions
            if s.pattern not in existing_patterns
        ]

    def _exclude_existing_command_rules(
        self, suggestions: List[PatternSuggestion]
    ) -> List[PatternSuggestion]:
        """
        既存コマンド規約ルールと重複する候補を除外

        注意: パターン文字列の完全一致で判定。包含関係は未考慮。
        """
        existing_patterns = set()
        for rule in self._command_matcher.list_rules():
            for p in rule.get("patterns", []):
                existing_patterns.add(p)

        return [
            s for s in suggestions
            if s.pattern not in existing_patterns
        ]
