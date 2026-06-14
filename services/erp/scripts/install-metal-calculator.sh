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
  echo "📦 install-app metal_calculator + migrate..."
  # install-app и migrate под общим откатом: любой сбой → uninstall, ERP как до установки.
  if $COMPOSE exec -T backend bench $SITE install-app metal_calculator \
     && $COMPOSE exec -T backend bench $SITE migrate; then
    echo "✓ Установка и миграция прошли"
  else
    echo "⚠️ install-app/migrate упал → АВТО-ОТКАТ (uninstall), чтобы не сломать ERP..."
    $COMPOSE exec -T backend bench $SITE uninstall-app metal_calculator --yes --no-backup || true
    $COMPOSE exec -T backend bench $SITE clear-cache || true
    echo "↩️ Откат выполнен. ERP в состоянии до установки."
    exit 1
  fi
fi

echo "🔨 Сборка ассетов калькулятора (ТОЛЬКО metal_calculator, образ не трогаем)..."
$COMPOSE exec -T backend bench build --app metal_calculator || true
echo "🧹 Очистка кэша..."
$COMPOSE exec -T backend bench $SITE clear-cache || true

echo ""
echo "🔍 SMOKE: saas_theme не пострадал? (маркер сборки должен читаться)"
curl -s http://localhost:8080/assets/saas_theme/js/saas_theme.js \
  | grep -o 'SAAS_THEME_BUILD = "[^"]*"' | head -1 \
  || echo "  ⚠️ маркер не прочитан — проверь тему/инбокс визуально"
curl -s -o /dev/null -w "  ERP root http=%{http_code} (ожидаем 302→/desk)\n" http://localhost:8080/

echo ""
echo "✅ metal_calculator установлен! Воркспейс «Калькуляторы», Ctrl+Shift+R"
echo "   Проверь визуально: инбокс и карточка лида (saas_theme/CRM на месте)."
echo "   Ручной откат при необходимости:"
echo "   $COMPOSE exec -T backend bench $SITE uninstall-app metal_calculator --yes --no-backup"
