FROM frappe/erpnext:v16

USER frappe

# Скачиваем saas_theme в bench
RUN cd /home/frappe/frappe-bench && \
    bench get-app https://github.com/vineyrawat/saas_theme.git --branch version-16
