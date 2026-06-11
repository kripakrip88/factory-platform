FROM frappe/erpnext:v16

USER frappe

# Копируем saas_theme из монорепозитория
COPY --chown=frappe:frappe saas_theme /home/frappe/frappe-bench/apps/saas_theme

RUN cd /home/frappe/frappe-bench && \
    uv pip install --quiet -e apps/saas_theme --python env/bin/python && \
    bench build --app saas_theme
