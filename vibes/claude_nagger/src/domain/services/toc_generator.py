"""目次生成サービス（旧Node.js update-toc.js の移植）"""

from typing import Dict, List, Optional
from pathlib import Path
import re
from ..entities.document_entity import Document


class TocGenerator:
    """目次生成サービス"""

    def __init__(self):
        # TOCまたは目次を含むセクションを検出
        self.toc_pattern = re.compile(r'^##\s+(?:TOC|.*目次.*)', re.MULTILINE)
        self.heading_pattern = re.compile(r'^(#{1,6})\s+(.+)', re.MULTILINE)
        self.index_pattern = re.compile(r'^##\s+各ドキュメント一覧', re.MULTILINE)

    def update_file(self, file_path: Path) -> Dict:
        """単一ファイルの目次更新"""
        try:
            document = Document(file_path)
            # INDEX.mdファイルは特別処理で完全再生成
            if file_path.name == 'INDEX.md':
                return self._update_index_file(document)
            else:
                # 通常ファイルはTOCセクションのみ更新
                return self._update_regular_file(document)

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def update_all(self, directory: Path) -> Dict:
        """全ファイル一括更新"""
        results = []

        # INDEX.mdファイルが存在しない場合は自動生成
        index_path = directory / 'INDEX.md'
        if not index_path.exists():
            try:
                from ..entities.document_entity import Document
                document = Document(index_path)
                index_result = self._update_index_file(document)
                results.append({
                    'file': str(index_path),
                    'success': index_result.get('success', False)
                })
            except Exception as e:
                results.append({
                    'file': str(index_path),
                    'success': False,
                    'error': str(e)
                })

        for md_file in directory.rglob("*.md"):
            if md_file.name.startswith("_template"):
                continue

            result = self.update_file(md_file)
            file_result = {
                'file': str(md_file),
                'success': result.get('success', False)
            }
            
            # エラー情報を保持
            if not result.get('success', False) and 'error' in result:
                file_result['error'] = result['error']
                
            results.append(file_result)

        # スキップされたファイルは成功とみなす
        success_count = len([r for r in results if r.get('success', False)])
        
        return {
            'success': success_count > 0,  # 1件以上成功していればOK
            'results': results,
            'summary': {
                'total': len(results),
                'updated': len([r for r in results if r.get('success', False) and not r.get('skipped', False)]),
                'skipped': len([r for r in results if r.get('skipped', False)]),
                'failed': len([r for r in results if not r.get('success', False)])
            }
        }

    def _update_regular_file(self, document: Document) -> Dict:
        """通常ファイルの目次更新"""
        try:
            content = document.read()
            
            # TOCセクションが存在しない場合はスキップ
            if not self.toc_pattern.search(content):
                return {
                    'success': True,
                    'skipped': True,
                    'reason': 'TOCセクションが存在しません。使用方法: ## TOC または ## 目次 セクションを追加してください。'
                }
            
            # 既存の処理を継続...
            return self._perform_toc_update(content, document)
            
        except Exception as e:
            return {'success': False, 'error': f'処理エラー: {str(e)}'}
    
    def _perform_toc_update(self, content: str, document: Document) -> Dict:
        """実際のTOC更新処理"""

        # TOCセクション検索
        if not self.toc_pattern.search(content):
            return {'success': False, 'error': 'TOCセクションが見つかりません'}

        # 見出し抽出（内容の詳細情報含む）
        headings = self._extract_headings_with_content(content)

        # 目次生成（行番号情報付き）
        toc_lines = self._generate_toc_lines_with_line_numbers(headings)

        # コンテンツ更新
        updated_content = self._replace_toc_section(content, toc_lines)

        document.write(updated_content)

        return {'success': True, 'headings_count': len(headings)}

    def _update_index_file(self, document: Document) -> Dict:
        """INDEXファイルの更新"""
        content = self._build_index_content(document.path.parent)
        document.write(content)
        return {'success': True}

    def _extract_headings(self, content: str) -> List[Dict]:
        """見出し抽出"""
        headings = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            match = self.heading_pattern.match(line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()

                # TOCや目次自身は除外
                if title != "TOC" and "目次" not in title:
                    headings.append({
                        'level': level,
                        'title': title,
                        'line_num': i + 1
                    })

        return headings
    
    def _extract_headings_with_content(self, content: str) -> List[Dict]:
        """見出し抽出（セクション範囲情報付き）"""
        headings = []
        lines = content.split('\n')
        
        # まず全ての見出しを収集
        heading_positions = []
        for i, line in enumerate(lines):
            match = self.heading_pattern.match(line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                # TOCや目次自身は除外
                if title != "TOC" and "目次" not in title:
                    heading_positions.append({
                        'level': level,
                        'title': title,
                        'line_num': i + 1,
                        'line_index': i
                    })
        
        # 各見出しのセクション範囲を計算
        for i, heading in enumerate(heading_positions):
            start_line = heading['line_num']
            
            # 次の同レベル以上の見出しまでの範囲を見つける
            end_line = len(lines)  # デフォルトは最終行
            for j in range(i + 1, len(heading_positions)):
                if heading_positions[j]['level'] <= heading['level']:
                    end_line = heading_positions[j]['line_num'] - 1
                    break
            
            # 実際の内容がある最後の行を探す（空行を除く）
            actual_end = start_line
            for line_idx in range(heading['line_index'], min(end_line, len(lines))):
                if lines[line_idx].strip():  # 空行でない
                    actual_end = line_idx + 1
            
            headings.append({
                'level': heading['level'],
                'title': heading['title'],
                'start_line': start_line,
                'end_line': actual_end
            })
        
        return headings

    def _generate_toc_lines(self, headings: List[Dict]) -> List[str]:
        """目次行生成"""
        toc_lines = []
        
        for heading in headings:
            indent = '  ' * (heading['level'] - 1)
            # アンカーリンク生成（GitHubスタイル）
            anchor = self._generate_anchor(heading['title'])
            toc_lines.append(f"{indent}- [{heading['title']}](#{anchor})")
        
        return toc_lines
    
    def _generate_toc_lines_with_line_numbers(self, headings: List[Dict]) -> List[str]:
        """目次行生成（行番号情報付き）"""
        toc_lines = []
        
        for heading in headings:
            indent = '  ' * (heading['level'] - 1)
            # アンカーリンク生成（GitHubスタイル）
            anchor = self._generate_anchor(heading['title'])
            
            # 行番号情報を追加
            start = heading['start_line']
            end = heading['end_line']
            line_info = f" (L{start}-{end})"
            
            toc_lines.append(f"{indent}- [{heading['title']}](#{anchor}){line_info}")
        
        return toc_lines

    def _generate_anchor(self, title: str) -> str:
        """GitHubスタイルのアンカー生成"""
        # 小文字化、スペースをハイフンに、特殊文字削除
        anchor = title.lower()
        anchor = re.sub(r'[^\w\s-]', '', anchor)
        anchor = re.sub(r'\s+', '-', anchor)
        return anchor

    def _replace_toc_section(self, content: str, toc_lines: List[str]) -> str:
        """TOCセクション置換"""
        lines = content.split('\n')
        new_lines = []
        in_toc = False
        toc_start = -1
        
        for i, line in enumerate(lines):
            if self.toc_pattern.match(line):
                new_lines.append(line)
                new_lines.extend(toc_lines)
                in_toc = True
                toc_start = i
            elif in_toc:
                # 次の見出しまでスキップ
                if line.startswith('#'):
                    in_toc = False
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        return '\n'.join(new_lines)

    def _build_index_content(self, directory: Path) -> str:
        """INDEXコンテンツ構築"""
        timestamp = self._get_timestamp()
        
        content = f"""# ドキュメントガイド

## 各ドキュメント一覧

{timestamp}

このドキュメントは階層的に整理されています。各カテゴリのINDEXから詳細なドキュメントにアクセスしてください。

## TOC

"""
        
        subdirs = ['rules', 'apis', 'specs', 'logics', 'tasks']
        
        for subdir in subdirs:
            dir_path = directory / subdir
            if dir_path.exists():
                description = self._get_category_description(subdir)
                content += f"### {subdir} - {description}\n"
                content += self._build_directory_section(dir_path, 0)
                content += "\n"
        
        return content

    def _build_directory_section(self, dir_path: Path, depth: int) -> str:
        """ディレクトリセクション構築"""
        section = ""
        indent = "  " * depth
        
        # ファイルリスト
        files = sorted([f for f in dir_path.iterdir() 
                       if f.is_file() and f.suffix in ['.md', '.pu'] 
                       and f.name != 'INDEX.md'])
        
        for file in files:
            title = self._extract_title_from_file(file)
            # docsディレクトリからの相対パスを計算
            docs_dir = Path(__file__).parent.parent.parent.parent.parent / "docs"
            relative_path = file.relative_to(docs_dir)
            icon = ' 🔷' if file.suffix == '.pu' else ''
            section += f"{indent}- [{title}](@vibes/{relative_path}){icon}\n"
        
        # サブディレクトリ
        dirs = sorted([d for d in dir_path.iterdir() 
                      if d.is_dir() and not d.name.startswith('.')])
        
        for subdir in dirs:
            if self._has_documents(subdir):
                dir_title = self._format_directory_name(subdir.name)
                section += f"{indent}- **{dir_title}**\n"
                section += self._build_directory_section(subdir, depth + 1)
        
        return section

    def _extract_title_from_file(self, file_path: Path) -> str:
        """ファイルからタイトル抽出"""
        try:
            if file_path.suffix == '.pu':
                content = file_path.read_text(encoding='utf-8')
                # @startuml の後のタイトルを探す
                match = re.search(r'@startuml\s+(.+)', content)
                if match:
                    return match.group(1).strip()
                return self._format_file_name(file_path.stem)
            else:
                content = file_path.read_text(encoding='utf-8')
                first_line = content.split('\n')[0].strip()
                if first_line.startswith('# '):
                    return first_line[2:]
                return self._format_file_name(file_path.stem)
        except:
            return self._format_file_name(file_path.stem)

    def _format_directory_name(self, dir_name: str) -> str:
        """ディレクトリ名フォーマット"""
        # 番号プレフィックスを除去
        return re.sub(r'^\d+_', '', dir_name)

    def _format_file_name(self, file_name: str) -> str:
        """ファイル名フォーマット"""
        name = re.sub(r'^\d+_', '', file_name)
        name = name.replace('_', ' ')
        return ' '.join(word.capitalize() for word in name.split())

    def _has_documents(self, directory: Path) -> bool:
        """ディレクトリにドキュメントがあるかチェック"""
        for item in directory.rglob('*'):
            if item.is_file() and item.suffix in ['.md', '.pu']:
                return True
        return False

    def _get_category_description(self, category: str) -> str:
        """カテゴリ説明取得"""
        descriptions = {
            'rules': 'プロジェクト規約',
            'apis': '外部連携仕様',
            'logics': 'ビジネスロジック',
            'specs': 'システム仕様',
            'tasks': '開発タスクガイド'
        }
        return descriptions.get(category, '')

    def _get_timestamp(self) -> str:
        """タイムスタンプ生成"""
        from datetime import datetime
        
        now = datetime.now()
        return now.strftime('%Y/%m/%d/%H/%M')