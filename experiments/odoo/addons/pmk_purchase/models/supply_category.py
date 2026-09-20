# -*- coding: utf-8 -*-
from odoo import fields, models


class SupplyCategory(models.Model):
    """Что поставщик возит.

    Отдельный справочник, а не список галочек на партнёре: номенклатурные
    группы меняются (появится, например, нержавейка или оцинкованный крепёж),
    и дописывать их должен снабженец, не программист.
    """

    _name = "pmk.supply.category"
    _description = "Группа поставки"
    _order = "sequence, name"

    name = fields.Char("Название", required=True, translate=False)
    sequence = fields.Integer("Порядок", default=10)
    note = fields.Char("Пояснение", help="Что сюда входит — чтобы снабженец не гадал.")
    active = fields.Boolean("Активно", default=True)

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Такая группа поставки уже есть."),
    ]
