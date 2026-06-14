#!/bin/bash
# Установка metal_calculator на существующий сайт erp.localhost.
# Запускать ПОСЛЕ того как новый образ собран и контейнеры перезапущены.
# Использование: bash services/erp/scripts/install-metal-calculator.sh

set -e
COMPOSE="docker compose -f /opt/factory-platform/services/erp/docker-compose.yml"

echo "📦 Установка metal_calculator на erp.localhost..."
$COMPOSE exec -T backend bench --site erp.localhost install-app metal_calculator

echo "🌱 Сид справочников ГОСТ (идемпотентно через after_install + миграции)..."
$COMPOSE exec -T backend bench --site erp.localhost migrate

echo "🔨 Сборка ассетов..."
$COMPOSE exec -T backend bench build --app metal_calculator

echo "🧹 Очистка кэша..."
$COMPOSE exec -T backend bench --site erp.localhost clear-cache

echo "✅ metal_calculator установлен! Открой ERP, воркспейс «Калькуляторы», Ctrl+Shift+R"
