# -*- coding: utf-8 -*-
"""Справочник металлоизделий колодцев: все марки по альбомам — стремянки С1 (902-09-22.84)
и С (901-09-11.84), МС-1…8, МН1, проставки (эскиз), ЗО, К1.

Строки собирает _pmk_fill() при установке и обновлении модуля, руками их не правят:
источник — файлы альбомов tools/<альбом>.py через tools/catalog.py. Править справочник =
править файл своего альбома (и docs/), остальные не трогаются.
"""
from odoo import api, fields, models

from ..tools import catalog

TYPES = [(k, v["label"]) for k, v in catalog.TYPES.items()]


class KolodecRef(models.Model):
    _name = "pmk.kolodec.ref"
    _description = "Справочник металлоизделий колодцев"
    _order = "album, item_type, sequence"
    _rec_name = "designation"

    album = fields.Char("Альбом", readonly=True)
    item_type = fields.Selection(TYPES, "Изделие", readonly=True)
    sequence = fields.Integer(readonly=True)
    mark = fields.Char("Марка", readonly=True)
    designation = fields.Char("Обозначение", readonly=True)
    name = fields.Char("Наименование", readonly=True)
    length = fields.Integer("Длина / L, мм", readonly=True, aggregator=False)
    rungs = fields.Integer("Ступеней", readonly=True, aggregator=False)
    width = fields.Integer("Ширина / Д, мм", readonly=True, aggregator=False)
    mass = fields.Float("Масса по деталям, кг", digits=(10, 2), readonly=True, aggregator=False)
    album_mass = fields.Float("Масса по альбому, кг", digits=(10, 2), readonly=True, aggregator=False)
    ratio = fields.Integer("Детали / альбом, %", readonly=True, aggregator=False)
    outside = fields.Boolean("Вне альбома", readonly=True)
    parts_text = fields.Text("Состав", readonly=True)

    _key_uniq = models.Constraint("UNIQUE(item_type, mark)", "Изделие в справочнике — один раз.")

    @api.model
    def _pmk_rows(self):
        """{(вид, марка): значения} — всё, что должно быть в справочнике."""
        rows = {}
        for kind, spec in catalog.TYPES.items():
            for seq, mark in enumerate(catalog.marks(kind), 1):
                d = catalog.dims(kind, mark)
                mass = catalog.mass(kind, mark)
                album_mass = catalog.album_mass(kind, mark)
                rows[(kind, mark)] = dict(
                    album=spec["album"], sequence=seq, designation=catalog.designation(kind, mark),
                    name=catalog.name(kind, mark), length=d.get("length", 0), rungs=d.get("rungs", 0),
                    width=d.get("width", 0), mass=mass, album_mass=album_mass,
                    ratio=round(mass / album_mass * 100) if album_mass else 0,
                    outside=bool(catalog.outside_album(kind, mark)),
                    parts_text="\n".join(("%s — %g шт × %.3f кг" % (p["name"], p["qty"], p["unit_mass"]))
                                         .replace(".", ",") for p in catalog.parts(kind, mark)),
                )
        return rows

    @api.model
    def _pmk_fill(self):
        """Пересобрать справочник: недостающие — создать, изменившиеся — обновить, лишние — удалить."""
        want = self._pmk_rows()
        for rec in self.search([]):
            vals = want.pop((rec.item_type, rec.mark), None)
            if vals is None:
                rec.unlink()
                continue
            changed = {k: v for k, v in vals.items() if rec[k] != v}
            if changed:
                rec.write(changed)
        for (kind, mark), vals in want.items():
            self.create(dict(vals, item_type=kind, mark=mark))
        return True
