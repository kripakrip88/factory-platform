# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_z2_test -i pmk_orders,pmk_org,pmk_theme,pmk_flow --test-enable \
#        --test-tags /pmk_orders,/pmk_org,/pmk_theme:TestMenusStep38,/pmk_theme:TestStep39Words,/pmk_flow \
#        --stop-after-init --http-port 8099
# Только синтетические данные: клиентов из Excel-планировщика здесь нет.
from . import test_step_z2_invoice
from . import test_step_z2_planner
from . import test_step_z2_prices
