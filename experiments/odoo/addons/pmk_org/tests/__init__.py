# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk58_test -i pmk_org --test-enable \
#        --test-tags /pmk_org --stop-after-init --http-port 8099
# Режим на дату без базы: python3 addons/pmk_org/tests/test_step58_regime.py
from . import test_step58_regime
from . import test_step58_org
