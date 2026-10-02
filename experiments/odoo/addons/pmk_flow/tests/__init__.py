# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_flow_test -i pmk_flow --test-enable \
#        --test-tags /pmk_flow --stop-after-init --http-port 8099
from . import test_letter_node
# Доводка шага 35: доборка на «Связях» сделки.
from . import test_step35_dobor_node
