FROM frappe/erpnext:v16

USER frappe

# Копируем saas_theme из монорепозитория
COPY --chown=frappe:frappe saas_theme /home/frappe/frappe-bench/apps/saas_theme

RUN cd /home/frappe/frappe-bench && \
    uv pip install --quiet -e apps/saas_theme --python env/bin/python && \
    bench build --app saas_theme

# Отключаем кэш для динамических страниц (HTML/boot info).
# CSS/JS с хэшами в именах браузер кэширует вечно — это правильно.
# Главная страница /desk должна всегда запрашиваться заново, иначе
# при следующем деплое браузер будет запрашивать старые bundle хэши.
USER root
RUN sed -i \
    '/location @webserver {/a\\tadd_header Cache-Control "no-cache, must-revalidate" always;' \
    /etc/nginx/conf.d/frappe.conf
USER frappe
