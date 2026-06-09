# n8n Service

Workflow orchestration — connects ERPNext with Email, Telegram, AI Assistant.

## Workflows

- Email → Lead (IMAP polling every 5 min)
- Quotation approval via Telegram
- Material request notifications
- Production status updates
- Health check monitoring

## Local Setup

n8n runs via Docker (see `infra/docker-compose.yml`).
Workflows are exported to `workflows/` as JSON and imported on startup.

## Structure

```
n8n/
├── workflows/        # exported workflow JSON files
├── credentials/      # credential templates (no secrets)
└── README.md
```
