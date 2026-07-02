# Привязка ERP/n8n к домену erppark.ru

Три сервиса на одном сервере `155.212.143.179`, фронт — infra-nginx (:80/:443):

| Домен | Сервис | Апстрим |
|-------|--------|---------|
| `erppark.ru` (+ `www` → 301) | ПРОД ERP (`main`) | `host.docker.internal:8080` |
| `d.erppark.ru` | STAGING ERP (`develop`) | `host.docker.internal:8081` |
| `n8n.erppark.ru` | n8n | `n8n:5678` |

## Почему фазами
Nginx не стартует, если в конфиге есть `ssl_certificate` на несуществующий файл →
это уронило бы и n8n. Поэтому TLS включаем ТОЛЬКО после выпуска сертов.

## Фаза 0 — DNS (в панели Beget)
A-записи на `155.212.143.179`: `@`, `www`, `d`, `n8n`. Убрать старые `5.35.92.112`.
Проверка распространения: `dig +short erppark.ru` (ждём `155.212.143.179`).

## Фаза A — HTTP + ACME (безопасно, без TLS)
Мержим ветку → `deploy-infra` поднимает nginx с HTTP-проксированием и путём
`/.well-known/acme-challenge/`. nginx стартует гарантированно (нет ссылок на серты).
Проверка: `http://erppark.ru/` открывает ERP, `http://n8n.erppark.ru/` — n8n.

## Фаза 2 — выпуск сертов (один раз, на сервере)
```bash
DRY_RUN=1 bash /opt/factory-platform/infra/scripts/issue-certs.sh   # проверка
bash /opt/factory-platform/infra/scripts/issue-certs.sh             # реальный выпуск
```

## Фаза B — включить TLS
Заменить `nginx.conf` на TLS-вариант (443 + редирект 80→443 + `www`→apex 301),
добавить certbot-сервис автопродления в `docker-compose.yml`. Деплой → `nginx -t` → reload.

## Фаза 4 — host_name + n8n на поддомен
- ERP: `site_config.json` prod → `host_name: https://erppark.ru`; staging → `https://d.erppark.ru`.
- n8n env: `N8N_HOST=n8n.erppark.ru`, `N8N_PROTOCOL=https`, `WEBHOOK_URL=https://n8n.erppark.ru/`,
  `N8N_SECURE_COOKIE=true`; убрать `/n8n/` из nginx.

## Откат
Вернуть прежний `infra/nginx/nginx.conf` (только `_`/`/n8n/`) + `docker-compose.yml`,
`deploy-infra`. Серты/тома не мешают. Прод ERP (:8080) и n8n продолжают работать —
домены просто перестанут отвечать, прямой доступ по IP:порт сохранится.
