# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_deal_test -i pmk_deal --test-enable \
#        --test-tags /pmk_deal --stop-after-init --http-port 8099
# Строка денег без базы: python3 addons/pmk_deal/tests/test_money_text.py
from . import test_money_text
from . import test_deal_money
from . import test_deal_views
from . import test_kp_sent
from . import test_list_columns
from . import test_partner_specs
from . import test_step29_utm
# Разбор UX, шаг 35: доборка и сделка.
from . import test_step35_dobor_deal
# Разбор UX, шаг 39: старая история сделок словами завода.
from . import test_step39_tracking
# Разбор UX, шаг 39: один фильтр «В работе» в поиске сделок.
from . import test_step39_filters
# Разбор UX, шаг 48: номер сделки «СД-», карточка без «Новое».
from . import test_step48_deal_head
# Разбор UX, шаг 54: смена дохода от расчёта — строкой в истории сделки.
from . import test_step54_revenue_history
