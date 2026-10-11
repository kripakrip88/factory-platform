# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_dadata_test -i pmk_dadata --test-enable \
#        --test-tags /pmk_dadata --stop-after-init --http-port 8099
# В DaData тесты не ходят: проверяется только разметка карточки.
from . import test_step28_requisites
# «Сверить по ИНН» (шаг З-17): ответ справочника подменён, в DaData не ходит.
from . import test_z17_check_by_inn
