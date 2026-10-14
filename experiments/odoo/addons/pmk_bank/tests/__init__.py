# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе:
#   odoo -d pmk_bank_test -i pmk_bank --test-enable --test-tags /pmk_bank --stop-after-init
from . import test_match
from . import test_flow
