#!/usr/bin/env node

import fs from 'fs-extra';
import path from 'path';
import { Command } from 'commander';
import readline from 'readline';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class DocumentGenerator {
  static CATEGORIES = {
    'rules': '規約類',
    'specs': '技術仕様書',
    'tasks': '定型タスク手順書',
    'logics': 'ビジネスロジック',
    'apis': '外部連携仕様書',
    'temps': '一時ドキュメント'
  };

  constructor(docDir = '../docs') {
    this.docDir = path.resolve(__dirname, docDir);
    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });
  }

  async run(options) {
    console.log('📝 新規ドキュメント生成を開始します...');
    console.log('');
    console.log('📋 参照ドキュメント:');
    console.log('  - ドキュメント作成規約: @vibes/rules/documentation_standards.md');
    console.log('  - ドキュメント作成ガイド: @vibes/tasks/document_creation_guide.md');
    console.log('  - プロジェクト全体のドキュメント: @vibes/INDEX.md');
    console.log('');
    
    try {
      // 必須引数チェック
      if (!options.category || !options.filename || !options.title) {
        console.log('❌ 必須引数が不足しています');
        DocumentGenerator.showHelp();
        process.exit(1);
      }
      
      const category = options.category;
      let filename = options.filename;
      const title = options.title;
      
      // tempsカテゴリの場合はタイムスタンププレフィックスを追加
      if (category === 'temps') {
        const now = new Date();
        const timestamp = `${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}_`;
        filename = timestamp + filename;
      }
      
      const filePath = path.join(this.docDir, category, `${filename}.md`);
      
      if (await fs.pathExists(filePath)) {
        console.log(`❌ ファイルが既に存在します: ${filePath}`);
        return;
      }
      
      await this.ensureDirectoryExists(path.dirname(filePath));
      await this.createDocument(filePath, title, category);
      
      console.log(`✅ ドキュメントを作成しました: ${filePath}`);
      console.log('📝 次のステップ: 内容を編集後、目次を更新してください');
      console.log('   npm run update-toc');
    } finally {
      this.rl.close();
    }
  }

  static showHelp() {
    console.log(`📖 ドキュメント生成ツール

使用方法:
  node generate-document.js [options]
  npm run generate-doc [-- options]

必須オプション:
  -c, --category <category>    ドキュメントカテゴリ (${Object.keys(DocumentGenerator.CATEGORIES).join(', ')})
  -f, --filename <filename>    ファイル名（拡張子なし）
  -t, --title <title>          ドキュメントタイトル

その他:
  -h, --help                   このヘルプを表示

例:
  node generate-document.js -c tasks -f user_guide -t "ユーザーガイド"
  npm run generate-doc -- -c specs -f api_spec -t "API仕様書"

カテゴリ:
${Object.entries(DocumentGenerator.CATEGORIES)
  .map(([key, desc]) => `  ${key.padEnd(8)} - ${desc}`)
  .join('\n')}

📋 参照ドキュメント:
  - ドキュメント作成規約: @vibes/rules/documentation_standards.md
  - ドキュメント作成ガイド: @vibes/tasks/document_creation_guide.md
  - プロジェクト全体のドキュメント: @vibes/INDEX.md`);
  }

  async selectCategory() {
    console.log('\n📂 ドキュメントカテゴリを選択してください:');
    const categories = Object.entries(DocumentGenerator.CATEGORIES);
    
    categories.forEach(([key, desc], index) => {
      console.log(`  ${index + 1}. ${key} (${desc})`);
    });
    
    const answer = await this.question(`選択 (1-${categories.length}): `);
    const choice = parseInt(answer);
    
    if (choice >= 1 && choice <= categories.length) {
      return categories[choice - 1][0];
    } else {
      console.log('❌ 無効な選択です');
      process.exit(1);
    }
  }

  async inputFilename() {
    const answer = await this.question('📄 ファイル名を入力してください（拡張子なし）: ');
    const filename = answer.trim();
    
    if (!filename) {
      console.log('❌ ファイル名は必須です');
      process.exit(1);
    }
    
    // ファイル名を正規化
    return filename.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  }

  async inputTitle() {
    const answer = await this.question('📝 ドキュメントタイトルを入力してください: ');
    const title = answer.trim();
    
    if (!title) {
      console.log('❌ タイトルは必須です');
      process.exit(1);
    }
    
    return title;
  }

  async question(prompt) {
    return new Promise((resolve) => {
      this.rl.question(prompt, resolve);
    });
  }

  async ensureDirectoryExists(dir) {
    await fs.ensureDir(dir);
  }

  async createDocument(filePath, title, category) {
    // まずテンプレートファイルを探す
    const templatePath = path.join(this.docDir, category, '_template.md');
    
    if (!await fs.pathExists(templatePath)) {
      console.log(`❌ テンプレートファイルが存在しません: ${templatePath}`);
      console.log(`📝 先に ${category}/_template.md ファイルを作成してください`);
      process.exit(1);
    }
    
    console.log(`📄 テンプレートファイルを使用: ${templatePath}`);
    let content = await fs.readFile(templatePath, 'utf8');
    
    // タイトルをプレースホルダーに置換
    content = content.replace(/\[TODO: [^\]]+\]/g, title);
    
    // 日付を置換（tempsカテゴリ用）
    if (category === 'temps') {
      const timestamp = new Date().toLocaleDateString('ja-JP');
      content = content.replace(/\${timestamp}/g, timestamp);
    }
    
    await fs.writeFile(filePath, content, 'utf8');
  }
}

// メイン実行
async function main() {
  const program = new Command();
  
  program
    .name('generate-document')
    .description('新規ドキュメント生成ツール')
    .version('1.0.0')
    .option('-c, --category <category>', 'ドキュメントカテゴリ')
    .option('-f, --filename <filename>', 'ファイル名')
    .option('-t, --title <title>', 'ドキュメントタイトル')
    .helpOption('-h, --help', 'ヘルプを表示')
    .on('--help', () => {
      DocumentGenerator.showHelp();
    });

  program.parse();
  
  const options = program.opts();
  
  if (program.args.includes('--help') || program.args.includes('-h')) {
    DocumentGenerator.showHelp();
    return;
  }
  
  const generator = new DocumentGenerator('../docs');
  
  await generator.run(options);
}

// スクリプトが直接実行された場合のみmain()を呼び出し
const isMainModule = import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('generate-document.js');
if (isMainModule) {
  main().catch(error => {
    console.error('❌ エラーが発生しました:', error);
    process.exit(1);
  });
}