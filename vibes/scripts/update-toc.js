#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class DocTocGenerator {
  constructor(docDir = '../docs') {
    this.docDir = path.resolve(__dirname, docDir);
    this.indexFile = path.join(this.docDir, 'INDEX.md');
  }

  async run() {
    console.log('📚 目次更新スクリプトを実行中...');
    
    if (!fs.existsSync(this.docDir)) {
      console.log(`❌ vibesディレクトリが見つかりません: ${this.docDir}`);
      return;
    }

    await this.generateIndex();
    console.log('✅ 目次更新が完了しました');
  }

  async generateIndex() {
    const content = await this.buildIndexContent();
    fs.writeFileSync(this.indexFile, content, 'utf8');
  }

  async buildIndexContent() {
    const timestamp = new Date().toLocaleString('ja-JP', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Tokyo'
    }).replace(/[\/\s:]/g, '/');

    let content = `# ドキュメントガイド

## 各ドキュメント一覧

${timestamp}
`;

    // 各サブディレクトリの内容を追加
    const subdirs = ['rules', 'apis', 'logics', 'specs', 'tasks'];
    
    for (const subdir of subdirs) {
      const dirPath = path.join(this.docDir, subdir);
      
      if (fs.existsSync(dirPath)) {
        content += await this.buildDirectorySection(subdir, dirPath);
      }
    }

    return content;
  }

  async buildDirectorySection(dirname, dirPath) {
    let section = `- ${dirname}\n`;
    
    try {
      const files = fs.readdirSync(dirPath);
      const mdFiles = files.filter(file => file.endsWith('.md')).sort();
      
      for (const file of mdFiles) {
        const filePath = path.join(dirPath, file);
        const relativePath = path.relative(this.docDir, filePath).replace(/\\/g, '/');
        const title = await this.extractTitleFromFile(filePath);
        
        section += `  - [${title}](@vibes/${relativePath})\n`;
      }
    } catch (error) {
      console.log(`⚠️  ディレクトリ読み込みエラー: ${dirPath} - ${error.message}`);
    }
    
    return section;
  }

  async extractTitleFromFile(filePath) {
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const firstLine = content.split('\n')[0]?.trim();
      
      if (firstLine?.startsWith('# ')) {
        return firstLine.substring(2);
      } else {
        const basename = path.basename(filePath, '.md');
        return basename.replace(/_/g, ' ').split(' ')
          .map(word => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ');
      }
    } catch (error) {
      console.log(`⚠️  ファイル読み込みエラー: ${filePath} - ${error.message}`);
      return path.basename(filePath, '.md');
    }
  }
}

// メイン実行
async function main() {
  const docDir = process.argv[2] || '../docs';
  const generator = new DocTocGenerator(docDir);
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