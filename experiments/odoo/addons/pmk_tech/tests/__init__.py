# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_z4_test -i pmk_tech,pmk_flow --test-enable \
#        --test-tags /pmk_tech,/pmk_orders,/pmk_purchase:TestPurchaseMenuStep38,/pmk_bridge:TestSpecFormStep32,/pmk_deal,/pmk_flow \
#        --stop-after-init --http-port 8099
# Только синтетические данные.
from . import test_step_z4
