# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk23_test -i pmk_theme,pmk_purchase --test-enable \
#        --test-tags /pmk_theme,/pmk_purchase --stop-after-init --http-port 8099
# Подсветку строки разделов (JS) здесь не проверить — в контейнере нет
# Chrome, туры пропускаются. Ключи подсветки — чистые функции
# static/src/js/active_section_keys.js, их гоняет node вне Odoo.
from . import test_dangerous_actions
from . import test_settings_paid_hidden
