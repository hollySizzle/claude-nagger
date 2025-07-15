#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 環境変数読み込み
function loadEnvFile() {
  const envPath = path.join(__dirname, '../.env');
  
  if (!fs.existsSync(envPath)) {
    return {};
  }
  
  const envContent = fs.readFileSync(envPath, 'utf8');
  const env = {};
  
  envContent.split('\n').forEach(line => {
    const match = line.match(/^([^=]+)=(.*)$/);
    if (match) {
      env[match[1].trim()] = match[2].trim();
    }
  });
  
  return env;
}


// エージェント名生成
function generateAgentName(sessionId) {
  const names = [
    "キヨマツ", "ヤギヌマ", "イタバ", "キタハシ", "イワモリ", "ロッカク", 
    "シモヤマ", "ウニスガ", "タカミチ", "ミサカ", "ダンノ", "コレマツ", 
    "ノナミ", "キリウ", "ユタカ", "マイグマ", "モリミツ", "サカガワ", "キマタ"
  ];
  
  // ハッシュ値生成
  const hash = crypto.createHash('md5').update(sessionId).digest('hex');
  const hashValue = parseInt(hash.substring(0, 8), 16);
  
  const nameIndex = hashValue % names.length;
  const shortId = sessionId.slice(-8);
  
  return `${names[nameIndex]}-${shortId}`;
}

// セッションID取得
function getSessionId() {
  if (process.stdin.isTTY) {
    // stdin がない場合はプロセスIDを使用
    return process.pid.toString();
  }
  
  try {
    // stdin から JSON を読み取り
    const input = fs.readFileSync(0, 'utf8');
    const data = JSON.parse(input);
    return data.session_id || process.pid.toString();
  } catch (error) {
    return process.pid.toString();
  }
}

// Discord メッセージ送信
async function sendDiscordMessage(webhookUrl, message, mentions = [], threadId = null) {
  const body = {
    content: message
  };
  
  // メンション設定
  if (mentions.length > 0) {
    body.allowed_mentions = {
      parse: mentions // "users", "roles", "everyone" を配列で指定
    };
  }
  
  // スレッドIDが指定されている場合はクエリパラメータを追加
  let targetUrl = webhookUrl;
  if (threadId) {
    targetUrl = `${webhookUrl}?thread_id=${threadId}`;
  }
  
  const response = await fetch(targetUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body)
  });
  
  if (!response.ok) {
    const errorText = await response.text();
    console.error(`Response body: ${errorText}`);
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
}

// メイン処理
async function main() {
  try {
    // 環境変数読み込み
    const env = loadEnvFile();
    const webhookUrl = env.DISCORD_WEBHOOK_URL;
    const threadId = env.DISCORD_THREAD_ID;
    const threadName = env.THREAD_NAME || 'general';
    const mentionEveryone = env.DISCORD_MENTION_EVERYONE === 'true'; // @everyone メンション
    
    if (!webhookUrl) {
      console.error('Discord webhook not configured, skipping notification');
      process.exit(0);
    }
    
    // メッセージ取得
    const message = process.argv[2] || 'hello';
    
    // セッションIDとエージェント名生成
    const sessionId = getSessionId();
    const agentName = generateAgentName(sessionId);
    
    // タイムスタンプとフォーマット済みメッセージ作成
    const timestamp = new Date().toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    
    // メンション文字列の構築
    let mentionPrefix = '';
    if (mentionEveryone) {
      mentionPrefix += '@everyone ';
    }
    
    // メッセージフォーマット
    let formattedMessage;
    if (threadId) {
      // スレッドIDが設定されている場合は通常フォーマット
      formattedMessage = `${mentionPrefix}🤖 **${agentName}** [${timestamp}] ${message}`;
    } else {
      // 通常のチャンネルの場合はプレフィックスを追加
      formattedMessage = `${mentionPrefix}[${threadName.trim()}] 🤖 **${agentName}** [${timestamp}] ${message}`;
    }
    
    // メンション設定
    const mentions = [];
    if (mentionEveryone) mentions.push('everyone');
    
    // Discord送信
    await sendDiscordMessage(webhookUrl, formattedMessage, mentions, threadId);
    console.error(`Message sent to Discord [${agentName}]: ${message}`);
    
  } catch (error) {
    console.error(`Failed to send Discord message: ${error.message}`);
    // フックの実行を妨げないよう exit 0
    process.exit(0);
  }
}

main();