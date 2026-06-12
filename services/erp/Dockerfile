FROM frappe/erpnext:v16

USER frappe

# Копируем saas_theme из монорепозитория
COPY --chown=frappe:frappe saas_theme /home/frappe/frappe-bench/apps/saas_theme

RUN cd /home/frappe/frappe-bench && \
    uv pip install --quiet -e apps/saas_theme --python env/bin/python && \
    bench build --app saas_theme

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
USER frappe
