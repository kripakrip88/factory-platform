#!/bin/bash
# Безопасное обновление ERPNext
# Использование: bash services/erp/scripts/update.sh

set -e
COMPOSE="docker compose -f /opt/factory-platform/services/erp/docker-compose.yml"

echo "🔒 Шаг 1: Бэкап перед обновлением..."
bash /opt/factory-platform/services/erp/scripts/backup.sh

echo "⬇️  Шаг 2: Обновление образов..."
$COMPOSE pull

echo "🔄 Шаг 3: Перезапуск контейнеров..."
$COMPOSE up -d

echo "⏳ Шаг 4: Ожидание готовности (60 сек)..."
sleep 60

echo "🔧 Шаг 5: Накат миграций ERPNext..."
$COMPOSE exec -T backend bench --site erp.localhost migrate

echo "⚙️  Шаг 6: Накат кастомных настроек..."
$COMPOSE cp /opt/factory-platform/services/erp/setup/setup_all.py backend:/tmp/setup_all.py
$COMPOSE exec -T backend bench --site erp.localhost execute /tmp/setup_all.py

echo "🧹 Шаг 7: Очистка кэша..."
$COMPOSE exec -T backend bench --site erp.localhost clear-cache

echo "✅ Обновление завершено!"
