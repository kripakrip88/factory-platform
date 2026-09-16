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

# python-magic определяет тип файла через libmagic — без системной библиотеки импорт падает.
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Две группы пакетов:
#  1) ОБЪЯВЛЕННЫЕ в external_dependencies манифестов RuOdoo;
#  2) НЕ объявленные, но реально импортируемые в коде — найдены сканированием
#     всех .py репозитория. Это дефект упаковки RuOdoo: без них модуль ставится
#     «успешно» по манифесту и падает на импорте. Первым так отвалился l10n_ru_contract
#     с ModuleNotFoundError: pymorphy2.
#     pymorphy2 тянет словарь отдельным пакетом — pymorphy2-dicts-ru.
#     matplotlib/networkx нужны только модулям mklab_* (показатели и графы);
#     держим в образе, чтобы их можно было включить не пересобирая.
#
# --break-system-packages: в Debian 12+ системный python помечен как externally-managed
# (PEP 668), без флага pip отказывается ставить. Для образа это безопасно.
ARG PYDEPS="pytils num2words docxcompose docxtpl beautifulsoup4 polib siphashc weasyprint \
            pymorphy2 pymorphy2-dicts-ru dadata httpx python-magic matplotlib networkx openupgradelib"
RUN pip3 install --no-cache-dir --break-system-packages ${PYDEPS} \
    || pip3 install --no-cache-dir ${PYDEPS}

USER odoo
