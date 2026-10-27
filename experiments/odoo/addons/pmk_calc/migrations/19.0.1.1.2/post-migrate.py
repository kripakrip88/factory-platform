# -*- coding: utf-8 -*-
"""Площадь окраски погонного метра у всего проката (27.10.2026, scripts_v1201/profile_surface.py).

В справочнике pmk.metal.profile площадь была только у 8 позиций, у остальных вклад детали
в строку «окраска / цинк» был 0 (колонна из швеллера 30У — 5,25 м² вместо ~31). Данные
залиты, но _compute_paint_area зависит от полей строк, а не от surface_per_meter — сам он
не пересчитается. Пересчитываем строки окраски у изделий, где есть прокат: присваивание
вне вычисления идёт через write(), поэтому следом пересчитываются вес строки, изделия и
итоги расчёта. Изделия без проката не трогаем: площадь у них прежняя, а ручной ввод цел.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["pmk.metal.spec.line"].search([
        ("calc_mode", "=", "paint"),
        ("product_id.line_linear_ids.profile_id", "!=", False),
    ])
    if lines:
        lines._compute_paint_area()
        env.flush_all()
