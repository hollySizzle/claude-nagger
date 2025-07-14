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
      const category = options.category || await this.selectCategory();
      const filename = options.filename || await this.inputFilename();
      const title = options.title || await this.inputTitle();
      
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

オプション:
  -c, --category <category>    ドキュメントカテゴリ (${Object.keys(DocumentGenerator.CATEGORIES).join(', ')})
  -f, --filename <filename>    ファイル名（拡張子なし）
  -t, --title <title>          ドキュメントタイトル
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
    const content = this.buildDocumentTemplate(title, category);
    await fs.writeFile(filePath, content, 'utf8');
  }

  buildDocumentTemplate(title, category) {
    const timestamp = new Date().toLocaleDateString('ja-JP');
    
    switch (category) {
      case 'rules':
        return this.buildRulesTemplate(title);
      case 'specs':
        return this.buildSpecsTemplate(title);
      case 'tasks':
        return this.buildTasksTemplate(title);
      case 'logics':
        return this.buildLogicsTemplate(title);
      case 'apis':
        return this.buildApisTemplate(title);
      case 'temps':
        return this.buildTempsTemplate(title, timestamp);
      default:
        return this.buildGenericTemplate(title);
    }
  }

  buildRulesTemplate(title) {
    return `# ${title}

## 目次

- [1. 概要](#1-概要)
- [2. 基本原則](#2-基本原則)
- [3. 詳細規約](#3-詳細規約)
- [4. 適用例](#4-適用例)

## 1. 概要

### 1.1 目的

[規約の目的を記載]

### 1.2 適用範囲

[適用範囲を記載]

## 2. 基本原則

### 2.1 [原則1]

[原則の説明]

### 2.2 [原則2]

[原則の説明]

## 3. 詳細規約

### 3.1 [詳細項目1]

[詳細規約の内容]

## 4. 適用例

### 4.1 推奨パターン

\`\`\`
[コード例]
\`\`\`

### 4.2 非推奨パターン

\`\`\`
[避けるべきパターン]
\`\`\`

## 関連ドキュメント

- [関連規約1](@vibes/docs/rules/example.md)
- [関連規約2](@vibes/docs/rules/example2.md)`;
  }

  buildTasksTemplate(title) {
    return `# ${title}

## 目次

- [1. 概要](#1-概要)
- [2. 事前準備](#2-事前準備)
- [3. 実行手順](#3-実行手順)
- [4. トラブルシューティング](#4-トラブルシューティング)

## 1. 概要

### 1.1 目的

[タスクの目的を記載]

### 1.2 前提条件

[必要な前提条件を記載]

## 2. 事前準備

### 2.1 必要な情報

- [必要な情報1]
- [必要な情報2]

### 2.2 事前確認事項

- [ ] [確認事項1]
- [ ] [確認事項2]

## 3. 実行手順

### 3.1 手順概要

[手順の概要を記載]

### 3.2 詳細手順

#### ステップ1: [ステップ名]

[具体的な実行内容]

\`\`\`bash
# コマンド例
command --option value
\`\`\`

#### ステップ2: [ステップ名]

[具体的な実行内容]

## 4. トラブルシューティング

### 4.1 [よくある問題1]

**症状**: [問題の症状]
**原因**: [問題の原因]  
**対処法**: [具体的な対処法]

## 関連ドキュメント

- [関連ガイド1](@vibes/docs/tasks/example.md)
- [関連仕様書](@vibes/docs/specs/example.md)`;
  }

  buildSpecsTemplate(title) {
    return `# ${title}

## 目次

- [1. 概要](#1-概要)
- [2. 仕様詳細](#2-仕様詳細)
- [3. 実装例](#3-実装例)
- [4. 運用・保守](#4-運用保守)

## 1. 概要

### 1.1 目的

[仕様の目的を記載]

### 1.2 位置づけ

- **機能分類**: [機能の分類]
- **対象範囲**: [適用範囲]
- **依存関係**: [他システムとの関係]

## 2. 仕様詳細

### 2.1 [仕様項目1]

[詳細仕様の説明]

### 2.2 [仕様項目2]

[詳細仕様の説明]

## 3. 実装例

### 3.1 基本実装

\`\`\`
[実装コード例]
\`\`\`

### 3.2 応用実装

\`\`\`
[応用コード例]
\`\`\`

## 4. 運用・保守

### 4.1 監視項目

[監視すべき項目]

### 4.2 メンテナンス

[定期メンテナンス内容]

## 関連ドキュメント

- [関連仕様書1](@vibes/docs/specs/example.md)
- [実装ガイド](@vibes/docs/tasks/example.md)`;
  }

  buildLogicsTemplate(title) {
    return `# ${title}

## 目次

- [1. 概要](#1-概要)
- [2. ビジネスルール](#2-ビジネスルール)
- [3. 処理フロー](#3-処理フロー)
- [4. 実装指針](#4-実装指針)

## 1. 概要

### 1.1 業務概要

[業務の概要を記載]

### 1.2 スコープ

[対象範囲を記載]

## 2. ビジネスルール

### 2.1 [ルール1]

[ビジネスルールの詳細]

### 2.2 [ルール2]

[ビジネスルールの詳細]

## 3. 処理フロー

### 3.1 基本フロー

1. [ステップ1]
2. [ステップ2]
3. [ステップ3]

### 3.2 例外フロー

[例外処理の内容]

## 4. 実装指針

### 4.1 実装時の注意点

[実装時に注意すべき点]

### 4.2 テスト観点

[テスト時の観点]

## 関連ドキュメント

- [関連ビジネスロジック](@vibes/docs/logics/example.md)
- [実装ガイド](@vibes/docs/tasks/example.md)`;
  }

  buildApisTemplate(title) {
    return `# ${title}

## 目次

- [1. 概要](#1-概要)
- [2. API仕様](#2-api仕様)
- [3. 認証・認可](#3-認証認可)
- [4. エラーハンドリング](#4-エラーハンドリング)

## 1. 概要

### 1.1 API概要

[APIの概要を記載]

### 1.2 ベースURL

\`\`\`
[本番環境]: https://api.example.com/v1
[開発環境]: https://dev-api.example.com/v1
\`\`\`

## 2. API仕様

### 2.1 [エンドポイント1]

**URL**: \`POST /endpoint\`

**リクエスト**:
\`\`\`json
{
  "parameter1": "value1",
  "parameter2": "value2"
}
\`\`\`

**レスポンス**:
\`\`\`json
{
  "status": "success",
  "data": {
    "result": "value"
  }
}
\`\`\`

## 3. 認証・認可

### 3.1 認証方式

[認証方式の説明]

### 3.2 認可レベル

[必要な権限レベル]

## 4. エラーハンドリング

### 4.1 エラーレスポンス形式

\`\`\`json
{
  "status": "error",
  "error": {
    "code": "ERROR_CODE",
    "message": "エラーメッセージ"
  }
}
\`\`\`

## 関連ドキュメント

- [認証ガイド](@vibes/docs/tasks/authentication_guide.md)
- [API実装例](@vibes/docs/specs/api_implementation.md)`;
  }

  buildTempsTemplate(title, timestamp) {
    return `# ${title}

**作成日**: ${timestamp}
**ステータス**: 進行中
**担当者**: [担当者名]

## 概要

[タスク・課題の概要]

## 目的

[達成したい目標]

## チェックリスト

### Phase 1: [フェーズ名]
- [ ] [タスク1]
- [ ] [タスク2]

### Phase 2: [フェーズ名]
- [ ] [タスク3]
- [ ] [タスク4]

## 進捗メモ

### ${timestamp}
- [進捗内容]

## 参考資料

- [参考ドキュメント1](@vibes/docs/specs/example.md)
- [参考ドキュメント2](@vibes/docs/tasks/example.md)

## 完了基準

- [ ] [完了条件1]
- [ ] [完了条件2]`;
  }

  buildGenericTemplate(title) {
    return `# ${title}

## 目次

- [1. 概要](#1-概要)
- [2. 詳細](#2-詳細)

## 1. 概要

[ドキュメントの概要を記載]

## 2. 詳細

[詳細内容を記載]

## 関連ドキュメント

- [関連ドキュメント1](@vibes/docs/example.md)`;
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