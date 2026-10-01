# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk23_test -i pmk_theme,pmk_purchase,theme_nexus --test-enable \
#        --test-tags /pmk_theme,/pmk_purchase --stop-after-init --http-port 8099
# theme_nexus — как на стенде: переключатель темы опирается на её механизм
# (шаг 47); без неё часть проверок сборки пропускается.
# Подсветку строки разделов (JS) здесь не проверить — в контейнере нет
# Chrome, туры пропускаются. Ключи подсветки — чистые функции
# static/src/js/active_section_keys.js, их гоняет node вне Odoo.
from . import test_dangerous_actions
from . import test_settings_paid_hidden
from . import test_list_table
from . import test_empty_screens
from . import test_step27_forms
from . import test_step47_trifles
from . import test_step29_hidden
