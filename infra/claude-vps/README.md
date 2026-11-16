# claude-vps — сервер с ИИ (132.243.127.33, FirstVDS)

Claude Code + мост Телеграма (@pmkpark_app), Qdrant-память, Obsidian Sync, публикация проектов pmkpark.ru.
Сервер не в docker-стеке завода — здесь только то, что ставится на него руками.

## Бэкап в Яндекс (с 16.11.2026)
- `backup-claude-vps.sh` → `/usr/local/sbin/backup-claude-vps`, cron root `40 4 * * *` (время сервера +10).
- `backup-check-claude-vps.sh` → `/usr/local/sbin/backup-check-claude-vps`, cron `0 9 * * *`: молчит, если выгрузка
  свежее 26 ч, иначе пишет Антону через бота моста.
- Бакет `pmk-claude-vps-backup` (15 ГБ, версии, `daily/` хранится 30 дней), сервисный аккаунт
  `claude-vps-backup-writer` — `storage.uploader` ТОЛЬКО на этот бакет (бакет Odoo/сайта/1С ему закрыт, удалять нельзя).
- Ключ: `/root/.yc-backup.env` (600). Пароль шифрования: `/root/.backup-passphrase` + у Антона в менеджере паролей
  (свой, не как у pmk-main).
- Архив ≈120 МБ/ночь: без Claude Code, моделей речи, Python/Node-окружений — они ставятся заново.

Восстановление: см. шапку `backup-claude-vps.sh`.
