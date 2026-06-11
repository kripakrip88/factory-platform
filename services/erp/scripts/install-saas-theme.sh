#!/bin/bash
# Установка saas_theme на существующий сайт erp.localhost
# Запускать ПОСЛЕ того как новый образ собран и контейнеры перезапущены
# Использование: bash services/erp/scripts/install-saas-theme.sh

set -e
COMPOSE="docker compose -f /opt/factory-platform/services/erp/docker-compose.yml"

echo "📦 Установка saas_theme на erp.localhost..."

$COMPOSE exec -T backend bench --site erp.localhost install-app saas_theme

echo "🔨 Сборка ассетов..."
$COMPOSE exec -T backend bench build --app saas_theme

echo "🧹 Очистка кэша..."
$COMPOSE exec -T backend bench --site erp.localhost clear-cache

echo "✅ saas_theme установлена! Открой ERP и сделай Ctrl+Shift+R"
