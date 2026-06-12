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

# Отключаем кэш HTML в nginx чтобы браузер всегда получал свежий boot info
# с актуальными хэшами бандлов после каждого деплоя.
USER root
RUN sed -i \
    '/location @webserver {/a\\tadd_header Cache-Control "no-cache, must-revalidate" always;' \
    /etc/nginx/conf.d/frappe.conf
USER frappe
