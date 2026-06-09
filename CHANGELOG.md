# Changelog

## 2026-06-09

### factory-platform
- [feat] инициализация монорепозитория — структура сервисов, Docker Compose, Nginx, GitHub Actions CI/CD
- [feat] services/telegram-bot — базовый скелет с командами /start, /help
- [feat] services/n8n — структура для workflow JSON
- [feat] services/erp — README-заглушка для ERPNext
- [config] infra/docker-compose.yml — все сервисы (postgres, redis, ai-assistant, n8n, telegram-bot, nginx)
- [config] .github/workflows — CI на PR, deploy workflows per service (ai-assistant, telegram-bot)
