#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class DocTocGenerator {
  constructor(docDir = '../docs', options = {}) {
    this.docDir = path.resolve(__dirname, docDir);
    this.options = {
      hierarchical: true,  // デフォルトで階層的INDEX生成
      flat: false,         // フラットモード（従来の動作）
      dryRun: false,
      targetPath: null,
      ...options
    };
    
    // カテゴリごとの説明
    this.categoryDescriptions = {
      'rules': 'プロジェクト規約',
      'apis': '外部連携仕様',
      'logics': 'ビジネスロジック',
      'specs': 'システム仕様',
      'tasks': '開発タスクガイド'
    };
    
    // 生成されたINDEXファイルを追跡
    this.generatedIndexes = new Set();
  }

  async run() {
    console.log('📚 目次更新スクリプトを実行中...');
    
    if (!fs.existsSync(this.docDir)) {
      console.log(`❌ vibesディレクトリが見つかりません: ${this.docDir}`);
      return;
    }

    if (this.options.flat) {
      console.log('📝 フラットモードで実行中...');
      await this.generateRootIndex();
    } else {
      console.log('🔄 階層的INDEX生成モードで実行中...');
      await this.generateHierarchicalIndexes();
    }
    
    if (this.options.dryRun) {
      console.log('📝 ドライランモード - 実際のファイルは更新されませんでした');
    }
    
    console.log('✅ 目次更新が完了しました');
  }

  // ルートINDEXのみ生成（従来の動作）
  async generateRootIndex() {
    const indexFile = path.join(this.docDir, 'INDEX.md');
    const content = await this.buildRootIndexContent();
    
    if (this.options.dryRun) {
      console.log(`\n📄 ${indexFile} の内容:\n${content}`);
    } else {
      fs.writeFileSync(indexFile, content, 'utf8');
    }
  }

  // 階層的INDEX生成
  async generateHierarchicalIndexes() {
    // 特定パスが指定されている場合
    if (this.options.targetPath) {
      const targetDir = path.join(this.docDir, this.options.targetPath);
      if (fs.existsSync(targetDir)) {
        await this.generateDirectoryIndex(targetDir);
      } else {
        console.log(`❌ 指定されたパスが見つかりません: ${targetDir}`);
        return;
      }
    } else {
      // 全階層を処理
      await this.processDirectory(this.docDir);
    }
    
    // ルートINDEXも更新
    await this.updateRootIndexForHierarchy();
  }

  // ディレクトリを再帰的に処理
  async processDirectory(dirPath) {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    
    // 現在のディレクトリにINDEXが必要か判定
    if (this.shouldHaveIndex(dirPath)) {
      await this.generateDirectoryIndex(dirPath);
    }
    
    // サブディレクトリを処理
    for (const entry of entries) {
      if (entry.isDirectory() && !entry.name.startsWith('.')) {
        const subdirPath = path.join(dirPath, entry.name);
        await this.processDirectory(subdirPath);
      }
    }
  }

  // ディレクトリがINDEXを持つべきか判定
  shouldHaveIndex(dirPath) {
    // ルートディレクトリは常にINDEXを持つ
    if (dirPath === this.docDir) return true;
    
    // 第1階層のディレクトリ（rules, apis, logics, specs, tasks）はINDEXを持たない
    const relativePath = path.relative(this.docDir, dirPath);
    const pathParts = relativePath.split(path.sep).filter(p => p);
    if (pathParts.length === 1 && ['rules', 'apis', 'logics', 'specs', 'tasks', 'temps'].includes(pathParts[0])) {
      return false;
    }
    
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    const docFiles = entries.filter(e => e.isFile() && (e.name.endsWith('.md') || e.name.endsWith('.pu')) && e.name !== 'INDEX.md');
    const subdirs = entries.filter(e => e.isDirectory() && !e.name.startsWith('.'));
    
    // ドキュメントファイルまたはサブディレクトリが1つでもあればINDEXを生成
    return docFiles.length > 0 || subdirs.length > 0;
  }

  // ディレクトリ用のINDEXを生成
  async generateDirectoryIndex(dirPath) {
    const indexFile = path.join(dirPath, 'INDEX.md');
    const relativePath = path.relative(this.docDir, dirPath);
    
    console.log(`📝 生成中: ${relativePath || 'ルート'}/INDEX.md`);
    
    let content = '';
    
    // タイトルとパンくずリスト
    if (dirPath === this.docDir) {
      content = await this.buildRootIndexContent();
    } else {
      const dirName = path.basename(dirPath);
      const title = this.formatDirectoryName(dirName);
      const breadcrumb = this.generateBreadcrumb(dirPath);
      
      content = `# ${title}\n\n${breadcrumb}\n\n`;
      
      // ディレクトリの説明を追加
      const description = await this.getDirectoryDescription(dirPath);
      if (description) {
        content += `## 概要\n\n${description}\n\n`;
      }
      
      // コンテンツ一覧
      content += `## ドキュメント一覧\n\n`;
      content += await this.buildDirectoryContent(dirPath);
    }
    
    if (this.options.dryRun) {
      console.log(`\n📄 ${indexFile} の内容:\n${content}\n`);
    } else {
      fs.writeFileSync(indexFile, content, 'utf8');
      this.generatedIndexes.add(indexFile);
    }
  }

  // パンくずリスト生成
  generateBreadcrumb(currentPath) {
    const relativePath = path.relative(this.docDir, currentPath);
    const parts = relativePath.split(path.sep).filter(p => p);
    
    let breadcrumb = '[📚 ドキュメントガイド](@vibes/INDEX.md)';
    let currentRelPath = '';
    
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      currentRelPath = currentRelPath ? `${currentRelPath}/${part}` : part;
      const title = this.formatDirectoryName(part);
      
      if (i === parts.length - 1) {
        breadcrumb += ` > **${title}**`;
      } else {
        breadcrumb += ` > [${title}](@vibes/${currentRelPath}/INDEX.md)`;
      }
    }
    
    return breadcrumb;
  }

  // ディレクトリの説明を取得
  async getDirectoryDescription(dirPath) {
    const dirName = path.basename(dirPath);
    const parentDirName = path.basename(path.dirname(dirPath));
    
    // カテゴリ説明
    if (this.categoryDescriptions[dirName]) {
      return this.categoryDescriptions[dirName];
    }
    
    // 特定のパターンに基づく説明
    if (dirName.match(/^\d+_/)) {
      const cleanName = this.formatDirectoryName(dirName);
      return `${cleanName}に関するドキュメント`;
    }
    
    return null;
  }

  // ディレクトリ内容を構築
  async buildDirectoryContent(dirPath) {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    let content = '';
    
    // ファイルとディレクトリを分離
    const files = entries.filter(e => e.isFile() && (e.name.endsWith('.md') || e.name.endsWith('.pu')) && e.name !== 'INDEX.md');
    const dirs = entries.filter(e => e.isDirectory() && !e.name.startsWith('.'));
    
    // サブディレクトリがある場合
    if (dirs.length > 0) {
      content += '### サブカテゴリ\n\n';
      for (const dir of dirs.sort((a, b) => a.name.localeCompare(b.name))) {
        const subdirPath = path.join(dirPath, dir.name);
        const hasIndex = fs.existsSync(path.join(subdirPath, 'INDEX.md')) || this.shouldHaveIndex(subdirPath);
        const title = this.formatDirectoryName(dir.name);
        const relativePath = path.relative(this.docDir, subdirPath);
        
        if (hasIndex) {
          content += `- 📁 [${title}](@vibes/${relativePath}/INDEX.md)\n`;
        } else {
          content += `- 📁 **${title}**\n`;
          // 直接ファイルをリスト
          const subdirContent = await this.listDirectoryFiles(subdirPath, 1);
          if (subdirContent) {
            content += subdirContent;
          }
        }
      }
      content += '\n';
    }
    
    // ファイルがある場合
    if (files.length > 0) {
      content += '### ドキュメント\n\n';
      for (const file of files.sort((a, b) => a.name.localeCompare(b.name))) {
        const filePath = path.join(dirPath, file.name);
        const relativePath = path.relative(this.docDir, filePath).replace(/\\/g, '/');
        const title = await this.extractTitleFromFile(filePath);
        const icon = file.name.endsWith('.pu') ? ' 🔷' : '';
        
        content += `- [${title}](@vibes/${relativePath})${icon}\n`;
      }
    }
    
    return content;
  }

  // ディレクトリ内のファイルをリスト（インデント付き）
  async listDirectoryFiles(dirPath, depth) {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    const files = entries.filter(e => e.isFile() && (e.name.endsWith('.md') || e.name.endsWith('.pu')) && e.name !== 'INDEX.md');
    
    if (files.length === 0) return '';
    
    let content = '';
    const indent = '  '.repeat(depth);
    
    for (const file of files.sort((a, b) => a.name.localeCompare(b.name))) {
      const filePath = path.join(dirPath, file.name);
      const relativePath = path.relative(this.docDir, filePath).replace(/\\/g, '/');
      const title = await this.extractTitleFromFile(filePath);
      const icon = file.name.endsWith('.pu') ? ' 🔷' : '';
      
      content += `${indent}- [${title}](@vibes/${relativePath})${icon}\n`;
    }
    
    return content;
  }

  // 階層的INDEX用のルートINDEX更新（全階層INDEX表示版）
  async updateRootIndexForHierarchy() {
    const indexFile = path.join(this.docDir, 'INDEX.md');
    const timestamp = this.getTimestamp();
    
    let content = `# ドキュメントガイド

## 各ドキュメント一覧

${timestamp}

このドキュメントは階層的に整理されています。各カテゴリのINDEXから詳細なドキュメントにアクセスしてください。

`;

    const subdirs = ['rules', 'apis', 'specs', 'logics', 'tasks'];
    
    // 各カテゴリの階層構造を表示
    for (const subdir of subdirs) {
      const dirPath = path.join(this.docDir, subdir);
      if (fs.existsSync(dirPath)) {
        const description = this.categoryDescriptions[subdir] || '';
        content += `### ${subdir} - ${description}\n`;
        content += await this.buildHierarchicalSection(dirPath, 0);
        content += '\n';
      }
    }
    
    if (this.options.dryRun) {
      console.log(`\n📄 ${indexFile} の内容:\n${content}`);
    } else {
      fs.writeFileSync(indexFile, content, 'utf8');
    }
  }

  // 階層的セクション構築（全階層のINDEXを表示）
  async buildHierarchicalSection(dirPath, depth) {
    let section = '';
    const indent = '  '.repeat(depth);
    
    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      const files = entries.filter(e => e.isFile() && (e.name.endsWith('.md') || e.name.endsWith('.pu')) && e.name !== 'INDEX.md');
      const dirs = entries.filter(e => e.isDirectory() && !e.name.startsWith('.'));
      
      // ファイルを表示
      for (const file of files.sort((a, b) => a.name.localeCompare(b.name))) {
        const filePath = path.join(dirPath, file.name);
        const relativePath = path.relative(this.docDir, filePath).replace(/\\/g, '/');
        const title = await this.extractTitleFromFile(filePath);
        const icon = file.name.endsWith('.pu') ? ' 🔷' : '';
        
        section += `${indent}- [${title}](@vibes/${relativePath})${icon}\n`;
      }
      
      // サブディレクトリを処理
      for (const dir of dirs.sort((a, b) => a.name.localeCompare(b.name))) {
        const subdirPath = path.join(dirPath, dir.name);
        const hasIndex = this.shouldHaveIndex(subdirPath);
        const hasFiles = (await this.getDirectoryFiles(subdirPath)).length > 0;
        
        if (hasFiles) {
          const dirTitle = this.formatDirectoryName(dir.name);
          
          if (hasIndex) {
            // INDEXがある場合はリンクを表示
            const relativePath = path.relative(this.docDir, subdirPath);
            section += `${indent}- [${dirTitle}](@vibes/${relativePath}/INDEX.md)\n`;
          } else {
            // INDEXがない場合は太字で表示
            section += `${indent}- **${dirTitle}**\n`;
          }
          
          // INDEXがない場合のみ再帰的にサブディレクトリを処理
          if (!hasIndex) {
            const subContent = await this.buildHierarchicalSection(subdirPath, depth + 1);
            if (subContent) {
              section += subContent;
            }
          }
        }
      }
    } catch (error) {
      console.log(`⚠️  ディレクトリ読み込みエラー: ${dirPath} - ${error.message}`);
    }
    
    return section;
  }

  // 従来のルートINDEX生成
  async buildRootIndexContent() {
    const timestamp = this.getTimestamp();

    let content = `# ドキュメントガイド

## 各ドキュメント一覧

${timestamp}
`;

    const subdirs = ['rules', 'apis', 'specs', 'logics', 'tasks'];
    
    for (const subdir of subdirs) {
      const dirPath = path.join(this.docDir, subdir);
      
      if (fs.existsSync(dirPath)) {
        const description = this.categoryDescriptions[subdir] || '';
        content += `\n### ${subdir}${description ? ' - ' + description : ''}\n`;
        content += await this.buildDirectorySection(subdir, dirPath, 0);
      }
    }

    return content;
  }

  // タイムスタンプ生成
  getTimestamp() {
    return new Date().toLocaleString('ja-JP', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Tokyo'
    }).replace(/[\/\s:]/g, '/');
  }

  async buildDirectorySection(dirname, dirPath, depth = 0) {
    let section = '';
    const indent = '  '.repeat(depth);
    
    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      
      // ファイルとディレクトリを分離してソート（INDEX.mdを除外）
      const files = entries.filter(e => e.isFile() && (e.name.endsWith('.md') || e.name.endsWith('.pu')) && e.name !== 'INDEX.md').sort((a, b) => a.name.localeCompare(b.name));
      const dirs = entries.filter(e => e.isDirectory() && !e.name.startsWith('.')).sort((a, b) => a.name.localeCompare(b.name));
      
      // ファイルを先に処理
      for (const file of files) {
        const filePath = path.join(dirPath, file.name);
        const relativePath = path.relative(this.docDir, filePath).replace(/\\/g, '/');
        const title = await this.extractTitleFromFile(filePath);
        const icon = file.name.endsWith('.pu') ? ' 🔷' : '';
        
        section += `${indent}- [${title}](@vibes/${relativePath})${icon}\n`;
      }
      
      // サブディレクトリを処理
      for (const dir of dirs) {
        const subdirPath = path.join(dirPath, dir.name);
        const subdirFiles = await this.getDirectoryFiles(subdirPath);
        
        if (subdirFiles.length > 0) {
          // サブディレクトリ名を太字で表示
          section += `${indent}- **${this.formatDirectoryName(dir.name)}**\n`;
          section += await this.buildDirectorySection(dir.name, subdirPath, depth + 1);
        }
      }
    } catch (error) {
      console.log(`⚠️  ディレクトリ読み込みエラー: ${dirPath} - ${error.message}`);
    }
    
    return section;
  }
  
  // ディレクトリ内のファイル数を取得（再帰的）
  async getDirectoryFiles(dirPath) {
    let files = [];
    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      
      for (const entry of entries) {
        if (entry.isFile() && (entry.name.endsWith('.md') || entry.name.endsWith('.pu'))) {
          files.push(entry.name);
        } else if (entry.isDirectory() && !entry.name.startsWith('.')) {
          const subdirFiles = await this.getDirectoryFiles(path.join(dirPath, entry.name));
          files = files.concat(subdirFiles);
        }
      }
    } catch (error) {
      // エラーは無視
    }
    
    return files;
  }
  
  // ディレクトリ名をフォーマット（番号プレフィックスを除去）
  formatDirectoryName(dirName) {
    // 例: "01_集荷依頼作成" → "集荷依頼作成"
    return dirName.replace(/^\d+_/, '');
  }

  async extractTitleFromFile(filePath) {
    try {
      // PlantUMLファイルの場合
      if (filePath.endsWith('.pu')) {
        const content = fs.readFileSync(filePath, 'utf8');
        // @startuml の後のタイトルを探す
        const titleMatch = content.match(/@startuml\s+(.+)/);
        if (titleMatch) {
          return titleMatch[1].trim();
        }
        // タイトルが見つからない場合はファイル名から生成
        const basename = path.basename(filePath, '.pu');
        return this.formatFileName(basename);
      }
      
      // Markdownファイルの場合
      const content = fs.readFileSync(filePath, 'utf8');
      const firstLine = content.split('\n')[0]?.trim();
      
      if (firstLine?.startsWith('# ')) {
        return firstLine.substring(2);
      } else {
        const basename = path.basename(filePath, '.md');
        return this.formatFileName(basename);
      }
    } catch (error) {
      console.log(`⚠️  ファイル読み込みエラー: ${filePath} - ${error.message}`);
      const ext = path.extname(filePath);
      return this.formatFileName(path.basename(filePath, ext));
    }
  }
  
  // ファイル名をフォーマット（番号プレフィックスを除去、アンダースコアをスペースに）
  formatFileName(fileName) {
    return fileName
      .replace(/^\d+_/, '') // 番号プレフィックスを除去
      .replace(/_/g, ' ')   // アンダースコアをスペースに
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }
}

// コマンドライン引数の解析
function parseArgs() {
  const args = process.argv.slice(2);
  const options = {
    hierarchical: true,  // デフォルトで階層的INDEX生成
    flat: false,
    dryRun: false,
    targetPath: null
  };
  
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--flat':
      case '-f':
        options.flat = true;
        options.hierarchical = false;
        break;
      case '--dry-run':
      case '-d':
        options.dryRun = true;
        break;
      case '--path':
      case '-p':
        if (i + 1 < args.length) {
          options.targetPath = args[++i];
        }
        break;
      case '--help':
        console.log(`
使用方法:
  npm run update-toc [オプション]

オプション:
  --flat, -f           フラットモード（階層INDEXを生成しない従来の動作）
  --dry-run, -d        変更内容を表示（実際の更新は行わない）
  --path <path>, -p    特定のパスのみ更新（階層モードのみ）
  --help               このヘルプを表示

デフォルト動作:
  階層的INDEX生成モード（各ディレクトリにINDEX.mdを生成）

例:
  npm run update-toc                           # 階層的INDEX生成（デフォルト）
  npm run update-toc -- --flat                 # フラットモード（従来の動作）
  npm run update-toc -- --path logics/13_集荷  # 特定パスのみ更新
  npm run update-toc -- --dry-run             # ドライラン
`);
        process.exit(0);
    }
  }
  
  return options;
}

// メイン実行
async function main() {
  const options = parseArgs();
  const docDir = '../docs';
  const generator = new DocTocGenerator(docDir, options);
  await generator.run();
}

// スクリプトが直接実行された場合のみmain()を呼び出し
const isMainModule = import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('update-toc.js');
if (isMainModule) {
  main().catch(error => {
    console.error('❌ エラーが発生しました:', error);
    process.exit(1);
  });
}