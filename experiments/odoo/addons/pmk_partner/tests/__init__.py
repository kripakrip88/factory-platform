# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_partner_test -i pmk_partner,pmk_purchase --test-enable \
#        --test-tags /pmk_partner --stop-after-init --http-port 8099
from . import test_customer_list
from . import test_step28_card
from . import test_step29_partner
# Клиент из письма: не плодить дубли (шаг З-14). Правила без базы:
#   python3 addons/pmk_partner/tests/test_partner_keys_rules.py
from . import test_partner_keys_rules
from . import test_z14_client_match
