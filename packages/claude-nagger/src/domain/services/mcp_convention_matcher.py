"""MCPツール呼び出し規約マッチングサービス"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .base_convention_matcher import BaseConventionMatcher
from shared.structured_logging import get_logger


@dataclass
class McpConventionRule:
    """MCP規約ルール"""
    name: str
    tool_pattern: str  # 正規表現パターン（re.match）
    severity: str  # 'block', 'warn', 'info'
    message: str
    token_threshold: Optional[int] = None


class McpConventionMatcher(BaseConventionMatcher):
    """MCPツール呼び出しと規約のマッチングを行うサービス"""

    def __init__(self, config_dir: Optional[Path] = None, debug: bool = False):
        """
        初期化

        Args:
            config_dir: 設定ディレクトリのパス
            debug: デバッグモードフラグ
        """
        if config_dir is None:
            # CLAUDE_PROJECT_DIRを優先、フォールバックはcwd
            project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
            base_path = Path(project_dir) if project_dir else Path.cwd()
            project_config = base_path / ".claude-nagger" / "mcp_conventions.yaml"
            if project_config.exists():
                rules_file = project_config
            else:
                # パッケージ内デフォルトを使用
                rules_file = Path(__file__).parent.parent.parent.parent / "rules" / "mcp_conventions.yaml"
        else:
            rules_file = Path(config_dir) / "mcp_conventions.yaml"

        self.rules_file = Path(rules_file)
        self.debug = debug
        # 統一ログディレクトリを使用（structured_logging）
        self.logger = get_logger("McpConventionMatcher")
        self.rules = self._load_rules()

    def _load_rules(self) -> List[McpConventionRule]:
        """ルールファイルを読み込む"""
        self.logger.info(f"Loading MCP rules from: {self.rules_file}")

        if not self.rules_file.exists():
            self.logger.error(f"MCP rules file not found: {self.rules_file}")
            return []

        try:
            with open(self.rules_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            rules = []
            for rule_data in data.get('rules', []):
                # regexパターンのコンパイル確認
                tool_pattern = rule_data['tool_pattern']
                try:
                    re.compile(tool_pattern)
                except re.error as e:
                    self.logger.warning(f"無効な正規表現パターンをスキップ: {tool_pattern} - {e}")
                    continue

                rule = McpConventionRule(
                    name=rule_data['name'],
                    tool_pattern=tool_pattern,
                    severity=rule_data.get('severity', 'warn'),
                    message=rule_data['message'],
                    token_threshold=rule_data.get('token_threshold')
                )
                rules.append(rule)
                self.logger.debug(f"Loaded MCP rule: {rule.name} with pattern: {rule.tool_pattern}")

            self.logger.info(f"Successfully loaded {len(rules)} MCP rules")
            return rules
        except yaml.YAMLError as e:
            error_msg = f"設定ファイル構文エラー ({self.rules_file}): {e}"
            self.logger.error(error_msg)
            print(error_msg)
            return []
        except KeyError as e:
            error_msg = f"設定ファイルに必須フィールドがありません ({self.rules_file}): {e}"
            self.logger.error(error_msg)
            print(error_msg)
            return []
        except Exception as e:
            error_msg = f"MCP規約ルールファイルの読み込みエラー ({self.rules_file}): {e}"
            self.logger.error(error_msg)
            print(error_msg)
            return []

    def matches_pattern(self, tool_name: str, patterns: List[str]) -> bool:
        """
        MCPツール名がパターンにマッチするか確認
        re.matchを使用して正規表現パターンをサポート

        Args:
            tool_name: チェック対象のMCPツール名
            patterns: 正規表現パターンのリスト

        Returns:
            マッチする場合True
        """
        self.logger.info(f"MCP PATTERN MATCH: Checking tool: {tool_name}")

        for pattern in patterns:
            self.logger.info(f"  Testing pattern: {pattern}")

            try:
                if re.match(pattern, tool_name):
                    self.logger.info(f"  Pattern matched: {pattern}")
                    return True

                self.logger.info(f"  Pattern not matched: {pattern}")

            except re.error as e:
                # 無効なパターンをスキップ
                self.logger.warning(f"  無効な正規表現パターンをスキップ: {pattern} - {e}")
                continue

        return False

    def check_tool(self, tool_name: str) -> List[McpConventionRule]:
        """
        MCPツール名に該当する全規約を返す

        Args:
            tool_name: チェック対象のMCPツール名

        Returns:
            該当する規約ルールのリスト（なければ空リスト）
        """
        self.logger.info(f"CHECK MCP TOOL: {tool_name}")
        self.logger.info(f"Total MCP rules loaded: {len(self.rules)}")

        matched_rules: List[McpConventionRule] = []
        for rule in self.rules:
            self.logger.info(f"Testing rule: {rule.name}")
            if self.matches_pattern(tool_name, [rule.tool_pattern]):
                self.logger.info(f"MCP TOOL MATCHED RULE: {rule.name} (severity: {rule.severity})")
                matched_rules.append(rule)

        if not matched_rules:
            self.logger.info(f"NO RULES MATCHED FOR MCP TOOL: {tool_name}")

        return matched_rules

    def get_confirmation_message(self, tool_name: str) -> List[Dict[str, Any]]:
        """
        確認メッセージを生成（全マッチルール分）

        Args:
            tool_name: チェック対象のMCPツール名

        Returns:
            確認メッセージ情報のリスト（なければ空リスト）
        """
        rules = self.check_tool(tool_name)
        if not rules:
            return []

        results = []
        for rule in rules:
            results.append({
                'rule_name': rule.name,
                'severity': rule.severity,
                'message': rule.message,
                'tool_name': tool_name,
                'token_threshold': rule.token_threshold
            })

        return results

    def reload_rules(self):
        """ルールをリロード"""
        self.rules = self._load_rules()

    def list_rules(self) -> List[McpConventionRule]:
        """
        全ルールのリストを返す

        Returns:
            McpConventionRuleのリスト
        """
        return list(self.rules)
