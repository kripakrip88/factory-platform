# -*- coding: utf-8 -*-
"""Таблица опор — та же, что у Бутика, «Конструкций» и болтов (принцип единообразия,
Антон 21.10.2026).

Виджет pmk_opora_grid — наследник таблицы Бутика (pmk_butik/static/src/js/butik_grid.js).
Опора — как изделие, под ней состав — как детали (корпус, рёбра, полухомуты, болты,
упоры; только материалы). Ключи строк: «o<id>» — опора, «p<id>» — состав.

Ячейка опоры — короткая запись («кх а12 219 09г2с 20шт», «кх неподв а22 219»); под ней —
название по ОСТ, пометки, прошлые продажи. Новая строка: запись опоры — новая опора,
иначе — своя строка состава текущей опоры («болт м20х60 2шт 25»).
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools import parse
from .part import parse_part

OPORA, PART = "o", "p"


def _to_float(value):
    text = str(value or "").replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _key(kind, record_id):
    return "%s%s" % (kind, record_id)


def _parse_key(key):
    key = str(key or "")
    if len(key) > 1 and key[0] in (OPORA, PART) and key[1:].isdigit():
        return key[0], int(key[1:])
    return None, 0


def _is_opora(text):
    return bool(text) and not parse.parse(text)[2]


class OporaLineGrid(models.Model):
    _inherit = "pmk.opora.line"

    pmk_text = fields.Char("Запись", help="Как набрали в таблице, если калькулятор её не понял.")
    parse_error = fields.Char("Не понял")

    def _grid_rows(self, number):
        self.ensure_one()
        ok = self._pmk_ok() and not self.parse_error
        rows = [{
            "id": _key(OPORA, self.id), "kind": "product", "number": number,
            "name": (self.pmk_text if self.parse_error else self.short_name) or "",
            "label": self.parse_error or self.name or "", "bad": bool(self.parse_error),
            "warning": self.warning if ok else "", "history": self.history if ok else "",
            "product_qty": self.qty or 0, "ost_mass": self.ost_mass if ok else 0.0,
            "mass_total": (self.mass_one or 0.0) * (self.qty or 0),
            "markup": self.markup_pct or 0.0, "price": self.price_unit or 0.0,
            "mass": self.mass_one or 0.0, "cost": self.cost_one or 0.0, "total": self.price_total or 0.0,
        }]
        hints = {key: self._pmk_buy_hint(key) for key in ("bolt", "nut")} if ok else {}
        for part in self.part_ids.sorted(lambda p: (p.sequence, p.id)):
            metal = part._pmk_is_metal()
            price = part.price_ton if metal else part.price_unit
            rows.append({
                "id": _key(PART, part.id), "kind": "detail", "parent": _key(OPORA, self.id),
                "name": part.name or "", "auto": bool(part.auto_key),
                "changed": _("поправлено руками") if part.edited else "",
                "qty": part.qty, "qty_total": part.qty * (self.qty or 0),
                "mass": part.mass, "cost": part.cost, "price": price,
                "price_label": _("₽/т") if metal else _("₽/шт"),
                "hint": hints.get(part.auto_key, ""), "no_price": not price,
            })
        return rows

    def _grid_apply_text(self, text):
        """Короткая запись опоры → поля. Не понял — запись остаётся с причиной."""
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
        vals.setdefault("steel", self.steel or "Ст3пс")
        vals.setdefault("height", 0)
        vals.update(pmk_text=False, parse_error=False)
        self.write(vals)


class OporaCalcGrid(models.Model):
    _inherit = "pmk.opora.calc"

    def _grid_lines(self):
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))

    def opora_rows(self):
        self.ensure_one()
        self.check_access("read")
        if not self.line_ids and self.has_access("write"):
            # Новый расчёт — сразу пустая строка опоры, в неё и пишут (как у Бутика).
            self.env["pmk.opora.line"].create({"calc_id": self.id, "sequence": 10})
        rows = []
        for i, line in enumerate(self._grid_lines(), 1):
            rows += line._grid_rows(i)
        return {
            "rows": rows, "products": len(self.line_ids),
            "count": self.total_qty, "weight_kg": self.total_weight,
            "cost": self.total_cost, "amount": self.amount_total,
            "can_write": self.has_access("write"),
        }

    def _grid_record(self, key):
        kind, rid = _parse_key(key)
        if kind == OPORA:
            return kind, self.line_ids.filtered(lambda l: l.id == rid)
        if kind == PART:
            return kind, self.line_ids.part_ids.filtered(lambda p: p.id == rid)
        return None, self.env["pmk.opora.line"]

    def _grid_new_opora(self, after_line, text=""):
        lines = self._grid_lines()
        seq = after_line.sequence if after_line else max(lines.mapped("sequence") or [0])
        for other in lines.filtered(lambda l: l.sequence > seq):
            other.sequence += 10
        line = self.env["pmk.opora.line"].create({"calc_id": self.id, "sequence": seq + 5})
        if text:
            line._grid_apply_text(text)
        return line

    def _grid_new_part(self, line, after_part, vals):
        parts = line.part_ids.sorted(lambda p: (p.sequence, p.id))
        seq = after_part.sequence if after_part else max(parts.mapped("sequence") or [0])
        for other in parts.filtered(lambda p: p.sequence > seq):
            other.sequence += 10
        return self.env["pmk.opora.part"].create(dict(vals, line_id=line.id, sequence=seq + 5))

    def _grid_place(self, after_key, text):
        """Новая строка после after_key: запись опоры — новая опора, иначе — строка состава."""
        kind, record = self._grid_record(after_key)
        line = record if kind == OPORA else (record.line_id if kind == PART else self._grid_lines()[-1:])
        text = (text or "").strip()
        if _is_opora(text):
            return self._grid_new_opora(line, text)
        if not line:
            return self._grid_new_opora(False, text)
        return self._grid_new_part(line, record if kind == PART else False,
                                   parse_part(text) if text else {"name": "", "qty": 1.0})

    def opora_save_row(self, row_key, vals):
        """Правка ячейки (или новая строка: row_key = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        vals = vals or {}
        if not row_key:
            self._grid_place(vals.get("after_id"), vals.get("name") or "")
            return self.opora_rows()
        kind, record = self._grid_record(row_key)
        if not record:
            return self.opora_rows()
        if kind == OPORA:
            if "name" in vals:
                record._grid_apply_text(vals["name"])
            if "product_qty" in vals:
                record.qty = max(1, int(_to_float(vals["product_qty"]) or 1))
            if "markup" in vals:
                record.markup_pct = _to_float(vals["markup"])
            if "price" in vals:
                record.price_unit = _to_float(vals["price"])
            return self.opora_rows()
        # Строка состава. Пустая строка, куда вписали опору, — становится опорой.
        if "name" in vals:
            text = (vals["name"] or "").strip()
            if not record.auto_key and _is_opora(text):
                line = record.line_id
                record.unlink()
                self._grid_new_opora(line, text)
                return self.opora_rows()
            if record.auto_key:
                record._pmk_user_write({"name": text or record.name})
            else:
                record.write(parse_part(text) if text else {"name": ""})
        if "qty" in vals:
            record._pmk_user_write({"qty": _to_float(vals["qty"])})
        if "price" in vals:
            field = "price_ton" if record._pmk_is_metal() else "price_unit"
            record._pmk_user_write({field: _to_float(vals["price"])})
        return self.opora_rows()

    def opora_insert_rows(self, after_key, rows):
        """Вставка из Excel или письма: опоры — новыми опорами, прочее — в состав."""
        self.ensure_one()
        self.check_access("write")
        texts = [" ".join(str(v).strip() for v in (row or {}).values() if str(v or "").strip()) for row in rows or []]
        texts = [t for t in texts if t]
        kind, record = self._grid_record(after_key)
        empty = kind == OPORA and record and not (record.opora_type or record.pmk_text)
        if empty and texts and _is_opora(texts[0]):
            record._grid_apply_text(texts.pop(0))
        key = after_key
        for text in texts:
            new = self._grid_place(key, text)
            key = _key(OPORA if new._name == "pmk.opora.line" else PART, new.id)
        return self.opora_rows()

    def opora_add_product(self):
        """«+ Опора» (Ctrl+Enter) — пустая опора в конце."""
        self.ensure_one()
        self.check_access("write")
        self._grid_new_opora(self._grid_lines()[-1:])
        return self.opora_rows()

    def opora_delete_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        _kind, record = self._grid_record(row_key)
        record.unlink()
        return self.opora_rows()

    def opora_move_row(self, row_key, target_key, below):
        """Перетащить строку: опора — среди опор (с составом), строка состава — в опору той
        строки, над/под которую её бросили (на опору — первой строкой состава)."""
        self.ensure_one()
        self.check_access("write")
        kind, record = self._grid_record(row_key)
        tkind, target = self._grid_record(target_key)
        if not record or not target or record == target:
            return self.opora_rows()
        if kind == OPORA:
            opora = target if tkind == OPORA else target.line_id
            oporas = [l for l in self._grid_lines() if l != record]
            if opora == record or opora not in oporas:
                return self.opora_rows()
            oporas.insert(oporas.index(opora) + (1 if below else 0), record)
            for number, line in enumerate(oporas, 1):
                if line.sequence != number * 10:
                    line.sequence = number * 10
            return self.opora_rows()
        opora = target if tkind == OPORA else target.line_id
        if record.auto_key and opora != record.line_id:
            raise UserError(_("Строка состава по ОСТ остаётся у своей опоры — переносится только своя строка."))
        parts = [p for p in opora.part_ids.sorted(lambda p: (p.sequence, p.id)) if p != record]
        index = 0 if tkind == OPORA else parts.index(target) + (1 if below else 0)
        parts.insert(index, record)
        if record.line_id != opora:
            record.line_id = opora
        for number, part in enumerate(parts, 1):
            if part.sequence != number * 10:
                part.sequence = number * 10
        return self.opora_rows()

    def opora_duplicate_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        kind, record = self._grid_record(row_key)
        if kind == OPORA and record:
            for other in self.line_ids.filtered(lambda l, s=record.sequence: l.sequence > s):
                other.sequence += 10
            # Состав копируется с правками (copy=True); пересчёт по ОСТ его не задвоит.
            record.copy({"calc_id": self.id, "sequence": record.sequence + 5})
        elif kind == PART and record:
            # Копия строки состава — своя строка (у ОСТ на ключ строка одна).
            vals = {k: record[k] for k in ("name", "qty", "unit_mass", "thickness", "price_unit", "price_ton")}
            self._grid_new_part(record.line_id, record, vals)
        return self.opora_rows()
