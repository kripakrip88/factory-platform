# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_deal_test -i pmk_deal_sms --test-enable \
#        --test-tags /pmk_deal_sms --stop-after-init --http-port 8099
from . import test_no_sms
