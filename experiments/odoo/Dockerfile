# Тонкая надстройка над официальным образом Odoo: только Python-зависимости RuOdoo.
#
# ЗАЧЕМ. Модули RuOdoo объявляют external_dependencies, которых нет в официальном
# образе. Без них установка падает с
#   UserError: Unable to install module "..." because an external dependency is not met
# Проверено на живой установке: первым отвалился docxcompose.
#
# Список собран из манифестов всех 48 модулей RuOdoo (external_dependencies.python).
# Базовый образ пиним датированным тегом — не плавающим 19.0.

FROM odoo:19.0-20260908

USER root

# weasyprint рисует PDF через pango/cairo — без системных библиотек он ставится,
# но падает при первом же отчёте.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# --break-system-packages: в Debian 12+ системный python помечен как externally-managed
# (PEP 668), без флага pip отказывается ставить. Для образа это безопасно.
RUN pip3 install --no-cache-dir --break-system-packages \
        pytils \
        num2words \
        docxcompose \
        docxtpl \
        beautifulsoup4 \
        polib \
        siphashc \
        weasyprint \
    || pip3 install --no-cache-dir \
        pytils num2words docxcompose docxtpl beautifulsoup4 polib siphashc weasyprint

USER odoo
