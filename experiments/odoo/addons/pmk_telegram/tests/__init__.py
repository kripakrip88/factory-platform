# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_tg_test -i pmk_telegram --test-enable \
#        --test-tags /pmk_telegram --stop-after-init --http-port 8099
from . import test_bot
