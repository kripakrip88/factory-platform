# -*- coding: utf-8 -*-
"""19.0.0.9.4 — №313 (Владимир, 24.10.2026): цены проката по маркам.

Старые цены проката лежали на шаблоне, марка — только в названии строки прайса.
Переносим их на вариант марки (Ст3сп — существующий вариант, другие марки
заводятся), чтобы загрузчик продолжал те же ряды цен, а подбор отличал 09Г2С от Ст3.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True})
    moved, kept, refused = env["product.template"]._pmk_linear_prices_to_grade_variants()
    _logger.info("pmk_bridge 19.0.0.9.4: цены проката на варианты марки %s; на шаблоне осталось %s; "
                 "не перенесено %s", moved, kept, refused)
