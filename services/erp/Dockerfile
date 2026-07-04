# ТОЧНЫЙ пин версии (не плавающий :v16). Линейка :v16 на 2026-06 несёт битую пару
# erpnext 16.22.0 + frappe 16.20.0: erpnext вызывает grid.set_column_disp_in_list_view,
# которого нет ни в одном релизе frappe 16 → форма Work Order не рендерится.
# v16.21.1 — последняя согласованная пара (erpnext 16.21.1 + frappe 16.20.0).
# frappe и erpnext обновляются ТОЛЬКО парой; менять этот тег осознанно, с migrate.
#
# Multi-stage + build-arg WITH_CRM (по умолчанию nocrm):
#   прод (docker-compose.yml) собирает БЕЗ CRM — путь тождественен прежнему.
#   staging (docker-compose.staging.yml, WITH_CRM=crm) добавляет Frappe CRM.

# WITH_CRM — ГЛОБАЛЬНЫЙ build-arg: объявлен ДО первого FROM, иначе не виден в
# `FROM erp-${WITH_CRM}` ниже (BuildKit: UndefinedArgInFrom → пустое имя стадии).
ARG WITH_CRM=nocrm

# ─── base: ERP + saas_theme + metal_calculator (прод-путь, без изменений) ────────
FROM frappe/erpnext:v16.21.1 AS base

USER frappe

# Копируем saas_theme из монорепозитория
COPY --chown=frappe:frappe saas_theme /home/frappe/frappe-bench/apps/saas_theme

RUN cd /home/frappe/frappe-bench && \
    uv pip install --quiet -e apps/saas_theme --python env/bin/python && \
    bench build --app saas_theme

# Копируем metal_calculator (калькулятор веса металлопроката) из монорепозитория.
# Изолированная аппа: справочники ГОСТ + расчёт + воркспейс «Калькуляторы».
# Установка на сайт (install-app) — отдельным шагом через scripts/install-metal-calculator.sh.
COPY --chown=frappe:frappe metal_calculator /home/frappe/frappe-bench/apps/metal_calculator

RUN cd /home/frappe/frappe-bench && \
    uv pip install --quiet -e apps/metal_calculator --python env/bin/python && \
    bench build --app metal_calculator

# Скрипт синхронизации assets.json запускается при старте backend контейнера.
# Решает проблему рассинхрона: volume хранит старый assets.json со старыми
# хэшами, а новый image содержит пересобранные CSS/JS с новыми хэшами.
COPY --chown=frappe:frappe fix_assets.py /home/frappe/fix_assets.py

# Патчим шаблон nginx-конфига: отключаем кэш HTML для свежего boot info.
# frappe.conf генерируется из шаблона при старте; патчим шаблон если он есть.
USER root
RUN for f in \
        /home/frappe/frappe-bench/config/frappe.conf \
        /usr/local/lib/python3.14/site-packages/bench/config/templates/frappe.conf \
        /opt/frappe-config/nginx.conf.jinja \
        /templates/nginx.conf.jinja; do \
    if [ -f "$f" ]; then \
        sed -i '/location @webserver {/a\\tadd_header Cache-Control "no-cache, must-revalidate" always;' "$f" && \
        echo "Patched nginx template: $f"; \
    fi; \
done; exit 0

# Редирект корня на /desk: "/" для залогиненных отдаёт легаси-лаунчер модулей,
# hooks home_page его не перекрывает (Desk-страница рендерится в обход website-роутов).
# ВАЖНО: редиректим ТОЛЬКО GET. Иначе POST / (легаси frappe.call с cmd, который шлёт
# страница /update-password и др. web-формы) ловит 302 → форма не работает. POST/прочее
# уходит на backend (@webserver).
RUN if [ -f /templates/nginx/frappe.conf.template ]; then \
        sed -i '/root \/home\/frappe\/frappe-bench\/sites;/a\\n\tlocation = / {\n\t\tif ($request_method = GET) { return 302 /desk; }\n\t\ttry_files /nonexistent @webserver;\n\t}' \
            /templates/nginx/frappe.conf.template && \
        echo "Patched: / -> /desk redirect (GET only)"; \
    fi
USER frappe

# ─── crm-build: сборка Vue-фронта Frappe CRM (node). Только для стадии erp-crm ──
# При WITH_CRM=nocrm эта стадия НЕ является зависимостью финала → BuildKit её пропускает.
FROM node:20-bookworm-slim AS crm-build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*
RUN corepack enable || npm i -g yarn
# Vite-сборка фронта CRM упирается в дефолтный V8-heap (~2G) → OOM (exit 134).
# Система тянет (8G RAM + swap) — поднимаем лимит heap ноды.
ENV NODE_OPTIONS=--max-old-space-size=4096
WORKDIR /opt
RUN git clone --depth 1 https://github.com/frappe/crm.git
WORKDIR /opt/crm/frontend
RUN yarn install && yarn build

# ─── вариант без CRM (прод) ──────────────────────────────────────────────────────
FROM base AS erp-nocrm

# ─── вариант с CRM (staging) ─────────────────────────────────────────────────────
FROM base AS erp-crm
# Собранный фронт CRM уже внутри /opt/crm (public/frontend) — переносим аппу целиком.
COPY --from=crm-build --chown=frappe:frappe /opt/crm /home/frappe/frappe-bench/apps/crm
# Регистрируем как python-пакет (bench build --app НЕ запускаем: в рантайм-образе нет
# node/esbuild; SPA уже собран yarn'ом на стадии crm-build).
RUN cd /home/frappe/frappe-bench && \
    uv pip install --quiet -e apps/crm --python env/bin/python

# ─── финальный выбор по WITH_CRM (nocrm → прод, crm → staging) ───────────────────
FROM erp-${WITH_CRM} AS final
