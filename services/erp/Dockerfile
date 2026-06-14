# ТОЧНЫЙ пин версии (не плавающий :v16). Линейка :v16 на 2026-06 несёт битую пару
# erpnext 16.22.0 + frappe 16.20.0: erpnext вызывает grid.set_column_disp_in_list_view,
# которого нет ни в одном релизе frappe 16 → форма Work Order не рендерится.
# v16.21.1 — последняя согласованная пара (erpnext 16.21.1 + frappe 16.20.0).
# frappe и erpnext обновляются ТОЛЬКО парой; менять этот тег осознанно, с migrate.
FROM frappe/erpnext:v16.21.1

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
RUN if [ -f /templates/nginx/frappe.conf.template ]; then \
        sed -i '/root \/home\/frappe\/frappe-bench\/sites;/a\\n\tlocation = / {\n\t\treturn 302 /desk;\n\t}' \
            /templates/nginx/frappe.conf.template && \
        echo "Patched: / -> /desk redirect"; \
    fi
USER frappe
