# -*- coding: utf-8 -*-
"""Справочник опор (пункт 3 плана, Антон 25.10.2026): все марки по стандартам —
ОСТ 36-146-88 (КП, КХ), ОСТ 36-94-83 (ОПП1 с составом; ОПП2/3, ОПХ, ОПБ — пока без состава).

Строки собирает _pmk_fill() при установке и обновлении модуля, руками их не правят:
источник — файлы стандартов tools/<стандарт>.py через диспетчер tools/catalog.py. Править
справочник = править файл своего стандарта (и docs/<стандарт>.md), остальные не трогаются.
"""
import re

from odoo import api, fields, models

from ..tools import catalog

TYPES = [(k, v["label"]) for k, v in catalog.TYPES.items()]
STANDARDS = [(m.STANDARD, m.STANDARD) for m in catalog.STANDARDS]


class OporaRef(models.Model):
    _name = "pmk.opora.ref"
    _description = "Справочник опор трубопроводов"
    _order = "standard, family, dn, execution"
    _rec_name = "designation"

    standard = fields.Selection(STANDARDS, "Стандарт", readonly=True)
    family = fields.Char("Тип", readonly=True, help="КП, КХ, ОПП1, ОПХ2…")
    opora_type = fields.Selection(TYPES, "Категория калькулятора", readonly=True,
                                  help="Пусто — состав по деталям ещё не собран, в калькуляторе марки нет.")
    has_parts = fields.Boolean("Состав собран", readonly=True)
    dn = fields.Float("Дн трубы, мм", digits=(6, 1), readonly=True, aggregator=False)
    execution = fields.Char("Исполнение / высота", readonly=True)
    designation = fields.Char("Обозначение", readonly=True, help="Без марки стали: «219-КХ-А12», «ОПП1-100.18».")
    height = fields.Integer("Н, мм", readonly=True, aggregator=False, help="У КП — до низа трубы, у КХ — до низа хомута.")
    length = fields.Integer("Длина корпуса, мм", readonly=True, aggregator=False)
    width = fields.Integer("Ширина B, мм", readonly=True, aggregator=False)
    thickness = fields.Integer("Лист корпуса, мм", readonly=True, aggregator=False)
    mass = fields.Float("Масса по деталям, кг", digits=(10, 2), readonly=True, aggregator=False)
    ost_mass = fields.Float("Масса по ОСТ, кг", digits=(10, 2), readonly=True, aggregator=False,
                            help="«Не более» по таблице или приложению ОСТ (у КХ — без упоров).")
    ratio = fields.Integer("Детали / ОСТ, %", readonly=True, aggregator=False)
    parts_text = fields.Text("Состав", readonly=True)

    _key_uniq = models.Constraint("UNIQUE(standard, opora_type, designation)", "Опора в справочнике — один раз.")

    @api.model
    def _pmk_rows(self):
        """{(стандарт, категория, обозначение): значения} — всё, что должно быть в справочнике."""
        rows = {}
        for kind, spec in catalog.TYPES.items():
            for dn in catalog.diameters(kind):
                for exe in catalog.executions(kind, dn):
                    if catalog.check(kind, dn, exe):
                        continue  # неподвижная А11 на большой Дн — по табл. 1 не бывает
                    g = catalog.body(kind, dn, exe)
                    parts = catalog.parts(kind, dn, exe)
                    mass = catalog.mass(kind, dn, exe)
                    ost_mass = catalog.ost_mass(kind, dn, exe)
                    designation = catalog.designation(kind, dn, exe)
                    rows[(spec["standard"], kind, designation)] = dict(
                        family=spec["code"], has_parts=True, dn=dn, execution=exe,
                        height=g["h"], length=g["L"], width=g["B"], thickness=g["S"],
                        mass=mass, ost_mass=ost_mass, ratio=round(mass / ost_mass * 100) if ost_mass else 0,
                        parts_text="\n".join(("%s — %g шт × %.2f кг" % (p["name"], p["qty"], p["unit_mass"]))
                                             .replace(".", ",") for p in parts),
                    )
        for standard, mark, family, label, ost_mass in catalog.catalog_only():
            m = re.match(r"^\D+\d-(?:(\d+)\.)?([\d,]+)$", mark)
            height, dn = (int(m.group(1)) if m and m.group(1) else 0), (float(m.group(2).replace(",", ".")) if m else 0)
            rows[(standard, False, mark)] = dict(
                family=family, has_parts=False, dn=dn, execution=str(height or ""), height=height,
                length=0, width=0, thickness=0, mass=0, ost_mass=ost_mass or 0, ratio=0,
                parts_text="Состав по деталям ещё не собран: %s. Масса — по приложению %s." % (label, standard),
            )
        return rows

    @api.model
    def _pmk_fill(self):
        """Пересобрать справочник: недостающие — создать, изменившиеся — обновить, лишние — удалить."""
        want = self._pmk_rows()
        for rec in self.search([]):
            vals = want.pop((rec.standard, rec.opora_type or False, rec.designation), None)
            if vals is None:
                rec.unlink()
                continue
            changed = {k: v for k, v in vals.items() if rec[k] != v}
            if changed:
                rec.write(changed)
        for (standard, kind, designation), vals in want.items():
            self.create(dict(vals, standard=standard, opora_type=kind, designation=designation))
        return True
