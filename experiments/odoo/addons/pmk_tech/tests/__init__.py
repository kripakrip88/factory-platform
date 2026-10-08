# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_z5_test -i pmk_tech,pmk_flow --test-enable \
#        --test-tags /pmk_tech,/pmk_orders,/pmk_purchase,/pmk_bridge:TestSpecFormStep32,/pmk_deal,/pmk_flow,/pmk_theme:TestStep39Words,/pmk_theme:TestStep39Screens,/pmk_theme:TestHeaderStep48,/pmk_theme:TestHiddenStep29 \
#        --stop-after-init --http-port 8099
# Только синтетические данные.
from . import test_step_z4
from . import test_step_z5
