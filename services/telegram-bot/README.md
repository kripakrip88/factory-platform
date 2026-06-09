# Telegram Bot Service

Employee-facing bot for notifications and quick commands.

## Commands

| Command | Role | Description |
|---------|------|-------------|
| `/leads` | Manager+ | Show 10 latest leads |
| `/orders` | All | Active work orders |
| `/status <id>` | All | Document details |
| `/approve <id>` | Director | Approve quotation |
| `/reject <id> <reason>` | Director | Reject quotation |

## Notifications

- New lead (with AI confidence score)
- Quotation pending approval (inline approve/reject buttons)
- Work order completed
- Material shortage alert
- System errors

## Stack

Node.js + `node-telegram-bot-api`

## Setup

```bash
cd services/telegram-bot
npm install
cp ../../.env.example .env   # fill TELEGRAM_BOT_TOKEN
npm run dev
```
