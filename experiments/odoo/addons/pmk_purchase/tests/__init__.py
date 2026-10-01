# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk23_test -i pmk_theme,pmk_purchase --test-enable \
#        --test-tags /pmk_theme,/pmk_purchase --stop-after-init --http-port 8099
from . import test_price_mailing_path
from . import test_step25_lists
