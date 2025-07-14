#!/usr/bin/env node

import fs from 'fs-extra';
import path from 'path';
import { glob } from 'glob';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class DocReferenceChecker {
  constructor(docDir = '../docs') {
    this.docDir = path.resolve(__dirname, docDir);
    this.errors = [];
    this.warnings = [];
  }

  async run() {
    console.log('🔍 ドキュメント参照チェックを実行中...');
    
    if (!await fs.pathExists(this.docDir)) {
      console.log(`❌ vibesディレクトリが見つかりません: ${this.docDir}`);
      return;
    }

    await this.checkAllReferences();
    this.printResults();
  }

  async checkAllReferences() {
    try {
      const pattern = path.join(this.docDir, '**', '*.md').replace(/\\/g, '/');
      const mdFiles = await glob(pattern);
      
      for (const filePath of mdFiles) {
        await this.checkFileReferences(filePath);
      }
    } catch (error) {
      this.errors.push(`グロブパターンエラー: ${error.message}`);
    }
  }

  async checkFileReferences(filePath) {
    try {
      const content = await fs.readFile(filePath, 'utf8');
      const relativePath = path.relative(this.docDir, filePath);
      
      // @vibes/記法の参照をチェック
      const docReferences = content.match(/@vibes\/([^\s\)]+\.md)/g);
      if (docReferences) {
        for (const reference of docReferences) {
          const referencedFile = reference.replace('@vibes/', '');
          const fullPath = path.join(this.docDir, referencedFile);
          
          if (!await fs.pathExists(fullPath)) {
            this.errors.push(`${relativePath}: 参照先が存在しません - ${reference}`);
          }
        }
      }
      
      // 相対パス参照（禁止パターン）をチェック
      const relativeReferences = content.match(/\[.*?\]\((?:\.\.?\/[^\)]+|[^@\s][^\)]*\.md)\)/g);
      if (relativeReferences) {
        for (const reference of relativeReferences) {
          this.warnings.push(`${relativePath}: 非推奨の相対パス参照 - ${reference}`);
        }
      }
      
    } catch (error) {
      const relativePath = path.relative(this.docDir, filePath);
      this.errors.push(`${relativePath}: ファイル読み込みエラー - ${error.message}`);
    }
  }

  printResults() {
    console.log('\n📊 チェック結果:');
    
    if (this.errors.length === 0 && this.warnings.length === 0) {
      console.log('✅ エラーや警告はありませんでした');
      return;
    }
    
    if (this.errors.length > 0) {
      console.log('\n❌ エラー:');
      this.errors.forEach(error => console.log(`  ${error}`));
    }
    
    if (this.warnings.length > 0) {
      console.log('\n⚠️  警告:');
      this.warnings.forEach(warning => console.log(`  ${warning}`));
    }
    
    console.log('\n推奨事項:');
    console.log('  - 相対パス参照は @vibes/記法に変更してください');
    console.log('  - 存在しないファイルへの参照は修正または削除してください');
  }
}

// メイン実行
async function main() {
  const docDir = process.argv[2] || '../docs';
  const checker = new DocReferenceChecker(docDir);
  await checker.run();
}

// スクリプトが直接実行された場合のみmain()を呼び出し
const isMainModule = import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('check-doc-references.js');
if (isMainModule) {
  main().catch(error => {
    console.error('❌ エラーが発生しました:', error);
    process.exit(1);
  });
}