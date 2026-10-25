# -*- coding: utf-8 -*-
"""Таблица металлоизделий колодцев — та же, что у Бутика, «Конструкций», болтов и опор
(принцип единообразия, Антон 21.10.2026).

Виджет pmk_kolodec_grid — наследник таблицы Бутика (pmk_butik/static/src/js/butik_grid.js).
Изделие — как изделие, под ним состав — как детали (стойки, ступени, пластины, фланцы;
только материалы). Ключи строк: «i<id>» — изделие, «p<id>» — состав.

Ячейка изделия — короткая запись («с1-04 10шт», «мс-5 100шт», «проставка ду300»); под ней —
название по альбому, пометки, прошлые продажи. Новая строка: запись изделия — новое изделие,
иначе — своя строка состава текущего изделия («шпилька м16х190 8шт 45»).
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools import parse
from .part import parse_part

ITEM, PART = "i", "p"


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
    if len(key) > 1 and key[0] in (ITEM, PART) and key[1:].isdigit():
        return key[0], int(key[1:])
    return None, 0


def _is_item(text):
    return bool(text) and not parse.parse(text)[2]


class KolodecLineGrid(models.Model):
    _inherit = "pmk.kolodec.line"

    pmk_text = fields.Char("Запись", help="Как набрали в таблице, если калькулятор её не понял.")
    parse_error = fields.Char("Не понял")

    def _grid_rows(self, number):
        self.ensure_one()
        ok = self._pmk_ok() and not self.parse_error
        rows = [{
            "id": _key(ITEM, self.id), "kind": "product", "number": number,
            "name": (self.pmk_text if self.parse_error else self.short_name) or "",
            "label": self.parse_error or self.name or "", "bad": bool(self.parse_error),
            "warning": self.warning if ok else "", "history": self.history if ok else "",
            "product_qty": self.qty or 0, "ost_mass": self.album_mass if ok else 0.0,
            "mass_total": (self.mass_one or 0.0) * (self.qty or 0),
            "markup": self.markup_pct or 0.0, "price": self.price_unit or 0.0,
            "mass": self.mass_one or 0.0, "cost": self.cost_one or 0.0, "total": self.price_total or 0.0,
        }]
        for part in self.part_ids.sorted(lambda p: (p.sequence, p.id)):
            metal = part._pmk_is_metal()
            price = part.price_ton if metal else part.price_unit
            rows.append({
                "id": _key(PART, part.id), "kind": "detail", "parent": _key(ITEM, self.id),
                "name": part.name or "", "auto": bool(part.auto_key),
                "changed": _("поправлено руками") if part.edited else "",
                "qty": part.qty, "qty_total": part.qty * (self.qty or 0),
                "mass": part.mass, "cost": part.cost, "price": price,
                "price_label": _("₽/т") if metal else _("₽/шт"),
                "hint": self._pmk_buy_hint(part) if ok and part.auto_key and not metal else "", "no_price": bool(part.name) and not price,
            })
        return rows

    def _grid_apply_text(self, text):
        """Короткая запись изделия → поля. Не понял — запись остаётся с причиной."""
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
        vals.update(pmk_text=False, parse_error=False)
        self.write(vals)


class KolodecCalcGrid(models.Model):
    _inherit = "pmk.kolodec.calc"

    def _grid_lines(self):
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))

    def kolodec_rows(self):
        self.ensure_one()
        self.check_access("read")
        if not self.line_ids and self.has_access("write"):
            # Новый расчёт — сразу пустая строка изделия, в неё и пишут (как у Бутика).
            self.env["pmk.kolodec.line"].create({"calc_id": self.id, "sequence": 10})
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
        if kind == ITEM:
            return kind, self.line_ids.filtered(lambda l: l.id == rid)
        if kind == PART:
            return kind, self.line_ids.part_ids.filtered(lambda p: p.id == rid)
        return None, self.env["pmk.kolodec.line"]

    def _grid_new_item(self, after_line, text=""):
        lines = self._grid_lines()
        seq = after_line.sequence if after_line else max(lines.mapped("sequence") or [0])
        for other in lines.filtered(lambda l: l.sequence > seq):
            other.sequence += 10
        line = self.env["pmk.kolodec.line"].create({"calc_id": self.id, "sequence": seq + 5})
        if text:
            line._grid_apply_text(text)
        return line

    def _grid_new_part(self, line, after_part, vals):
        parts = line.part_ids.sorted(lambda p: (p.sequence, p.id))
        seq = after_part.sequence if after_part else max(parts.mapped("sequence") or [0])
        for other in parts.filtered(lambda p: p.sequence > seq):
            other.sequence += 10
        return self.env["pmk.kolodec.part"].create(dict(vals, line_id=line.id, sequence=seq + 5))

    def _grid_place(self, after_key, text):
        """Новая строка после after_key: запись изделия — новое изделие, иначе — строка состава."""
        kind, record = self._grid_record(after_key)
        line = record if kind == ITEM else (record.line_id if kind == PART else self._grid_lines()[-1:])
        text = (text or "").strip()
        if _is_item(text):
            return self._grid_new_item(line, text)
        if not line:
            return self._grid_new_item(False, text)
        return self._grid_new_part(line, record if kind == PART else False,
                                   parse_part(text) if text else {"name": "", "qty": 1.0})

    def kolodec_save_row(self, row_key, vals):
        """Правка ячейки (или новая строка: row_key = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        vals = vals or {}
        if not row_key:
            self._grid_place(vals.get("after_id"), vals.get("name") or "")
            return self.kolodec_rows()
        kind, record = self._grid_record(row_key)
        if not record:
            return self.kolodec_rows()
        if kind == ITEM:
            if "name" in vals:
                record._grid_apply_text(vals["name"])
            if "product_qty" in vals:
                record.qty = max(1, int(_to_float(vals["product_qty"]) or 1))
            if "markup" in vals:
                record.markup_pct = _to_float(vals["markup"])
            if "price" in vals:
                record.price_unit = _to_float(vals["price"])
            return self.kolodec_rows()
        # Строка состава. Пустая строка, куда вписали изделие, — становится изделием.
        if "name" in vals:
            text = (vals["name"] or "").strip()
            if not record.auto_key and _is_item(text):
                line = record.line_id
                record.unlink()
                self._grid_new_item(line, text)
                return self.kolodec_rows()
            if record.auto_key:
                record._pmk_user_write({"name": text or record.name})
            else:
                record.write(parse_part(text) if text else {"name": ""})
        if "qty" in vals:
            record._pmk_user_write({"qty": _to_float(vals["qty"])})
        if "price" in vals:
            field = "price_ton" if record._pmk_is_metal() else "price_unit"
            record._pmk_user_write({field: _to_float(vals["price"])})
        return self.kolodec_rows()

    def kolodec_insert_rows(self, after_key, rows):
        """Вставка из Excel или письма: изделия — новыми изделиями, прочее — в состав."""
        self.ensure_one()
        self.check_access("write")
        texts = [" ".join(str(v).strip() for v in (row or {}).values() if str(v or "").strip()) for row in rows or []]
        texts = [t for t in texts if t]
        kind, record = self._grid_record(after_key)
        empty = kind == ITEM and record and not (record.item_type or record.pmk_text)
        if empty and texts and _is_item(texts[0]):
            record._grid_apply_text(texts.pop(0))
        key = after_key
        for text in texts:
            new = self._grid_place(key, text)
            key = _key(ITEM if new._name == "pmk.kolodec.line" else PART, new.id)
        return self.kolodec_rows()

    def kolodec_add_product(self):
        """«+ Изделие» (Ctrl+Enter) — пустое изделие в конце."""
        self.ensure_one()
        self.check_access("write")
        self._grid_new_item(self._grid_lines()[-1:])
        return self.kolodec_rows()

    def kolodec_delete_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        _kind, record = self._grid_record(row_key)
        record.unlink()
        return self.kolodec_rows()

    def kolodec_move_row(self, row_key, target_key, below):
        """Перетащить строку: изделие — среди изделий (с составом), строка состава — в изделие той
        строки, над/под которую её бросили (на изделие — первой строкой состава)."""
        self.ensure_one()
        self.check_access("write")
        kind, record = self._grid_record(row_key)
        tkind, target = self._grid_record(target_key)
        if not record or not target or record == target:
            return self.kolodec_rows()
        if kind == ITEM:
            item = target if tkind == ITEM else target.line_id
            items = [l for l in self._grid_lines() if l != record]
            if item == record or item not in items:
                return self.kolodec_rows()
            items.insert(items.index(item) + (1 if below else 0), record)
            for number, line in enumerate(items, 1):
                if line.sequence != number * 10:
                    line.sequence = number * 10
            return self.kolodec_rows()
        item = target if tkind == ITEM else target.line_id
        if record.auto_key and item != record.line_id:
            raise UserError(_("Строка состава по альбому остаётся у своего изделия — переносится только своя строка."))
        parts = [p for p in item.part_ids.sorted(lambda p: (p.sequence, p.id)) if p != record]
        index = 0 if tkind == ITEM else parts.index(target) + (1 if below else 0)
        parts.insert(index, record)
        if record.line_id != item:
            record.line_id = item
        for number, part in enumerate(parts, 1):
            if part.sequence != number * 10:
                part.sequence = number * 10
        return self.kolodec_rows()

    def kolodec_duplicate_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        kind, record = self._grid_record(row_key)
        if kind == ITEM and record:
            for other in self.line_ids.filtered(lambda l, s=record.sequence: l.sequence > s):
                other.sequence += 10
            # Состав копируется с правками (copy=True); пересчёт по альбому его не задвоит.
            record.copy({"calc_id": self.id, "sequence": record.sequence + 5})
        elif kind == PART and record:
            # Копия строки состава — своя строка (у альбома на ключ строка одна).
            vals = {k: record[k] for k in ("name", "qty", "unit_mass", "thickness", "metal", "price_unit", "price_ton")}
            self._grid_new_part(record.line_id, record, vals)
        return self.kolodec_rows()
