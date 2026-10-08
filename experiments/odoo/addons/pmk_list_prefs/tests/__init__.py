# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk55_test -i pmk_list_prefs,theme_nexus --test-enable \
#        --test-tags /pmk_list_prefs --stop-after-init --http-port 8099
# Правила порядка, ширин и видимости (чистые функции) — node, без Odoo:
#   node experiments/odoo/addons/pmk_list_prefs/static/tests/list_prefs_step55.test.mjs
# Сам список (растягивание, перетаскивание, окно «Колонки») — глазами в
# браузере: в контейнере нет Chrome, туры пропускаются.
from . import test_step55_list_prefs
