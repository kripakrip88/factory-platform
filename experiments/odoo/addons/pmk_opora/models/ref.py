# -*- coding: utf-8 -*-
"""Справочник опор ОСТ 36-146-88 (пункт 3 плана, Антон 25.10.2026): все сочетания
категория × Дн × исполнение из таблиц ОСТ — состав по деталям, масса по деталям и
по ОСТ рядом. Строки собирает _pmk_fill() при установке и обновлении модуля, руками
их не правят: источник — tools/ost.py.
"""
from odoo import api, fields, models

from ..tools import ost

TYPES = [(k, v["label"]) for k, v in ost.TYPES.items()]


class OporaRef(models.Model):
    _name = "pmk.opora.ref"
    _description = "Справочник опор ОСТ 36-146-88"
    _order = "opora_type, dn, execution"
    _rec_name = "designation"

    opora_type = fields.Selection(TYPES, "Категория", required=True, readonly=True)
    dn = fields.Integer("Дн трубы, мм", required=True, readonly=True, aggregator=False)
    execution = fields.Char("Исполнение", required=True, readonly=True)
    designation = fields.Char("Обозначение", readonly=True, help="Без марки стали: «219-КХ-А12».")
    height = fields.Integer("Н, мм", readonly=True, aggregator=False, help="У КП — до низа трубы, у КХ — до низа хомута.")
    length = fields.Integer("Длина корпуса, мм", readonly=True, aggregator=False)
    width = fields.Integer("Ширина B, мм", readonly=True, aggregator=False)
    thickness = fields.Integer("Лист корпуса, мм", readonly=True, aggregator=False)
    mass = fields.Float("Масса по деталям, кг", digits=(10, 2), readonly=True, aggregator=False)
    ost_mass = fields.Float("Масса по ОСТ, кг", digits=(10, 1), readonly=True, aggregator=False,
                            help="«Не более» по таблице ОСТ (у КХ — без упоров).")
    ratio = fields.Integer("Детали / ОСТ, %", readonly=True, aggregator=False)
    parts_text = fields.Text("Состав", readonly=True)

    _key_uniq = models.Constraint("UNIQUE(opora_type, dn, execution)", "Опора в справочнике — один раз.")

    @api.model
    def _pmk_fill(self):
        """Пересобрать справочник из tools/ost.py: недостающие — создать, изменившиеся — обновить,
        лишние — удалить."""
        have = {(r.opora_type, r.dn, r.execution): r for r in self.search([])}
        for kind in ost.TYPES:
            for dn in ost.diameters(kind):
                for exe in ost.executions(kind, dn):
                    if ost.check(kind, dn, exe):
                        continue  # неподвижная А11 на большой Дн — по табл. 1 не бывает
                    g = ost.body(kind, dn, exe)
                    parts = ost.parts(kind, dn, exe)
                    mass = ost.mass(kind, dn, exe)
                    ost_mass = ost.ost_mass(kind, dn, exe)
                    vals = dict(
                        designation="%s-%s-%s" % (dn, ost.TYPES[kind]["code"], exe),
                        height=g["h"], length=g["L"], width=g["B"], thickness=g["S"],
                        mass=mass, ost_mass=ost_mass, ratio=round(mass / ost_mass * 100) if ost_mass else 0,
                        parts_text="\n".join(("%s — %g шт × %.2f кг" % (p["name"], p["qty"], p["unit_mass"])).replace(".", ",")
                                             for p in parts),
                    )
                    rec = have.pop((kind, dn, exe), None)
                    if rec:
                        changed = {k: v for k, v in vals.items() if rec[k] != v}
                        if changed:
                            rec.write(changed)
                    else:
                        self.create(dict(vals, opora_type=kind, dn=dn, execution=exe))
        for rec in have.values():
            rec.unlink()
        return True
