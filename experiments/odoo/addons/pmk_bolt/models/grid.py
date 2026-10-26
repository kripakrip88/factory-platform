# -*- coding: utf-8 -*-
"""Таблица болтов — та же, что у Бутика и «Конструкций» (Антон 21.10.2026: «почему
строка ввода не как в бутике? … почему не соблюдается принцип единообразия?»).

Виджет pmk_bolt_grid — наследник таблицы Бутика (pmk_butik/static/src/js/
butik_grid.js): та же разметка, клавиши, вставка из Excel. Болт — как изделие,
под ним состав — как детали («болт должен быть составом вида как у металлоизделия,
отдельно круг гайки шайбы плиты»; только материалы). Ключи строк: «b<id>» — болт, «p<id>» — состав.

Ячейка болта — короткая запись («бф 2.1 м30 640мм ст3 10шт»); под ней — название
по ГОСТ, пометки, прошлые продажи. Новая строка (Enter, «+ Строка»): запись болта —
новый болт, иначе — своя строка состава текущего болта («гайка м30 калён 2шт 45»).
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools import gost, parse
from .bolt import NUT_KINDS
from .part import parse_part

BOLT, PART = "b", "p"


def _to_float(value):
    text = str(value or "").replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _nut_kind(text):
    low = (text or "").strip().lower()
    if low.startswith("кал") or "кл" in low:
        return "hardened"
    if low.startswith("спец"):
        return "special"
    return "plain"


def _key(kind, record_id):
    return "%s%s" % (kind, record_id)


def _parse_key(key):
    key = str(key or "")
    if len(key) > 1 and key[0] in (BOLT, PART) and key[1:].isdigit():
        return key[0], int(key[1:])
    return None, 0


class BoltLineGrid(models.Model):
    _inherit = "pmk.bolt.line"

    pmk_text = fields.Char("Запись", help="Как набрали в таблице, если калькулятор её не понял.")
    parse_error = fields.Char("Не понял")

    def _grid_rows(self, number):
        self.ensure_one()
        ok = self._pmk_ok() and not self.parse_error
        rows = [{
            "id": _key(BOLT, self.id), "kind": "product", "number": number,
            "name": (self.pmk_text if self.parse_error else self.short_name) or "",
            "label": self.parse_error or self.name or "", "bad": bool(self.parse_error),
            "warning": self.warning if ok else "", "history": self.history if ok else "",
            "product_qty": self.qty or 0, "nut_kind": dict(NUT_KINDS).get(self.nut_kind, ""),
            "mass_total": (self.mass_one or 0.0) * (self.qty or 0),
            "markup": self.markup_pct or 0.0, "price": self.price_unit or 0.0,
            "mass": self.mass_one or 0.0, "cost": self.cost_one or 0.0, "total": self.price_total or 0.0,
        }]
        hints = {key: self._pmk_buy_hint(key) for key in ("nut", "washer")} if ok else {}
        standard = {}
        if ok:
            spec = gost.TYPES[self.bolt_type]
            standard = {"stud": 1, "nut": spec["nuts"], "washer": 1, "plate": 1}
        for part in self.part_ids.sorted(lambda p: (p.sequence, p.id)):
            stud = part.auto_key == "stud"
            std = standard.get(part.auto_key)
            changed = (_("%(qty)s вместо %(std)s по ГОСТ", qty=("%g" % part.qty).replace(".", ","), std=std)
                       if std is not None and abs(part.qty - std) > 1e-9 else "")
            rows.append({
                "id": _key(PART, part.id), "kind": "detail", "parent": _key(BOLT, self.id),
                "name": part.name or "", "auto": bool(part.auto_key), "changed": changed,
                "qty": part.qty, "qty_total": part.qty * (self.qty or 0),
                "mass": part.mass, "cost": part.cost,
                "price": part.price_ton if stud else part.price_unit,
                "price_label": _("₽/т") if stud else _("₽/шт"),
                "hint": hints.get(part.auto_key, ""),
                "no_price": not (part.price_ton if stud else part.price_unit),
            })
        return rows

    def _grid_apply_text(self, text):
        """Короткая запись болта → поля. Не понял — запись остаётся с причиной."""
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
        nut_price = vals.pop("nut_price", None)
        vals.update(pmk_text=False, parse_error=False)
        self.write(vals)
        if nut_price:
            self.part_ids.filtered(lambda p: p.auto_key == "nut")._pmk_user_write({"price_unit": nut_price})


class BoltCalcGrid(models.Model):
    _inherit = "pmk.bolt.calc"

    def _grid_lines(self):
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))

    def bolt_rows(self):
        self.ensure_one()
        self.check_access("read")
        if not self.line_ids and self.has_access("write"):
            # Новый расчёт — сразу пустая строка болта, в неё и пишут (как у Бутика).
            self.env["pmk.bolt.line"].create({"calc_id": self.id, "sequence": 10})
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
        if kind == BOLT:
            return kind, self.line_ids.filtered(lambda l: l.id == rid)
        if kind == PART:
            return kind, self.line_ids.part_ids.filtered(lambda p: p.id == rid)
        return None, self.env["pmk.bolt.line"]

    def _grid_new_bolt(self, after_line, text=""):
        """Новый болт после after_line (или в конце)."""
        lines = self._grid_lines()
        seq = after_line.sequence if after_line else max(lines.mapped("sequence") or [0])
        for other in lines.filtered(lambda l: l.sequence > seq):
            other.sequence += 10
        line = self.env["pmk.bolt.line"].create({"calc_id": self.id, "sequence": seq + 5})
        if text:
            line._grid_apply_text(text)
        return line

    def _grid_new_part(self, line, after_part, vals):
        parts = line.part_ids.sorted(lambda p: (p.sequence, p.id))
        seq = after_part.sequence if after_part else max(parts.mapped("sequence") or [0])
        for other in parts.filtered(lambda p: p.sequence > seq):
            other.sequence += 10
        return self.env["pmk.bolt.part"].create(dict(vals, line_id=line.id, sequence=seq + 5))

    def _grid_place(self, after_key, text):
        """Новая строка после after_key: запись болта — новый болт, иначе — строка состава."""
        kind, record = self._grid_record(after_key)
        line = record if kind == BOLT else (record.line_id if kind == PART else self._grid_lines()[-1:])
        text = (text or "").strip()
        if text and not parse.parse(text)[2]:
            return self._grid_new_bolt(line, text)
        if not line:
            return self._grid_new_bolt(False, text)
        return self._grid_new_part(line, record if kind == PART else False,
                                   parse_part(text) if text else {"name": "", "qty": 1.0})

    def bolt_set_part_from_catalog(self, row_key, key):
        """Каталог материалов (26.10.2026): метиз справочника в строку состава — название, масса
        штуки и цена из прайса (нет цены — прежняя). Строка становится «поправленной»."""
        self.ensure_one()
        self.check_access("write")
        kind, part = self._grid_record(row_key)
        if kind != PART or not part or part.auto_key == "stud":
            raise UserError(_("Из каталога — метиз в строку состава (гайка, шайба, своя строка)."))
        model, _sep, ident = (key or "").partition(":")
        if model != "fastener" or not ident.isdigit():
            raise UserError(_("В состав болта ставится метиз — выберите в разделе «Метизы»."))
        fastener = self.env["pmk.metal.fastener"].browse(int(ident)).exists()
        if not fastener:
            raise UserError(_("Позиция не найдена — обновите каталог."))
        vals = {"name": ("%s %s" % (fastener.name, fastener.gost or "")).strip(), "unit_mass": fastener.weight_kg}
        tmpl = fastener.product_tmpl_id
        seller = tmpl._pmk_find_seller(fields.Date.context_today(self)) if tmpl else False
        if seller:
            vals["price_unit"] = round(seller.price_discounted, 2)
        part._pmk_user_write(vals)
        return self.bolt_rows()

    def bolt_save_row(self, row_key, vals):
        """Правка ячейки (или новая строка: row_key = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        vals = vals or {}
        if not row_key:
            self._grid_place(vals.get("after_id"), vals.get("name") or "")
            return self.bolt_rows()
        kind, record = self._grid_record(row_key)
        if not record:
            return self.bolt_rows()
        if kind == BOLT:
            if "name" in vals:
                record._grid_apply_text(vals["name"])
            if "product_qty" in vals:
                record.qty = max(1, int(_to_float(vals["product_qty"]) or 1))
            if "nut_kind" in vals:
                record.nut_kind = _nut_kind(vals["nut_kind"])
            if "markup" in vals:
                record.markup_pct = _to_float(vals["markup"])
            if "price" in vals:
                record.price_unit = _to_float(vals["price"])
            return self.bolt_rows()
        # Строка состава. Пустая строка, куда вписали болт, — становится болтом.
        if "name" in vals:
            text = (vals["name"] or "").strip()
            if not record.auto_key and text and not parse.parse(text)[2]:
                line = record.line_id
                record.unlink()
                self._grid_new_bolt(line, text)
                return self.bolt_rows()
            if record.auto_key:
                record._pmk_user_write({"name": text or record.name})
            else:
                record.write(parse_part(text) if text else {"name": ""})
        if "qty" in vals:
            record._pmk_user_write({"qty": _to_float(vals["qty"])})
        if "price" in vals:
            field = "price_ton" if record.auto_key == "stud" else "price_unit"
            record._pmk_user_write({field: _to_float(vals["price"])})
        return self.bolt_rows()

    def bolt_insert_rows(self, after_key, rows):
        """Вставка из Excel или письма: болты — новыми болтами, прочее — в состав."""
        self.ensure_one()
        self.check_access("write")
        texts = [" ".join(str(v).strip() for v in (row or {}).values() if str(v or "").strip()) for row in rows or []]
        texts = [t for t in texts if t]
        kind, record = self._grid_record(after_key)
        empty_bolt = kind == BOLT and record and not (record.bolt_type or record.pmk_text)
        if empty_bolt and texts and not parse.parse(texts[0])[2]:
            record._grid_apply_text(texts.pop(0))
        key = after_key
        for text in texts:
            new = self._grid_place(key, text)
            key = _key(BOLT if new._name == "pmk.bolt.line" else PART, new.id)
        return self.bolt_rows()

    def bolt_add_product(self):
        """«+ Болт» (Ctrl+Enter) — пустой болт в конце."""
        self.ensure_one()
        self.check_access("write")
        self._grid_new_bolt(self._grid_lines()[-1:])
        return self.bolt_rows()

    def bolt_delete_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        _kind, record = self._grid_record(row_key)
        record.unlink()
        return self.bolt_rows()

    def bolt_move_row(self, row_key, target_key, below):
        """№312: перетащить строку. Болт — среди болтов (с составом), строка состава — в болт той
        строки, над/под которую её бросили (на болт — первой строкой состава)."""
        self.ensure_one()
        self.check_access("write")
        kind, record = self._grid_record(row_key)
        tkind, target = self._grid_record(target_key)
        if not record or not target or record == target:
            return self.bolt_rows()
        if kind == BOLT:
            bolt = target if tkind == BOLT else target.line_id
            bolts = [l for l in self._grid_lines() if l != record]
            if bolt == record or bolt not in bolts:
                return self.bolt_rows()
            bolts.insert(bolts.index(bolt) + (1 if below else 0), record)
            for number, line in enumerate(bolts, 1):
                if line.sequence != number * 10:
                    line.sequence = number * 10
            return self.bolt_rows()
        bolt = target if tkind == BOLT else target.line_id
        if record.auto_key and bolt != record.line_id:
            raise UserError(_("Строка состава по ГОСТ остаётся у своего болта — переносится только своя строка."))
        parts = [p for p in bolt.part_ids.sorted(lambda p: (p.sequence, p.id)) if p != record]
        index = 0 if tkind == BOLT else parts.index(target) + (1 if below else 0)
        parts.insert(index, record)
        if record.line_id != bolt:
            record.line_id = bolt
        for number, part in enumerate(parts, 1):
            if part.sequence != number * 10:
                part.sequence = number * 10
        return self.bolt_rows()

    def bolt_duplicate_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        kind, record = self._grid_record(row_key)
        if kind == BOLT and record:
            for other in self.line_ids.filtered(lambda l, s=record.sequence: l.sequence > s):
                other.sequence += 10
            # Состав копируется с правками (copy=True); пересчёт по ГОСТ его не задвоит.
            record.copy({"calc_id": self.id, "sequence": record.sequence + 5})
        elif kind == PART and record:
            # Копия строки состава — своя строка (у ГОСТ на ключ строка одна).
            vals = {k: record[k] for k in ("name", "qty", "unit_mass", "price_unit")}
            self._grid_new_part(record.line_id, record, vals)
        return self.bolt_rows()
