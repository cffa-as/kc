'use strict';

const readline = require('node:readline');
const { WSClient } = require('@wecom/aibot-node-sdk');

let client = null;
let commandQueue = Promise.resolve();

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

const logger = {
  debug: () => {},
  info: (...args) => console.error('[info]', ...args),
  warn: (...args) => console.error('[warn]', ...args),
  error: (...args) => console.error('[error]', ...args),
};

async function start(command) {
  if (client) {
    return;
  }
  client = new WSClient({
    botId: command.botId,
    secret: command.secret,
    maxReconnectAttempts: -1,
    logger,
  });
  client.on('authenticated', () => emit({ type: 'status', message: '已连接并认证' }));
  client.on('disconnected', (reason) => emit({ type: 'status', message: `连接断开：${reason}` }));
  client.on('reconnecting', (attempt) => emit({ type: 'status', message: `正在第 ${attempt} 次重连` }));
  client.on('error', (error) => emit({ type: 'error', message: error.message }));
  client.on('message.text', (frame) => {
    const body = frame.body || {};
    const chatId = body.chatid || body.from?.userid || '';
    emit({
      type: 'message',
      chatId,
      chatType: body.chattype || 'single',
      userId: body.from?.userid || '',
      content: body.text?.content || '',
    });
  });
  client.connect();
}

async function handle(command) {
  if (command.type === 'start') {
    await start(command);
  } else if (command.type === 'reply') {
    if (!client || !client.isConnected) {
      throw new Error('WeCom client is not connected');
    }
    await client.sendMessage(command.chatId, {
      msgtype: 'markdown',
      markdown: { content: command.content },
    });
    emit({ type: 'reply_sent' });
  } else if (command.type === 'stop') {
    if (client) {
      client.disconnect();
    }
    process.exit(0);
  }
}

const input = readline.createInterface({ input: process.stdin, terminal: false });
input.on('line', (line) => {
  commandQueue = commandQueue
    .then(() => handle(JSON.parse(line)))
    .catch((error) => emit({ type: 'error', message: error.message }));
});

process.on('SIGTERM', () => {
  if (client) {
    client.disconnect();
  }
  process.exit(0);
});
