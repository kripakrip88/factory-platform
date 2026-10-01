# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_partner_test -i pmk_partner,pmk_purchase --test-enable \
#        --test-tags /pmk_partner --stop-after-init --http-port 8099
from . import test_customer_list
from . import test_step28_card
from . import test_step29_partner
