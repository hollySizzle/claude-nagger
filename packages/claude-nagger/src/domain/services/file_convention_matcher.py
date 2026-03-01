"""ファイル編集規約マッチングサービス"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from wcmatch import glob as wc_glob

from shared.structured_logging import get_logger


@dataclass
class ConventionRule:
    """規約ルール"""
    name: str
    patterns: List[str]
    severity: str  # 'block', 'warn', 'deny'
    message: str
    token_threshold: Optional[int] = None
    scope: Optional[str] = None  # 'leader' or None（全agent対象）  # 規約別トークン閾値


class FileConventionMatcher:
    """ファイルパスと編集規約のマッチングを行うサービス"""

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
            project_config = base_path / ".claude-nagger" / "file_conventions.yaml"
            if project_config.exists():
                rules_file = project_config
            else:
                # パッケージ内デフォルトを使用
                rules_file = Path(__file__).parent.parent.parent.parent / "rules" / "file_conventions.yaml"
        
        self.rules_file = Path(rules_file)
        self.debug = debug
        # 統一ログディレクトリを使用（structured_logging）
        self.logger = get_logger("FileConventionMatcher")
        self.rules = self._load_rules()

    def _load_rules(self) -> List[ConventionRule]:
        """ルールファイルを読み込む"""
        self.logger.info(f"Loading rules from: {self.rules_file}")
        
        if not self.rules_file.exists():
            self.logger.error(f"Rules file not found: {self.rules_file}")
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
                self.logger.debug(f"Loaded rule: {rule.name} with patterns: {rule.patterns}")
            
            self.logger.info(f"Successfully loaded {len(rules)} rules")
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
            error_msg = f"ルールファイルの読み込みエラー ({self.rules_file}): {e}"
            self.logger.error(error_msg)
            print(error_msg)
            return []

    def matches_pattern(self, file_path: str, patterns: List[str]) -> bool:
        """
        ファイルパスがパターンにマッチするか確認
        wcmatch.globを使用して**パターンを正しくサポート

        Args:
            file_path: チェック対象のファイルパス
            patterns: パターンリスト

        Returns:
            マッチする場合True
        """
        path = Path(file_path)
        
        # 絶対パスの場合、CWDからの相対パスに変換を試みる
        if path.is_absolute():
            try:
                path = path.relative_to(Path.cwd())
                self.logger.info(f"🔄 Converted absolute path to relative: {path}")
            except ValueError:
                # CWD配下にない場合はそのまま使う
                self.logger.info(f"⚠️ Path not under CWD, using as-is: {path}")
        
        normalized_path = str(path.as_posix())
        self.logger.info(f"🔍 PATTERN MATCH DEBUG: Checking file path: {normalized_path}")

        for pattern in patterns:
            self.logger.info(f"  🎯 Testing pattern: {pattern}")

            try:
                # wcmatch.globmatchで**パターンを完全サポート
                if wc_glob.globmatch(normalized_path, pattern, flags=wc_glob.GLOBSTAR):
                    self.logger.info(f"  ✅ Pattern matched: {pattern}")
                    return True

                self.logger.info(f"  ❌ Pattern not matched: {pattern}")

            except Exception as e:
                # 無効なパターンをスキップ
                self.logger.info(f"  ⚠️ Invalid pattern skipped: {pattern} - {e}")
                continue

        self.logger.info(f"🚫 No patterns matched for: {normalized_path}")
        return False

    def check_file(self, file_path: str) -> List[ConventionRule]:
        """
        ファイルパスに該当する全規約を返す
        
        Args:
            file_path: チェック対象のファイルパス
            
        Returns:
            該当する規約ルールのリスト（なければ空リスト）
        """
        self.logger.info(f"📋 CHECK FILE: {file_path}")
        self.logger.info(f"📊 Total rules loaded: {len(self.rules)}")
        
        matched_rules: List[ConventionRule] = []
        for rule in self.rules:
            self.logger.info(f"🔎 Testing rule: {rule.name}")
            if self.matches_pattern(file_path, rule.patterns):
                self.logger.info(f"✅ FILE MATCHED RULE: {rule.name} (severity: {rule.severity})")
                matched_rules.append(rule)
        
        if not matched_rules:
            self.logger.info(f"❌ NO RULES MATCHED FOR FILE: {file_path}")
        
        return matched_rules

    def get_confirmation_message(self, file_path: str) -> List[Dict[str, Any]]:
        """
        確認メッセージを生成（全マッチルール分）
        
        Args:
            file_path: チェック対象のファイルパス
            
        Returns:
            確認メッセージ情報のリスト（なければ空リスト）
        """
        rules = self.check_file(file_path)
        if not rules:
            return []
        
        results = []
        for rule in rules:
            # messageに規約ドキュメントへの参照が既に含まれているため、そのまま使用
            formatted_message = f"""⚠️  {rule.message}"""
            
            results.append({
                'rule_name': rule.name,
                'severity': rule.severity,
                'message': formatted_message,
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