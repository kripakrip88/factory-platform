#!/bin/bash
# Установка metal_calculator на сайт erp.localhost с путями отхода.
# Предусловие: образ пересобран (код аппы уже в контейнере).
# Использование: bash services/erp/scripts/install-metal-calculator.sh

set -e
COMPOSE="docker compose -f /opt/factory-platform/services/erp/docker-compose.yml"
SITE="--site erp.localhost"

echo "🔎 Предусловие: код metal_calculator в контейнере?"
$COMPOSE exec -T backend bash -c "test -d /home/frappe/frappe-bench/apps/metal_calculator" \
  || { echo "❌ ABORT: apps/metal_calculator нет в контейнере. Сначала пересобери образ."; exit 1; }

echo "🔒 ПУТЬ ОТХОДА: бэкап БД + файлов до установки..."
$COMPOSE exec -T backend bench $SITE backup --with-files \
  || { echo "❌ ABORT: бэкап не удался — ничего не ставим."; exit 1; }

if $COMPOSE exec -T backend bench $SITE list-apps | grep -qw metal_calculator; then
  echo "ℹ️ Уже установлен — догоняем миграции (идемпотентно)..."
  $COMPOSE exec -T backend bench $SITE migrate
else
  echo "📦 install-app metal_calculator..."
  if ! $COMPOSE exec -T backend bench $SITE install-app metal_calculator; then
    echo "⚠️ install-app упал → АВТО-ОТКАТ (uninstall), чтобы не сломать ERP..."
    $COMPOSE exec -T backend bench $SITE uninstall-app metal_calculator --yes --no-backup || true
    $COMPOSE exec -T backend bench $SITE clear-cache || true
    echo "↩️ Откат выполнен. ERP в состоянии до установки."
    exit 1
  fi
fi

echo "🔨 Сборка ассетов..."
$COMPOSE exec -T backend bench build --app metal_calculator || true
echo "🧹 Очистка кэша..."
$COMPOSE exec -T backend bench $SITE clear-cache || true

echo "✅ metal_calculator установлен! Воркспейс «Калькуляторы», Ctrl+Shift+R"
echo "   Ручной откат при необходимости:"
echo "   $COMPOSE exec -T backend bench $SITE uninstall-app metal_calculator --yes --no-backup"
