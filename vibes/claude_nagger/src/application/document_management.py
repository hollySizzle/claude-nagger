"""ドキュメント管理オーケストレータ"""

from typing import Optional, List
from pathlib import Path
import questionary
from domain.services.toc_generator import TocGenerator
from domain.services.reference_checker import ReferenceChecker
from domain.services.document_generator import DocumentGenerator
from infrastructure.config.config_manager import ConfigManager
from shared.base.base_cli import BaseCLI


class DocumentManagementCLI(BaseCLI):
    """ドキュメント管理オーケストレータ"""

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.toc_generator = TocGenerator()
        self.reference_checker = ReferenceChecker()
        self.doc_generator = DocumentGenerator(self.config)

    @classmethod
    def add_parser_arguments(cls, parser):
        """メインパーサーに引数を追加（オーケストレータの責務）"""
        doc_actions = ['check_all', 'check_file', 'update_all', 'update_file', 'generate']
        action_help = f"実行するアクション。利用可能: {', '.join(doc_actions)}"
        
        parser.add_argument('--action', choices=doc_actions, help=action_help)
        parser.add_argument('--file', type=str, help='対象ファイルパス (check_file, update_file で必須)')
        parser.add_argument('--quiet', action='store_true', help='簡潔出力モード (例: "12 errors, 0 warnings")')
        
        # generateアクション用の引数
        parser.add_argument('--doc-type', choices=['rules', 'specs', 'tasks', 'logics', 'temps'],
                           help='ドキュメントタイプ (generate で必須)')
        parser.add_argument('--filename', type=str, help='ファイル名 (拡張子不要, generate で必須)')

    def show_menu(self) -> str:
        """サブメニュー表示"""
        choices = [
            "📝 新規ドキュメント生成",
            "🔄 目次更新 (単一ファイル)",
            "📚 目次一括更新 (全ファイル)",
            "🔍 参照チェック (単一ファイル)",
            "✅ 参照一括チェック (全ファイル)",
            "🔙 メインメニューに戻る"
        ]

        return questionary.select(
            "ドキュメント管理機能を選択:",
            choices=choices
        ).ask()

    def run_interactive(self):
        """対話的実行"""
        while True:
            choice = self.show_menu()

            if not choice or "メインメニュー" in choice:
                break

            if "新規ドキュメント生成" in choice:
                self.generate_new_document()
            elif "目次更新 (単一" in choice:
                self.update_single_toc()
            elif "目次一括更新" in choice:
                self.update_all_tocs()
            elif "参照チェック (単一" in choice:
                self.check_single_reference()
            elif "参照一括チェック" in choice:
                self.check_all_references()

    def run_non_interactive(self, action: str, file_path: Optional[str] = None, doc_type: Optional[str] = None, filename: Optional[str] = None) -> dict:
        """非対話モード実行"""
        if action == 'check_all':
            return self._check_all_references_silent()
        elif action == 'check_file' and file_path:
            return self._check_single_reference_silent(file_path)
        elif action == 'update_all':
            return self._update_all_tocs_silent()
        elif action == 'update_file' and file_path:
            return self._update_single_toc_silent(file_path)
        elif action == 'generate' and doc_type and filename:
            return self._generate_document_silent(doc_type, filename)
        else:
            return {'success': False, 'error': f'Unknown action: {action}'}

    def run_with_args(self, action: str, file_path: str = None, quiet: bool = False, doc_type: str = None, filename: str = None) -> int:
        """コマンドライン引数で非対話実行（オーケストレータの責務）"""
        # アクションのバリデーションと実行
        valid_actions = ['check_all', 'check_file', 'update_all', 'update_file', 'generate']
        
        if action not in valid_actions:
            if not quiet:
                self.print_error(f'不正なアクション: {action}')
                self.print_info(f'有効なアクション: {", ".join(valid_actions)}')
            return 1
        
        # ファイルパスが必要なアクションのチェック
        if action in ['check_file', 'update_file'] and not file_path:
            if not quiet:
                self.print_error(f'{action}には--fileオプションが必要です')
            return 1
        
        # generateアクションの引数チェック
        if action == 'generate':
            if not doc_type:
                if not quiet:
                    self.print_error('generateには--doc-typeオプションが必要です')
                return 1
            if not filename:
                if not quiet:
                    self.print_error('generateには--filenameオプションが必要です')
                return 1
        
        # 実行
        result = self.run_non_interactive(action, file_path, doc_type, filename)
        
        # 結果出力
        if quiet:
            # 簡潔出力
            if action in ['check_all', 'check_file']:
                print(f"{result['errors']} errors, {result['warnings']} warnings")
            elif action in ['update_all', 'update_file']:
                if 'updated_count' in result:
                    print(f"Updated {result['updated_count']} files")
                else:
                    print("Updated" if result['success'] else "Failed")
            elif action == 'generate':
                if result['success']:
                    print(f"Generated: {result.get('file_path', 'file created')}")
                else:
                    print("Generation failed")
        else:
            # 詳細出力
            if action in ['check_all', 'check_file']:
                if result['errors'] > 0:
                    self.print_error(f"合計 {result['errors']}個のエラーが見つかりました")
                    # エラーの詳細情報を表示
                    self._print_error_details(result['details'])
                else:
                    self.print_success("問題なし")
                    
                if result['warnings'] > 0:
                    self.print_warning(f"合計 {result['warnings']}個の警告")
                    # 警告の詳細情報を表示
                    self._print_warning_details(result['details'])
            elif action in ['update_all', 'update_file']:
                if result['success']:
                    if action == 'update_all' and 'total_count' in result:
                        updated = result.get('updated_count', 0)
                        skipped = result.get('skipped_count', 0)
                        total = result.get('total_count', 0)
                        failed = result.get('failed_count', 0)
                        
                        self.print_success(f"目次更新完了: {updated}件更新, {skipped}件スキップ, {failed}件失敗 (全{total}件)")
                        
                        if skipped > 0:
                            self.print_info("TOCセクション仕様: '## TOC' または '## 目次' をファイルに追加して目次更新を有効化")
                    elif 'updated_count' in result:
                        self.print_success(f"{result['updated_count']}個のファイルの目次を更新しました")
                    else:
                        self.print_success("ファイルの目次を更新しました")
                else:
                    self.print_error("更新に失敗しました")
                    # 更新失敗の詳細情報を表示
                    self._print_update_error_details(result['details'])
            elif action == 'generate':
                if result['success']:
                    file_path = result.get('file_path', '不明なファイル')
                    self.print_success(f"ドキュメント生成完了: {file_path}")
                    
                    # 自動実行された追加処理の情報
                    self.print_info("自動実行: 目次更新と参照チェックを実行しました")
                else:
                    self.print_error("ドキュメント生成に失敗しました")
                    if 'error' in result:
                        self.print_error(f"エラー詳細: {result['error']}")
        
        return 0 if result['success'] else 1

    @classmethod
    def can_handle_action(cls, action: str) -> bool:
        """このオーケストレータが処理できるアクションか確認"""
        valid_actions = ['check_all', 'check_file', 'update_all', 'update_file', 'generate']
        return action in valid_actions

    def generate_new_document(self):
        """新規ドキュメント生成"""
        doc_type = questionary.select(
            "ドキュメントタイプを選択:",
            choices=["rules", "specs", "tasks", "logics", "temps"]
        ).ask()

        filename = questionary.text(
            "ファイル名を入力 (拡張子不要):"
        ).ask()

        if filename:
            result = self.doc_generator.generate(doc_type, filename)
            if result['success']:
                self.print_success(f"{result['file_path']} を生成しました")

                # 自動的に目次更新と参照チェック
                self.toc_generator.update_file(result['file_path'])
                self.reference_checker.check_file(result['file_path'])
            else:
                self.print_error(f"エラー: {result['error']}")

    def update_single_toc(self):
        """単一ファイルの目次更新"""
        file_path = questionary.text(
            "ファイルパスを入力 (相対パスまたは絶対パス):"
        ).ask()

        if file_path:
            path = Path(file_path)
            result = self.toc_generator.update_file(path)
            
            if result['success']:
                self.print_success(f"目次を更新しました: {path}")
            else:
                self.print_error(f"エラー: {result.get('error', '不明なエラー')}")

    def update_all_tocs(self):
        """全ファイルの目次一括更新"""
        if questionary.confirm("全ドキュメントの目次を更新しますか？").ask():
            self.print_progress("全ファイルの目次を更新中...")
            
            # ConfigManagerからドキュメントルートを取得
            doc_root = self.config.get_doc_root()
            result = self.toc_generator.update_all(doc_root)
            
            if result['success']:
                updated_count = len([r for r in result['results'] if r['success']])
                self.print_success(f"{updated_count}個のファイルの目次を更新しました")
            else:
                self.print_error("一部のファイルで更新に失敗しました")
                for r in result['results']:
                    if not r['success']:
                        self.print_warning(f"  - {r['file']}")

    def check_single_reference(self):
        """単一ファイルの参照チェック"""
        file_path = questionary.text(
            "チェックするファイルパスを入力:"
        ).ask()

        if file_path:
            path = Path(file_path)
            result = self.reference_checker.check_file(path)
            
            if result['errors']:
                self.print_error(f"{len(result['errors'])}個のエラーが見つかりました:")
                for error in result['errors']:
                    print(f"  - {error}")
                
            if result['warnings']:
                self.print_warning(f"{len(result['warnings'])}個の警告が見つかりました:")
                for warning in result['warnings']:
                    print(f"  - {warning}")
            
            if not result['errors'] and not result['warnings']:
                self.print_success("エラーや警告はありませんでした")

    def check_all_references(self):
        """全ファイルの参照一括チェック"""
        if questionary.confirm("全ドキュメントの参照をチェックしますか？").ask():
            self.print_progress("全ファイルの参照をチェック中...")
            
            # ConfigManagerからドキュメントルートを取得
            doc_root = self.config.get_doc_root()
            result = self.reference_checker.check_all(doc_root)
            
            total_errors = sum(len(r.get('errors', [])) for r in result['results'])
            total_warnings = sum(len(r.get('warnings', [])) for r in result['results'])
            
            if total_errors > 0:
                self.print_error(f"合計 {total_errors}個のエラーが見つかりました")
            
            if total_warnings > 0:
                self.print_warning(f"合計 {total_warnings}個の警告が見つかりました")
            
            if total_errors == 0 and total_warnings == 0:
                self.print_success("すべてのファイルで問題は見つかりませんでした")

    def _check_all_references_silent(self) -> dict:
        """全ファイルの参照チェック（非対話）"""
        doc_root = self.config.get_doc_root()
        result = self.reference_checker.check_all(doc_root)
        
        total_errors = sum(len(r.get('errors', [])) for r in result['results'])
        total_warnings = sum(len(r.get('warnings', [])) for r in result['results'])
        
        return {
            'success': total_errors == 0,
            'errors': total_errors,
            'warnings': total_warnings,
            'details': result
        }

    def _check_single_reference_silent(self, file_path: str) -> dict:
        """単一ファイルの参照チェック（非対話）"""
        path = Path(file_path)
        result = self.reference_checker.check_file(path)
        
        # 単一ファイル結果を全ファイル形式に変換
        formatted_result = {
            'results': [{
                'file': str(path),
                'errors': result.get('errors', []),
                'warnings': result.get('warnings', [])
            }]
        }
        
        return {
            'success': len(result['errors']) == 0,
            'errors': len(result['errors']),
            'warnings': len(result['warnings']),
            'details': formatted_result
        }

    def _update_all_tocs_silent(self) -> dict:
        """全ファイルの目次更新（非対話）"""
        try:
            doc_root = self.config.get_doc_root()
            result = self.toc_generator.update_all(doc_root)
            
            # サマリ情報を使用
            summary = result.get('summary', {})
            updated_count = summary.get('updated', 0)
            skipped_count = summary.get('skipped', 0)
            
            return {
                'success': result.get('success', False),
                'updated_count': updated_count,
                'skipped_count': skipped_count,
                'total_count': summary.get('total', 0),
                'failed_count': summary.get('failed', 0),
                'details': result
            }
        except Exception as e:
            return {
                'success': False,
                'updated_count': 0,
                'details': {'error': str(e)}
            }

    def _update_single_toc_silent(self, file_path: str) -> dict:
        """単一ファイルの目次更新（非対話）"""
        try:
            path = Path(file_path)
            result = self.toc_generator.update_file(path)
            
            return {
                'success': result.get('success', False),
                'details': result
            }
        except Exception as e:
            return {
                'success': False,
                'details': {'error': str(e)}
            }

    def _print_error_details(self, details: dict):
        """エラーの詳細情報を表示"""
        if 'results' in details:
            for file_result in details['results']:
                if file_result.get('errors'):
                    file_path = file_result.get('file', '不明なファイル')
                    print(f"  📄 {file_path}:")
                    for error in file_result['errors']:
                        print(f"    • {error}")

    def _print_warning_details(self, details: dict):
        """警告の詳細情報を表示"""
        if 'results' in details:
            for file_result in details['results']:
                if file_result.get('warnings'):
                    file_path = file_result.get('file', '不明なファイル')
                    print(f"  📄 {file_path}:")
                    for warning in file_result['warnings']:
                        print(f"    • {warning}")

    def _print_update_error_details(self, details: dict):
        """更新エラーの詳細情報を表示"""
        if 'results' in details:
            for file_result in details['results']:
                if not file_result.get('success', True):
                    file_path = file_result.get('file', '不明なファイル')
                    error_msg = file_result.get('error', '不明なエラー')
                    print(f"  📄 {file_path}: {error_msg}")
        elif 'error' in details:
            # 全体エラーの場合
            print(f"  エラー: {details['error']}")

    def _generate_document_silent(self, doc_type: str, filename: str) -> dict:
        """ドキュメント生成（非対話）"""
        try:
            result = self.doc_generator.generate(doc_type, filename)
            
            if result.get('success', False):
                # 自動的に目次更新と参照チェック
                file_path = result.get('file_path')
                if file_path:
                    from pathlib import Path
                    path_obj = Path(file_path)
                    self.toc_generator.update_file(path_obj)
                    self.reference_checker.check_file(path_obj)
                
            return result
            
        except Exception as e:
            return {
                'success': False,
                'error': f'ドキュメント生成エラー: {str(e)}'
            }