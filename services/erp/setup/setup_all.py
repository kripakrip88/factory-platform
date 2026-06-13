"""
Полная настройка ERPNext после первого запуска.

Запускать один раз после init-site.sh:

    docker compose -f services/erp/docker-compose.yml cp \
      services/erp/setup/setup_all.py backend:/tmp/setup_all.py
    docker compose -f services/erp/docker-compose.yml exec backend \
      bench --site erp.localhost execute /tmp/setup_all.py

Идемпотентен — безопасно перезапускать.
"""

import frappe


def execute():
    print("=== Factory Platform — ERPNext setup ===")

    # 1. CRM: воронка, этапы, скрытые секции
    print("\n[1/2] CRM setup...")
    from crm_setup import execute as crm
    crm()

    # Кнопка «Отмена» теперь глобальная — в saas_theme.js (form-refresh hook),
    # покрывает ВСЕ DocType. Per-doctype Client Scripts удалены.

    # 2. UX: поиск + уведомления в рейле, скрыть из сайдбара
    print("\n[2/2] Client Scripts — Rail icons...")
    from client_scripts.rail_icons import execute as rail_icons
    rail_icons()

    print("\n=== Setup complete ===")


execute()
