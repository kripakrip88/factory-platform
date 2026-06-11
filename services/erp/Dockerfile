FROM frappe/erpnext:v16

USER frappe

RUN cd /home/frappe/frappe-bench && \
    bench get-app https://github.com/kripakrip88/saas_theme.git --branch version-16
