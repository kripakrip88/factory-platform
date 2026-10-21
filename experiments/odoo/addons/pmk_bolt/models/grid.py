# -*- coding: utf-8 -*-
"""Таблица болтов — та же, что у Бутика и «Конструкций» (Антон 21.10.2026: «почему
строка ввода не как в бутике? … почему не соблюдается принцип единообразия?»).

Виджет pmk_bolt_grid — наследник таблицы Бутика (pmk_butik/static/src/js/
butik_grid.js): та же разметка, клавиши (Enter, стрелки, Tab, Ctrl+D), вставка
блока из Excel. Строки — болты расчёта; методы bolt_* отвечают таблицей целиком.

Ячейка «Болт» — короткая запись («бф 2.1 м30 640мм ст3 10шт»), после сохранения
в ней — запись калькулятора «2.1 М30×640 · Ст3 · резьба 120»; под ней мелко, как
«узнано как» у Бутика, — название по ГОСТ, комплект, себестоимость, прошлые продажи.
"""
from odoo import _, api, fields, models

from ..tools import gost, parse
from .bolt import NUT_KINDS


def _to_float(value):
    text = str(value or "").replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _money(value):
    return "{:,.0f}".format(value or 0).replace(",", " ")


def _nut_kind(text):
    low = (text or "").strip().lower()
    if low.startswith("кал") or "кл" in low:
        return "hardened"
    if low.startswith("спец"):
        return "special"
    return "plain"


class BoltLineGrid(models.Model):
    _inherit = "pmk.bolt.line"

    pmk_text = fields.Char("Запись", help="Как набрали в таблице, если калькулятор её не понял.")
    parse_error = fields.Char("Не понял")

    def _grid_row(self, number):
        self.ensure_one()
        ok = bool(self.bolt_type and self.diameter and self.length and not self.parse_error)
        cost_parts = [(_("круг"), self.metal_rub), (_("плита"), self.plate_rub), (_("шайба"), self.washer_rub),
                      (_("гайки"), self.nuts_rub), (_("резьба"), self.thread_rub), (_("гиб, проточка"), self.work_rub)]
        detail = ""
        if ok:
            spec = gost.TYPES[self.bolt_type]
            kit = [_("заготовка %s мм") % int(self.blank_mm), _("%(n)s гайки М%(d)s", n=spec["nuts"], d=self.diameter),
                   _("шайба")]
            if spec["plate"]:
                b, t, _kg = gost.SIZES[int(self.diameter)]["plate"]
                kit.append(_("плита %(b)s×%(t)s", b=b, t=t))
            detail = _("Комплект: %(kit)s · себестоимость: %(cost)s", kit=", ".join(kit),
                       cost=", ".join("%s %s" % (k, _money(v)) for k, v in cost_parts if v))
        return {
            "id": self.id, "kind": "bolt", "number": number,
            "name": (self.pmk_text if self.parse_error else self.short_name) or "",
            "label": self.parse_error or self.name or "",
            "bad": bool(self.parse_error),
            "detail": detail, "warning": self.warning if ok else "",
            "history": self.history if ok else "",
            "nut_hint": self.nut_hint if ok else "",
            "qty": self.qty or 0, "nut_kind": dict(NUT_KINDS).get(self.nut_kind, ""),
            "nut_price": self.nut_price or 0.0, "markup": self.markup_pct or 0.0,
            "price": self.price_unit or 0.0, "mass": self.mass_one or 0.0,
            "cost": self.cost_one or 0.0, "total": self.price_total or 0.0,
        }

    def _grid_apply_text(self, text):
        """Короткая запись в ячейке «Болт» → поля строки. Не понял — запись остаётся с причиной."""
        self.ensure_one()
        text = (text or "").strip()
        if not text:
            self.write({"pmk_text": False, "parse_error": False})
            return
        vals, _notes, error = parse.parse(text)
        if error:
            self.write({"pmk_text": text, "parse_error": error})
            return
        vals.setdefault("qty", self.qty or 1)
        vals.setdefault("steel", self.steel or "09Г2С")
        if "thread_len" not in vals and vals.get("diameter") != self.diameter:
            vals["thread_len"] = gost.SIZES[int(vals["diameter"])]["l0"]
        vals.update(pmk_text=False, parse_error=False)
        self.write(vals)


class BoltCalcGrid(models.Model):
    _inherit = "pmk.bolt.calc"

    def _grid_lines(self):
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))

    def bolt_rows(self):
        self.ensure_one()
        self.check_access("read")
        if not self.line_ids and self.has_access("write"):
            # Новый расчёт — сразу пустая строка, в неё и пишут (как у Бутика).
            self.env["pmk.bolt.line"].create({"calc_id": self.id, "sequence": 10})
        lines = self._grid_lines()
        return {
            "rows": [line._grid_row(i) for i, line in enumerate(lines, 1)],
            "count": self.total_qty, "weight_kg": self.total_weight,
            "cost": self.total_cost, "amount": self.amount_total,
            "can_write": self.has_access("write"),
        }

    def _grid_insert(self, texts, after_id):
        lines = self._grid_lines()
        after = lines.filtered(lambda l: l.id == after_id)
        seq = after.sequence if after else (max(lines.mapped("sequence") or [0]))
        later = lines.filtered(lambda l: l.sequence > seq)
        for line in later:
            line.sequence += 10 * max(1, len(texts))
        created = self.env["pmk.bolt.line"]
        for i, text in enumerate(texts, 1):
            line = self.env["pmk.bolt.line"].create({"calc_id": self.id, "sequence": seq + i})
            line._grid_apply_text(text)
            created |= line
        return created

    def bolt_save_row(self, row_id, vals):
        """Правка ячейки (или новая строка: row_id = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        vals = vals or {}
        if not row_id:
            self._grid_insert([vals.get("name") or ""], vals.get("after_id"))
            return self.bolt_rows()
        line = self.line_ids.filtered(lambda l: l.id == row_id)
        if not line:
            return self.bolt_rows()
        if "name" in vals:
            line._grid_apply_text(vals["name"])
        if "qty" in vals:
            line.qty = max(1, int(_to_float(vals["qty"]) or 1))
        if "nut_kind" in vals:
            line.nut_kind = _nut_kind(vals["nut_kind"])
        if "nut_price" in vals:
            line.nut_price = _to_float(vals["nut_price"])
        if "markup" in vals:
            line.markup_pct = _to_float(vals["markup"])
        if "price" in vals:
            line.price_unit = _to_float(vals["price"])
        return self.bolt_rows()

    def bolt_insert_rows(self, after_id, rows):
        """Вставка из Excel или письма: столбик строк или колонки (склеиваем в одну запись)."""
        self.ensure_one()
        self.check_access("write")
        texts = [" ".join(str(v).strip() for v in (row or {}).values() if str(v or "").strip()) for row in rows or []]
        texts = [t for t in texts if t]
        target = self.line_ids.filtered(lambda l: l.id == after_id)
        if target and not (target.bolt_type or target.pmk_text) and texts:
            # Вставка в пустую строку — первая запись в неё же.
            target._grid_apply_text(texts.pop(0))
        if texts:
            self._grid_insert(texts, after_id)
        return self.bolt_rows()

    def bolt_delete_row(self, row_id):
        self.ensure_one()
        self.check_access("write")
        self.line_ids.filtered(lambda l: l.id == row_id).unlink()
        return self.bolt_rows()

    def bolt_duplicate_row(self, row_id):
        self.ensure_one()
        self.check_access("write")
        line = self.line_ids.filtered(lambda l: l.id == row_id)
        if line:
            for other in self.line_ids.filtered(lambda l, s=line.sequence: l.sequence > s):
                other.sequence += 1
            line.copy({"calc_id": self.id, "sequence": line.sequence + 1})
        return self.bolt_rows()
