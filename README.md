# Factory Platform

Unified digital platform for metal construction factory management.

## Services

| Service | Stack | Description |
|---------|-------|-------------|
| `services/erp` | ERPNext (Python/Frappe) | Core ERP — CRM, Quotation, BOM, Production |
| `services/ai-assistant` | NestJS + TypeScript | OCR, AI extraction (Claude API), document parsing |
| `services/n8n` | n8n (Node.js) | Orchestration — Email, Telegram, workflow automation |
| `services/telegram-bot` | Node.js | Employee notifications and commands |

## Architecture

```
Email / Telegram / Web
        ↓
   n8n (orchestrator)
        ↓
  ERPNext (core ERP) ←→ AI Assistant (extraction)
        ↓
   Telegram Bot (notifications)
```

## Quick Start

```bash
# Copy env template
cp .env.example .env

# Start all services
docker compose -f infra/docker-compose.yml up -d

# Or start individual service
docker compose -f infra/docker-compose.yml up erp -d
```

## Environments

| Environment | Branch | URL |
|-------------|--------|-----|
| Production | `main` | TBD |
| Staging | `develop` | TBD |

## Deployment

Push to `develop` → auto-deploy to staging.
After QA: PR `develop` → `main` → auto-deploy to production.

## Documentation

See [docs/](docs/) for full architecture, roadmap, and API references.
