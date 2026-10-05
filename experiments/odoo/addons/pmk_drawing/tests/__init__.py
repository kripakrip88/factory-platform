# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе:
#   odoo -d dxf_test -i pmk_drawing --test-enable --test-tags /pmk_drawing --stop-after-init
# dxf_samples.py — сборщик тестовых чертежей, не тест.
from . import test_dxf_render
from . import test_drawing_model
