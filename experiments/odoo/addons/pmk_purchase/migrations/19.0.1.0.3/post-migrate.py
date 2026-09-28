# -*- coding: utf-8 -*-
"""«Последний прайс» — из цен поставщика (разбор UX, шаг 13, 29.09.2026).

Поле было ручным и стало вычисляемым хранимым. Для уже существующей колонки
Odoo при обновлении модуля ничего не пересчитывает — считает только новые
колонки, — поэтому дату по уже загруженным ценам проставляем здесь. Иначе у
Металлсервиса (1554 цены от 21.09) «Последний прайс» так и остался бы пустым
до следующей заливки.

Пересчитываем всех, у кого есть строки цен, и всех, у кого поле заполнено:
вторые — на случай даты, вписанной когда-то руками без цен за ней.
Повторный прогон даёт тот же результат.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Partner = env["res.partner"].with_context(active_test=False)
    partners = Partner.search(["|", ("pmk_price_row_ids", "!=", False),
                               ("pmk_price_last_date", "!=", False)])
    env.add_to_compute(Partner._fields["pmk_price_last_date"], partners)
    env.flush_all()
