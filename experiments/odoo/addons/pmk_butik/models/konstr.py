# -*- coding: utf-8 -*-
"""«Конструкции» — таблица Бутика внутри расчёта (шаг 2, Антон 20.10.2026).

«Калькулятор Бутик отдельной вкладкой в расчёт… считать конкретно в бутике»;
вкладка — «Конструкции» (бывший состав расчёта, бывшее «Металлоизделия»).
Таблица та же, что у отдельного Бутика (js/butik_grid.js): строка изделия,
под ней детали, короткая запись, стрелки, вставка из Excel. Пишет она в ТОТ ЖЕ
состав расчёта — изделия pmk.metal.spec.product и детали pmk.metal.spec.line,
— поэтому цены по прайсам, марка, лист в м², раскладка, вкладки «Металл» и
«Металлоизделия», заявка на металл работают как раньше, без переноса данных.

Соответствие колонок:
  № поз.        → «Деталь» (detail_name);
  Наименование  → распознаётся в вид детали и позицию справочника
                  (прокат / лист / метиз / покрытие, tools/parse.py);
                  набранный текст хранится в pmk_text — его и видно в таблице;
  Ширина, Длина → у листа A × B (a_mm, b_mm), у проката — длина;
  На 1 шт       → «Кол-во на изделие» (целое, не меньше 1 — правило расчёта);
  Марка         → справочник марок (grade_id); нет такой — текст в pmk_grade_text;
  изделие       → название, количество, цена клиенту за шт.
Краска считается от площади деталей изделия сама (pmk_calc, _compute_paint_area).

Прежний редактор состава остаётся — переключатель «Таблица / Подробно» в
таблице (раскладка листа, позиции «на разнос», цена закупки по строке).
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_bridge.tools import grades

from ..tools import parse
from .butik import _EASTER_RE, _decoded, _fmt, _to_float

PRODUCT, DETAIL = "p", "d"
MODE_ITEM = {"linear": "profile_id", "sheet": "sheet_id", "fastener": "fastener_id", "paint": "paint_id"}


def _key(kind, record_id):
    return "%s%d" % (kind, record_id)


def _parse_key(key):
    match = re.match(r"^([pd])(\d+)$", key or "")
    return (match.group(1), int(match.group(2))) if match else (None, None)


class MetalSpecLineKonstr(models.Model):
    _inherit = "pmk.metal.spec.line"

    pmk_text = fields.Char(
        "Наименование", help="Как записали в таблице «Конструкции» («Уголок 63х4», «Лист 10х60»). "
                             "Пусто — показывается позиция справочника.")
    pmk_grade_text = fields.Char(
        "Марка (текст)", help="Марка, как её вписали в таблицу: нет в справочнике марок или записана "
                              "иначе («С345» — цена по 09Г2С, марка справочника в «Марка стали»).")

    def write(self, vals):
        # Марку сменили в «Подробно» (только справочник) — вписанное в таблицу
        # «С345» больше не про эту строку.
        if "grade_id" in vals and "pmk_grade_text" not in vals:
            vals = dict(vals, pmk_grade_text=False)
        return super().write(vals)

    def _konstr_item(self):
        self.ensure_one()
        return self[MODE_ITEM.get(self.calc_mode, "profile_id")]

    def _konstr_label(self):
        """Что распознано — строкой под наименованием, как у Бутика."""
        self.ensure_one()
        item = self._konstr_item()
        if not item:
            if self.pmk_text:
                return _("нет в справочнике — выберите из подсказки")
            return ""
        if self.pmk_mass_kg and self.calc_mode in ("linear", "sheet"):
            # №307: «по КМ» — масса из спецификации, длина / площадь выведены из неё.
            if self.calc_mode == "linear":
                mpm = item.mass_per_meter or 0.0
                text = "%s · %s кг/м · по КМ %s кг = %s м" % (
                    item.display_name, _fmt(round(mpm, 3)), _fmt(round(self.pmk_mass_kg, 1)),
                    _fmt(round(self.pmk_mass_kg / mpm, 1)) if mpm else "?")
            else:
                mps = item.mass_per_sqm or 0.0
                text = "%s · %s кг/м² · по КМ %s кг = %s м²" % (
                    item.display_name, _fmt(round(mps, 2)), _fmt(round(self.pmk_mass_kg, 1)),
                    _fmt(round(self.pmk_mass_kg / mps, 2)) if mps else "?")
        elif self.calc_mode == "linear":
            text = "%s · %s кг/м" % (item.display_name, _fmt(round(item.mass_per_meter or 0, 3)))
        elif self.calc_mode == "sheet":
            text = "%s · %s×%s мм" % (item.display_name, _fmt(self.a_mm) if self.a_mm else "? ширина",
                                      _fmt(self.b_mm) if self.b_mm else "? длина")
        elif self.calc_mode == "fastener":
            text = "%s · метиз" % item.display_name
        else:
            text = "%s · %s м² · %s мкм" % (item.display_name, _fmt(round(self.area_m2 or 0, 2)),
                                           _fmt(self.paint_thickness_um or 0))
        notes = []
        if "price_state" in self._fields and self.price_state == "no_price":
            notes.append(_("нет цены в прайсах"))
        if self.pmk_item_note:
            notes.append(self.pmk_item_note)
        return " · ".join([text] + notes)

    def _konstr_manual_hint(self):
        """Та же позиция и марка, цена вписана вручную в другом расчёте — последняя такая
        (Антон 22.10.2026: «подставить цену из расчёта, указав ссылку на этот расчёт»).
        Сама не подставляется: «нет в прайсе» обычно значит «в городе нет» — решает человек."""
        self.ensure_one()
        item = {"linear": ("profile_id", self.profile_id), "sheet": ("sheet_id", self.sheet_id)}.get(self.calc_mode)
        if not item or not item[1]:
            return False
        domain = [(item[0], "=", item[1].id), ("pmk_manual_price_ton", ">", 0),
                  ("grade_id", "=", self.grade_id.id or False)]
        if self.spec_id.id:
            domain.append(("spec_id", "!=", self.spec_id.id))
        other = self.sudo().search(domain, order="write_date desc", limit=1)
        if not other:
            return False
        return {"price": round(other.pmk_manual_price_ton), "spec_id": other.spec_id.id,
                "spec": other.spec_id.name or "", "date": other.write_date.strftime("%d.%m.%Y")}

    def _konstr_row(self, product):
        self.ensure_one()
        sheet = self.calc_mode == "sheet"
        item = self._konstr_item()
        name = self.pmk_text or (item.display_name if item else "")
        qty_product = product.qty or 0
        return {
            "id": _key(DETAIL, self.id),
            "kind": "detail",
            "parent": _key(PRODUCT, product.id),
            "pos": self.detail_name or "",
            "name": name,
            "is_sheet": sheet,
            # Лист «по КМ» (№307) — без размеров: вес из массы, раскладки нет.
            "width": self.a_mm if sheet and not self.pmk_mass_kg else 0.0,
            "length_mm": (self.b_mm if not self.pmk_mass_kg else 0.0) if sheet
            else (self.length_mm if self.calc_mode == "linear" else 0.0),
            "length_derived": bool(self.pmk_mass_kg) and self.calc_mode == "linear",
            "qty": self.qty or 0,
            "qty_total": (self.qty or 0) * qty_product,
            # Вписанное («С345») — поверх марки справочника, по которой цена (09Г2С).
            "grade": self.pmk_grade_text or self.grade_id.name or "",
            "weight_one": round(self.weight_one, 4),
            "weight_total": round(self.weight_total * qty_product, 3),
            # «Вес всего» — вводимая ячейка: масса по КМ на все изделия (№307).
            "mass": round(self.weight_total * qty_product, 3) if self.pmk_mass_kg else 0.0,
            "by_mass": bool(self.pmk_mass_kg) and self.calc_mode in ("linear", "sheet"),
            "cost": round((self["cost_fact_total"] if "cost_fact_total" in self._fields else 0.0) * qty_product, 2),
            "no_price": self.price_state == "no_price",
            # №314: цена металла за тонну у детали — из прайса (только смотреть) или вписанная
            # вручную, когда позиции в прайсах нет; подсказка — вписанная раньше в другом расчёте.
            "metal_ton": round(self.price_ton) if self.price_state in ("ok", "manual") else 0.0,
            "manual": self.price_state == "manual",
            "can_manual": self.calc_mode in ("linear", "sheet") and self.price_state in ("no_price", "manual"),
            "manual_hint": self._konstr_manual_hint() if self.price_state == "no_price" else False,
            "match_state": "auto" if item else ("none" if self.pmk_text else "empty"),
            "label": self._konstr_label(),
        }


class MetalSpecKonstr(models.Model):
    _inherit = "pmk.metal.spec"

    # ─── таблица ────────────────────────────────────────────────────────
    def _konstr_products(self):
        self.ensure_one()
        return self.product_ids.sorted(lambda p: (p.sequence, p.id))

    def konstr_rows(self):
        self.ensure_one()
        self.check_access("read")
        rows, weight, cost = [], 0.0, 0.0
        for number, product in enumerate(self._konstr_products(), 1):
            rows.append({
                "id": _key(PRODUCT, product.id),
                "kind": "product",
                "number": number,
                "name": product.name or "",
                "product_qty": product.qty or 0,
                "price": product["price_customer_unit"] if "price_customer_unit" in product._fields else 0.0,
                "price_ton": product["pmk_price_ton"] if "pmk_price_ton" in product._fields else 0.0,
                "weight_one": round(product.weight_one, 3),
                "weight_total": round(product.weight_total, 3),
                "cost": round(product["cost_fact_total"] if "cost_fact_total" in product._fields else 0.0, 2),
            })
            for line in product.line_ids.sorted(lambda l: (l.sequence, l.id)):
                row = line._konstr_row(product)
                rows.append(row)
                weight += row["weight_total"]
                cost += row["cost"]
        return {
            "rows": rows,
            "products": len(self.product_ids),
            "weight_kg": round(weight, 3),
            "cost": round(cost, 2),
            "can_write": self.has_access("write"),
        }

    def _konstr_record(self, key):
        kind, record_id = _parse_key(key)
        if kind == PRODUCT:
            record = self.product_ids.filtered(lambda p: p.id == record_id)
        elif kind == DETAIL:
            record = self.product_ids.line_ids.filtered(lambda l: l.id == record_id)
        else:
            record = None
        if not record:
            raise UserError(_("Строка не найдена — таблица обновится."))
        return kind, record

    # ─── распознавание наименования ─────────────────────────────────────
    @api.model
    def _konstr_resolve(self, text, grade_text=""):
        """Наименование → вид детали и позиция справочника (как у Бутика). grade_text — ячейка
        «Марка»: у метиза там класс («кл. 8.8») и покрытие (26.10.2026)."""
        vals = {"profile_id": False, "sheet_id": False, "fastener_id": False, "paint_id": False}
        info = parse.classify(text)
        if info["kind"] == "coating":
            found = self.env["pmk.paint.coating"].name_search(parse.coating_query(text), limit=1)
            vals.update(calc_mode="paint", paint_id=found[0][0] if found else False)
            um = parse.coating_um(text)
            if um:
                vals["paint_thickness_um"] = um
        elif info["kind"] == "sheet" and info["thickness"]:
            found = self.env["pmk.metal.sheet"].name_search(parse.sheet_query(text, info["thickness"]), limit=1)
            vals.update(calc_mode="sheet", sheet_id=found[0][0] if found else False)
            if info["width"]:
                vals["a_mm"] = info["width"]
            if info["length"]:
                vals["b_mm"] = info["length"]
        elif info["kind"] == "piece":
            found = self.env["pmk.metal.fastener"]._pmk_resolve("%s %s" % (parse.piece_query(text), grade_text or ""))
            vals.update(calc_mode="fastener", fastener_id=found.id or False)
        elif info["kind"] != "empty":
            found = self.env["pmk.metal.profile"].name_search(text, limit=1)
            vals.update(calc_mode="linear", profile_id=found[0][0] if found else False)
        return vals

    @api.model
    def _konstr_grade(self, text):
        """Марка из ячейки → справочник марок. Точное имя — марка как есть; иначе —
        словарь написаний прайсов (Антон 25.10.2026: «С345 считаем как 09Г2С»,
        «ст3», «С255» → Ст3сп): цена — по марке справочника, а в ячейке остаётся
        то, что вписали (С345). Не опознана — только текст, цена самая дешёвая."""
        text = (text or "").strip()
        if not text:
            return {"grade_id": False, "pmk_grade_text": False}
        Grade = self.env["pmk.metal.grade"]
        norm = text.replace(" ", "").lower()
        grade = Grade.search([("name", "=ilike", text)], limit=1) or Grade.search([]).filtered(
            lambda g: (g.name or "").replace(" ", "").lower() == norm)[:1]
        if grade:
            return {"grade_id": grade.id, "pmk_grade_text": False}
        mapped = grades.map_grade(text)
        grade = Grade.search([("name", "=", mapped)], limit=1) if mapped else Grade
        return {"grade_id": grade.id or False, "pmk_grade_text": text}

    def _konstr_detail_vals(self, line, clean, product=None):
        """Правка ячеек детали → поля строки расчёта."""
        vals = {}
        product = product or (line.product_id if line else None)
        # №307: масса по КМ — ячейка «Вес всего» (на все изделия) или «…кг / …т» в
        # короткой записи. В строке храним на одно изделие. Вписали длину или
        # ширину руками — деталь снова считается по размерам.
        mass = clean.get("mass", clean.get("mass_kg"))
        if mass is not None:
            total = _to_float(mass)
            vals["pmk_mass_kg"] = total / (product.qty or 1) if (total and product) else total
        elif "length_mm" in clean or "width" in clean:
            if line and line.pmk_mass_kg:
                vals["pmk_mass_kg"] = 0.0
        if "pos" in clean:
            vals["detail_name"] = (clean["pos"] or "").strip() or False
        grade_cell = clean["grade"] if "grade" in clean else ((line.pmk_grade_text or "") if line else "")
        if "name" in clean:
            text = (clean["name"] or "").strip()
            vals["pmk_text"] = text or False
            vals.update(self._konstr_resolve(text, grade_cell))
        elif "grade" in clean and line and line.calc_mode == "fastener":
            # Поменяли класс / покрытие у метиза — другая позиция и цена.
            vals.update(self._konstr_resolve(line.pmk_text or line.fastener_id.name or "", grade_cell))
        mode = vals.get("calc_mode") or (line.calc_mode if line else "linear")
        if "width" in clean and mode == "sheet":
            vals["a_mm"] = _to_float(clean["width"])
        if "length_mm" in clean:
            length = _to_float(clean["length_mm"])
            if mode == "sheet":
                vals["b_mm"] = length
            elif mode == "linear":
                vals["length_mm"] = length
        if "qty" in clean and mode != "paint":
            vals["qty"] = max(1, int(round(_to_float(clean["qty"]) or 1)))
        if "grade" in clean:
            vals.update(self._konstr_grade(clean["grade"]))
        if "metal_ton" in clean:
            # №314: цена металла за тонну, когда позиции нет в прайсах (сотрите — снова «нет цены»).
            vals["pmk_manual_price_ton"] = _to_float(clean["metal_ton"])
        # Лист «по КМ» — размеры не нужны (старые после смены записи не мешали бы
        # в «Подробно» и вкладке «Металл»).
        if vals.get("pmk_mass_kg") and (vals.get("calc_mode") or (line.calc_mode if line else "")) == "sheet":
            vals.update(a_mm=0.0, b_mm=0.0)
        # Сменился вид — размеры чужого вида не оставляем (как onchange расчёта).
        if "calc_mode" in vals and line and vals["calc_mode"] != line.calc_mode:
            if vals["calc_mode"] != "sheet":
                vals.setdefault("a_mm", 0.0)
                vals.setdefault("b_mm", 0.0)
            if vals["calc_mode"] != "linear":
                vals["length_mm"] = 0.0
            if vals["calc_mode"] == "paint":
                vals["qty"] = 1
        return vals

    # ─── правка ─────────────────────────────────────────────────────────
    def konstr_save_row(self, row_key, vals):
        """Правка ячейки (или новая деталь: row_key = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        allowed = {"pos", "name", "product_qty", "length_mm", "qty", "grade", "width", "price",
                   "price_ton", "metal_ton", "mass"}
        clean = {k: v for k, v in (vals or {}).items() if k in allowed}
        if not row_key:
            self._konstr_insert([clean], (vals or {}).get("after_id"))
            return self.konstr_rows()
        kind, record = self._konstr_record(row_key)
        if kind == PRODUCT:
            pvals = {}
            if "name" in clean:
                name = (clean["name"] or "").strip()
                pvals["name"] = _("Сам ты лох") if _EASTER_RE.match(name) else (name or record.name)
            if "product_qty" in clean:
                pvals["qty"] = max(1, int(_to_float(clean["product_qty"]) or 1))
            if "price" in clean and "price_customer_unit" in record._fields:
                pvals["price_customer_unit"] = _to_float(clean["price"])
            if "price_ton" in clean and "pmk_price_ton" in record._fields:
                pvals["pmk_price_ton"] = _to_float(clean["price_ton"])
            if pvals:
                record.write(pvals)
        else:
            if clean.get("name"):
                # Короткая запись «д1 шв10 1200мм 10шт 09г» — пустые колонки из неё.
                # Масса («…кг», «…т», №307) — из набранного, до замены наименования.
                mass = (parse.decode_for_cell(clean["name"]) or {}).get("mass_kg")
                decoded = _decoded(clean["name"])
                if "sheet_width_mm" in decoded:
                    decoded["width"] = decoded.pop("sheet_width_mm")
                clean.update(decoded)
                if mass:
                    clean["mass_kg"] = mass
            record.write(self._konstr_detail_vals(record, clean))
        return self.konstr_rows()

    def konstr_move_row(self, row_key, target_key, below):
        """№312: перетащить строку. Изделие — вместе с деталями (среди изделий), деталь — в изделие
        той строки, над/под которую её бросили (на изделие — первой деталью)."""
        self.ensure_one()
        self.check_access("write")
        kind, record = self._konstr_record(row_key)
        tkind, target = self._konstr_record(target_key)
        if record == target:
            return self.konstr_rows()
        if kind == PRODUCT:
            target_product = target if tkind == PRODUCT else target.product_id
            products = [p for p in self._konstr_products() if p != record]
            if target_product == record:
                return self.konstr_rows()
            index = products.index(target_product) + (1 if below else 0)
            products.insert(index, record)
            for number, product in enumerate(products, 1):
                if product.sequence != number * 10:
                    product.sequence = number * 10
            return self.konstr_rows()
        product = target if tkind == PRODUCT else target.product_id
        siblings = [l for l in product.line_ids.sorted(lambda l: (l.sequence, l.id)) if l != record]
        if tkind == PRODUCT:
            index = 0
        else:
            index = siblings.index(target) + (1 if below else 0)
        siblings.insert(index, record)
        if record.product_id != product:
            record.product_id = product
        for number, line in enumerate(siblings, 1):
            if line.sequence != number * 10:
                line.sequence = number * 10
        return self.konstr_rows()

    def konstr_save_prices(self, prices):
        """№314: «Сохранить цены» — ручные цены за тонну пачкой {ключ детали: значение}
        (Антон 22.10.2026: цена не сохраняется сама — кнопкой или в окне «было → стало»)."""
        self.ensure_one()
        self.check_access("write")
        for key, value in (prices or {}).items():
            kind, record = self._konstr_record(key)
            if kind == DETAIL:
                record.write({"pmk_manual_price_ton": _to_float(value)})
        return self.konstr_rows()

    def _konstr_insert(self, cleans, after_key):
        """Новые детали после строки after_key: после изделия — первыми в нём,
        после детали — в том же изделии; без строки — в конце последнего изделия."""
        products = self._konstr_products()
        kind, anchor = (None, None)
        if after_key:
            kind, anchor = self._konstr_record(after_key)
        if kind == PRODUCT:
            product, siblings, index = anchor, anchor.line_ids.sorted(lambda l: (l.sequence, l.id)), 0
        elif kind == DETAIL:
            product = anchor.product_id
            siblings = product.line_ids.sorted(lambda l: (l.sequence, l.id))
            index = list(siblings).index(anchor) + 1
        else:
            product = products[-1:] or self.env["pmk.metal.spec.product"].create({
                "spec_id": self.id, "name": _("Изделие 1"), "qty": 1})
            siblings = product.line_ids.sorted(lambda l: (l.sequence, l.id))
            index = len(siblings)
        new_vals = []
        for clean in cleans:
            vals = {"product_id": product.id, "calc_mode": "linear", "qty": 1}
            vals.update(self._konstr_detail_vals(False, clean, product))
            new_vals.append(vals)
        created = self.env["pmk.metal.spec.line"].create(new_vals) if new_vals else self.env["pmk.metal.spec.line"]
        ordered = list(siblings[:index]) + list(created) + list(siblings[index:])
        for number, line in enumerate(ordered, 1):
            if line.sequence != number * 10:
                line.sequence = number * 10
        return created

    def konstr_insert_rows(self, after_key, rows):
        """Вставка блока из Excel: «№ | наименование | длина | кол-во | марка»."""
        self.ensure_one()
        self.check_access("write")
        cleans = []
        for row in rows or []:
            clean = {"pos": (row.get("pos") or "").strip(), "name": (row.get("name") or "").strip(),
                     "length_mm": row.get("length_mm") or "", "qty": row.get("qty") or "",
                     "grade": (row.get("grade") or "").strip()}
            decoded = _decoded(clean["name"])
            if "sheet_width_mm" in decoded:
                decoded["width"] = decoded.pop("sheet_width_mm")
            mass = (parse.decode_for_cell(clean["name"]) or {}).get("mass_kg")
            if mass:
                decoded["mass_kg"] = mass
            for key, value in decoded.items():
                if key == "name" or not clean.get(key):
                    clean[key] = value
            cleans.append({k: v for k, v in clean.items() if v not in ("", None)})
        target = None
        kind, record = _parse_key(after_key)
        if kind == DETAIL:
            _kind, target = self._konstr_record(after_key)
            if target.pmk_text or target._konstr_item() or target.detail_name:
                target = None
        self._konstr_insert(cleans, after_key)
        if target and cleans:
            # Вставили в пустую строку — она уступает место вставленному.
            target.unlink()
        return self.konstr_rows()

    def konstr_delete_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        _kind, record = self._konstr_record(row_key)
        record.unlink()
        return self.konstr_rows()

    def konstr_duplicate_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        kind, record = self._konstr_record(row_key)
        if kind == PRODUCT:
            record.action_pmk_copy()
        else:
            siblings = record.product_id.line_ids.filtered(lambda l, s=record: l.sequence > s.sequence)
            for other in siblings:
                other.sequence += 1
            record.copy({"product_id": record.product_id.id, "sequence": record.sequence + 1})
        return self.konstr_rows()

    def konstr_add_product(self):
        self.ensure_one()
        self.check_access("write")
        last = self._konstr_products()[-1:]
        product = self.env["pmk.metal.spec.product"].create({
            "spec_id": self.id, "name": _("Изделие %s") % (len(self.product_ids) + 1), "qty": 1,
            "sequence": (last.sequence or 0) + 10,
            "line_ids": [fields.Command.create({"calc_mode": "linear", "qty": 1})],
        })
        return self.konstr_rows()

    def konstr_set_position(self, row_key, key):
        """Позиция из подсказки (как в Бутике): прокат / лист / метиз / покрытие."""
        self.ensure_one()
        self.check_access("write")
        kind, line = self._konstr_record(row_key)
        if kind != DETAIL:
            raise UserError(_("Позиция выбирается у детали."))
        model, _sep, ident = (key or "").partition(":")
        mode = {"profile": "linear", "sheet": "sheet", "fastener": "fastener", "coating": "paint"}.get(model)
        if not mode or not ident.isdigit():
            raise UserError(_("Не понял позицию."))
        vals = {"profile_id": False, "sheet_id": False, "fastener_id": False, "paint_id": False,
                "calc_mode": mode, MODE_ITEM[mode]: int(ident)}
        if mode != "linear":
            vals["length_mm"] = 0.0
        if mode != "sheet":
            vals.update(a_mm=0.0, b_mm=0.0)
        if mode == "sheet" and not line.a_mm:
            info = parse.classify(line.pmk_text)
            if info["kind"] == "sheet" and info["width"]:
                vals["a_mm"] = info["width"]
        if mode == "paint":
            vals["qty"] = 1
            um = parse.coating_um(line.pmk_text)
            if um:
                vals["paint_thickness_um"] = um
        line.write(vals)
        return self.konstr_rows()
