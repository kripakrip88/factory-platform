# -*- coding: utf-8 -*-
"""Пустой экран без выдуманных записей (разбор UX, шаг 26, 01.10.2026).

Штатные списки, канбаны, графики и сводные несут атрибут sample="1": когда
записей нет, ядро рисует под подсказкой размытые демо-строки с чужими
суммами и именами («$ 88 202», «John Miller», «Portugal»). На заводе это
читалось как «там чьи-то данные». Снимаем атрибут у собранной разметки
любого вида любой модели — до кэша видов (_get_view_cache), поэтому правка
стоит один раз на вид, а не на каждое открытие.

Почему здесь, а не наследованием видов: таких видов на стенде больше
полутора сотен в двух десятках модулей (sale, purchase, stock, mrp, crm, hr,
account, maintenance, repair…), плюс расширения, которые сами дописывают
sample (mrp.mrp_production_workorder_tree_view). Наследник на каждый вид
ломался бы при каждом обновлении ядра.

Пустой экран после этого — шапка таблицы и подсказка (тексты —
ir_actions_act_window.py). Пустые строки-распорки под шапкой снял ещё шаг 24
(static/src/js/list_table.js).

Вернуть демо-строки: удалить этот файл и строку «from . import base» в
models/__init__.py, выложить pmk_theme. Таблица — docs/disabled-features.md.
"""
from odoo import api, models


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if arch is not None and "sample" in arch.attrib:
            del arch.attrib["sample"]
        return arch, view
