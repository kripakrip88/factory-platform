# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk23_test -i pmk_theme,pmk_purchase --test-enable \
#        --test-tags /pmk_theme,/pmk_purchase --stop-after-init --http-port 8099
from . import test_price_mailing_path
from . import test_step25_lists
from . import test_step26_empty
from . import test_step28_partner_mailing
from . import test_step29_hidden
