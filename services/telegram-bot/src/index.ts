import TelegramBot from 'node-telegram-bot-api';
import * as dotenv from 'dotenv';

dotenv.config();

const token = process.env.TELEGRAM_BOT_TOKEN;
if (!token) throw new Error('TELEGRAM_BOT_TOKEN is required');

const bot = new TelegramBot(token, { polling: true });

bot.onText(/\/start/, (msg) => {
  bot.sendMessage(msg.chat.id, 'Factory Platform Bot ready. Use /help for commands.');
});

bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id, [
    '/leads — latest leads',
    '/orders — active work orders',
    '/status <id> — document details',
    '/approve <id> — approve quotation (Director)',
    '/reject <id> <reason> — reject quotation (Director)',
  ].join('\n'));
});

console.log('Telegram bot started');
