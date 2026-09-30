# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_deal_test -i pmk_deal --test-enable \
#        --test-tags /pmk_deal --stop-after-init --http-port 8099
# Строка денег без базы: python3 addons/pmk_deal/tests/test_money_text.py
from . import test_money_text
from . import test_deal_money
from . import test_deal_views
