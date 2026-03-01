"""コマンド実行規約マッチングサービス"""

import os
import yaml
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .base_convention_matcher import BaseConventionMatcher
from shared.structured_logging import get_logger


@dataclass
class ConventionRule:
    """規約ルール"""
    name: str
    patterns: List[str]
    severity: str  # 'block', 'warn', 'deny'
    message: str
    token_threshold: Optional[int] = None
    scope: Optional[str] = None  # 'leader' or None（全agent対象）  # 規約別トークン闾値


class CommandConventionMatcher(BaseConventionMatcher):
    """コマンド実行と規約のマッチングを行うサービス"""

    def __init__(self, rules_file: Optional[Path] = None, debug: bool = False):
        """
        初期化
        
        Args:
            rules_file: ルール定義ファイルのパス
            debug: デバッグモードフラグ
        """
        if rules_file is None:
            # CLAUDE_PROJECT_DIRを優先、フォールバックはcwd
            project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
            base_path = Path(project_dir) if project_dir else Path.cwd()
            project_config = base_path / ".claude-nagger" / "command_conventions.yaml"
            if project_config.exists():
                rules_file = project_config
            else:
                # パッケージ内デフォルトを使用
                rules_file = Path(__file__).parent.parent.parent.parent / "rules" / "command_conventions.yaml"
        
        self.rules_file = Path(rules_file)
        self.debug = debug
        # 統一ログディレクトリを使用（structured_logging）
        self.logger = get_logger("CommandConventionMatcher")
        self.rules = self._load_rules()

    def _load_rules(self) -> List[ConventionRule]:
        """ルールファイルを読み込む"""
        self.logger.info(f"Loading command rules from: {self.rules_file}")
        
        if not self.rules_file.exists():
            self.logger.error(f"Command rules file not found: {self.rules_file}")
            return []
        
        try:
            with open(self.rules_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            rules = []
            for rule_data in data.get('rules', []):
                rule = ConventionRule(
                    name=rule_data['name'],
                    patterns=rule_data['patterns'],
                    severity=rule_data.get('severity', 'warn'),
                    message=rule_data['message'],
                    token_threshold=rule_data.get('token_threshold'),
                    scope=rule_data.get('scope')
                )
                rules.append(rule)
                self.logger.debug(f"Loaded command rule: {rule.name} with patterns: {rule.patterns}")
            
            self.logger.info(f"Successfully loaded {len(rules)} command rules")
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
            error_msg = f"コマンド規約ルールファイルの読み込みエラー ({self.rules_file}): {e}"
            self.logger.error(error_msg)
            print(error_msg)
            return []

    def matches_pattern(self, command: str, patterns: List[str]) -> bool:
        """
        コマンドがパターンにマッチするか確認
        fnmatchを使用してワイルドカードパターンをサポート
        
        Args:
            command: チェック対象のコマンド
            patterns: パターンリスト
            
        Returns:
            マッチする場合True
        """
        # コマンドを正規化（余分な空白を除去）
        normalized_command = ' '.join(command.split())
        self.logger.info(f"🔍 COMMAND PATTERN MATCH: Checking command: {normalized_command}")
        
        for pattern in patterns:
            self.logger.info(f"  🎯 Testing pattern: {pattern}")
            
            try:
                # fnmatchでワイルドカードパターンマッチング
                if fnmatch.fnmatch(normalized_command, pattern):
                    self.logger.info(f"  ✅ Pattern matched: {pattern}")
                    return True
                
                # 部分マッチも考慮（コマンドの先頭部分）
                if fnmatch.fnmatch(normalized_command.split()[0], pattern):
                    self.logger.info(f"  ✅ Command prefix matched: {pattern}")
                    return True
                        
                self.logger.info(f"  ❌ Pattern not matched: {pattern}")
                
            except Exception as e:
                # 無効なパターンをスキップ
                self.logger.info(f"  ⚠️ Invalid pattern skipped: {pattern} - {e}")
                continue
        
        self.logger.info(f"🚫 No patterns matched for command: {normalized_command}")
        return False

    def check_command(self, command: str) -> List[ConventionRule]:
        """
        コマンドに該当する全規約を返す
        
        Args:
            command: チェック対象のコマンド
            
        Returns:
            該当する規約ルールのリスト（なければ空リスト）
        """
        self.logger.info(f"📋 CHECK COMMAND: {command}")
        self.logger.info(f"📊 Total command rules loaded: {len(self.rules)}")
        
        matched_rules: List[ConventionRule] = []
        for rule in self.rules:
            self.logger.info(f"🔎 Testing rule: {rule.name}")
            if self.matches_pattern(command, rule.patterns):
                self.logger.info(f"✅ COMMAND MATCHED RULE: {rule.name} (severity: {rule.severity})")
                matched_rules.append(rule)
        
        if not matched_rules:
            self.logger.info(f"❌ NO RULES MATCHED FOR COMMAND: {command}")
        
        return matched_rules

    def get_confirmation_message(self, command: str) -> List[Dict[str, Any]]:
        """
        確認メッセージを生成（全マッチルール分）
        
        Args:
            command: チェック対象のコマンド
            
        Returns:
            確認メッセージ情報のリスト（なければ空リスト）
        """
        rules = self.check_command(command)
        if not rules:
            return []
        
        results = []
        for rule in rules:
            formatted_message = f"""⚠️  {rule.message}

実行コマンド: {command}

続行しますか？"""
            
            results.append({
                'rule_name': rule.name,
                'severity': rule.severity,
                'message': formatted_message,
                'command': command,
                'token_threshold': rule.token_threshold,
                'scope': rule.scope
            })
        
        return results

    def reload_rules(self):
        """ルールをリロード"""
        self.rules = self._load_rules()

    def list_rules(self) -> List[Dict[str, Any]]:
        """
        全ルールのリストを返す
        
        Returns:
            ルール情報のリスト
        """
        return [
            {
                'name': rule.name,
                'patterns': rule.patterns,
                'message': rule.message,
                'severity': rule.severity
            }
            for rule in self.rules
        ]