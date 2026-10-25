# -*- coding: utf-8 -*-
"""Бутик — спецификация таблицей, как её пишет Бутов в Excel (15.10.2026).

Расчёт (БТ-…) — строки по порядку: строка изделия (название, количество изделий) и
под ней строки деталей (№ поз., наименование, длина, на 1 шт, марка). Таблица на
экране — виджет pmk_butik_grid (static/src/js/butik_grid.js); он говорит с сервером
методами butik_* ниже и после каждой правки получает таблицу целиком (строк — десятки).

Наименование распознаётся при записи: лист / метиз / прокат (tools/parse.py), позиция —
умным поиском справочников pmk_calc (name_search проката и листа, size_search.py), метиз
— поиском справочника метизов. Выбор из подсказки — «вручную»: дальше правка
наименования позицию не переопределяет, пока его не сотрут.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import parse

KINDS = [("product", "Изделие"), ("detail", "Деталь")]
MATCH = [("auto", "Найдено"), ("manual", "Выбрано"), ("none", "Нет в справочнике"), ("empty", "Пусто"),
         ("coating", "Покрытие")]
DECODED = ("pos", "name", "length_mm", "qty", "grade")


def _r1(value):
    return round(value or 0.0, 3)


class ButikSpec(models.Model):
    _name = "pmk.butik.spec"
    _description = "Бутик: спецификация"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    subject = fields.Char("Заказ", help="Как в шапке файла Бутова: «Заказчик, спец./счёт №».")
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    lead_id = fields.Many2one(
        "crm.lead", "Сделка", tracking=True, domain=[("type", "=", "opportunity")],
        help="К какой сделке относится расчёт. Основной расчёт сделки этим не меняется.")
    note = fields.Text("Примечание")
    line_ids = fields.One2many("pmk.butik.line", "spec_id", "Строки", copy=True)
    product_count = fields.Integer("Изделий", compute="_compute_totals")
    detail_count = fields.Integer("Деталей", compute="_compute_totals")
    weight_kg = fields.Float("Металл, кг", compute="_compute_totals", digits=(12, 1))
    weight_t = fields.Float("Общий вес, т", compute="_compute_totals", digits=(12, 3))

    @api.depends("line_ids.kind", "line_ids.name", "line_ids.weight_total")
    def _compute_totals(self):
        for spec in self:
            lines = spec.line_ids
            spec.product_count = len(lines.filtered(lambda l: l.kind == "product"))
            spec.detail_count = len(lines.filtered(lambda l: l.kind == "detail" and l.name))
            spec.weight_kg = sum(lines.mapped("weight_total"))
            spec.weight_t = spec.weight_kg / 1000.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.butik.spec") or "Черновик"
        specs = super().create(vals_list)
        for spec in specs.filtered(lambda s: not s.line_ids):
            spec.line_ids = [
                fields.Command.create({"kind": "product", "sequence": 10, "name": "Изделие 1", "product_qty": 1}),
                fields.Command.create({"kind": "detail", "sequence": 20, "pos": "1"}),
            ]
        return specs

    @api.onchange("lead_id")
    def _onchange_lead_id(self):
        if self.lead_id.partner_id and not self.partner_id:
            self.partner_id = self.lead_id.partner_id.commercial_partner_id

    # ─── таблица для виджета ──────────────────────────────────────────────
    def _butik_ordered(self):
        self.ensure_one()
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))

    def action_butik_save(self):
        """Кнопка «Сохранить»: запись формы делает сам клиент перед вызовом."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": _("Расчёт %s сохранён") % self.name, "type": "success", "sticky": False},
        }

    def butik_rows(self):
        self.ensure_one()
        self.check_access("read")
        rows, products, number, head = [], 0, 0, None
        for line in self._butik_ordered():
            row = line._butik_row(number + 1 if line.kind == "product" else number)
            if line.kind == "product":
                products += 1
                number = products
                head = row
                row.update(weight_total=0.0, weight_one=0.0)
            else:
                # Строка изделия несёт вес своих деталей (Антон 16.10: «изделие в
                # строке не показывает вес итого»): всего и на одно изделие.
                row["parent"] = head["id"] if head else False
                if head:
                    head["weight_total"] = round(head["weight_total"] + row["weight_total"], 3)
                    head["weight_one"] = round(head["weight_total"] / (head["product_qty"] or 1), 3)
            rows.append(row)
        return {
            "rows": rows,
            "products": products,
            "weight_kg": _r1(sum(r["weight_total"] for r in rows if r["kind"] != "product")),
            "can_write": self.has_access("write"),
        }

    def _butik_renumber(self):
        for index, line in enumerate(self._butik_ordered(), 1):
            if line.sequence != index * 10:
                line.sequence = index * 10

    def butik_save_row(self, row_id, vals):
        """Правка ячейки (или новая строка, row_id = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        allowed = {"pos", "name", "product_qty", "length_mm", "qty", "grade", "kind", "width"}
        clean = {k: v for k, v in (vals or {}).items() if k in allowed}
        for key in ("product_qty",):
            if key in clean:
                clean[key] = int(float(clean[key] or 0))
        for key in ("length_mm", "qty"):
            if key in clean:
                clean[key] = _to_float(clean[key])
        if "width" in clean:
            clean["sheet_width_mm"] = _to_float(clean.pop("width"))
        line = self.line_ids.filtered(lambda l: l.id == row_id) if row_id else False
        if row_id and not line:
            raise UserError(_("Строка не найдена — таблица обновится."))
        if clean.get("name"):
            if line and line.kind == "product":
                # Название изделия — как написано (короткую запись деталей не
                # применять), кроме пасхалки (Антон 16.10).
                if _EASTER_RE.match(clean["name"]):
                    clean["name"] = "Сам ты лох"
            else:
                clean.update(_decoded(clean["name"]))
        if line:
            line.write(clean)
        else:
            self._butik_insert([dict({"kind": "detail"}, **clean)], (vals or {}).get("after_id"))
        return self.butik_rows()

    def butik_insert_rows(self, after_id, rows):
        """Вставка блока из Excel: строки «№ | наименование | длина | кол-во | марка»."""
        self.ensure_one()
        self.check_access("write")
        vals_list = []
        for row in rows or []:
            vals = {
                "kind": "detail", "pos": (row.get("pos") or "").strip(),
                "name": (row.get("name") or "").strip(), "length_mm": _to_float(row.get("length_mm")),
                "qty": _to_float(row.get("qty")), "grade": (row.get("grade") or "").strip(),
            }
            # Короткая запись в колонке наименования: пустые колонки — из неё.
            for key, value in _decoded(vals["name"]).items():
                if key == "name" or not vals.get(key):
                    vals[key] = value
            vals_list.append(vals)
        # Вставили в пустую строку — она уступает место вставленному.
        target = self.line_ids.filtered(lambda l: l.id == after_id)
        empty = target if (target and target.kind == "detail" and not target.name and not target.qty
                           and not target.length_mm and not target.grade) else False
        self._butik_insert(vals_list, after_id)
        if empty and vals_list:
            empty.unlink()
            self._butik_renumber()
        return self.butik_rows()

    def _butik_insert(self, vals_list, after_id):
        ordered = self._butik_ordered()
        anchor = ordered.filtered(lambda l: l.id == after_id)
        index = list(ordered).index(anchor) + 1 if anchor else len(ordered)
        base = (ordered[index - 1].sequence if index else 0)
        step = 1
        for offset, vals in enumerate(vals_list, 1):
            vals.update(spec_id=self.id, sequence=base + offset * step)
        # Освободить место: всё после вставки — дальше.
        for line in ordered[index:]:
            line.sequence += len(vals_list) + 1
        self.env["pmk.butik.line"].create(vals_list)
        self._butik_renumber()

    def butik_delete_row(self, row_id):
        self.ensure_one()
        self.check_access("write")
        self.line_ids.filtered(lambda l: l.id == row_id).unlink()
        self._butik_renumber()
        return self.butik_rows()

    def butik_move_row(self, row_id, target_id, below):
        """№312: перетащить строку. Изделие — вместе со своими деталями (до следующего изделия),
        деталь — одна, в изделие той строки, над/под которую её бросили."""
        self.ensure_one()
        self.check_access("write")
        lines = list(self.line_ids.sorted(lambda l: (l.sequence, l.id)))
        ids = [l.id for l in lines]
        if row_id not in ids or target_id not in ids or row_id == target_id:
            return self.butik_rows()

        def block(index):
            if lines[index].kind != "product":
                return index, index
            end = index + 1
            while end < len(lines) and lines[end].kind != "product":
                end += 1
            return index, end - 1

        a, b = block(ids.index(row_id))
        moving = lines[a:b + 1]
        rest = lines[:a] + lines[b + 1:]
        target = next(l for l in rest if l.id == target_id) if target_id not in [m.id for m in moving] else None
        if target is None:
            return self.butik_rows()
        t = rest.index(target)
        if moving[0].kind == "product" and target.kind != "product":
            # Изделие бросили на деталь — ставим относительно её изделия целиком.
            while t > 0 and rest[t].kind != "product":
                t -= 1
            if below:
                t += 1
                while t < len(rest) and rest[t].kind != "product":
                    t += 1
                rest[t:t] = moving
            else:
                rest[t:t] = moving
        else:
            rest[t + 1 if below else t:t + 1 if below else t] = moving
        for number, line in enumerate(rest, 1):
            if line.sequence != number * 10:
                line.sequence = number * 10
        return self.butik_rows()

    def butik_duplicate_row(self, row_id):
        self.ensure_one()
        self.check_access("write")
        line = self.line_ids.filtered(lambda l: l.id == row_id)
        if line:
            vals = line.copy_data()[0]
            vals.pop("spec_id", None)
            self._butik_insert([vals], line.id)
        return self.butik_rows()

    def butik_add_product(self):
        self.ensure_one()
        self.check_access("write")
        count = len(self.line_ids.filtered(lambda l: l.kind == "product"))
        self._butik_insert([
            {"kind": "product", "name": _("Изделие %s") % (count + 1), "product_qty": 1},
            {"kind": "detail", "pos": "1"},
        ], False)
        return self.butik_rows()

    @api.model
    def butik_suggest(self, query):
        """Подсказки наименования — умный поиск справочников (как в основной системе)."""
        query = (query or "").strip()
        if len(query) < 2:
            return []
        info = parse.classify(query)
        out = []
        Profile = self.env["pmk.metal.profile"]
        Sheet = self.env["pmk.metal.sheet"]
        Fastener = self.env["pmk.metal.fastener"]
        if info["kind"] == "sheet" and info["thickness"]:
            for rid, _label in Sheet.name_search(parse.sheet_query(query, info["thickness"]), limit=6):
                out.append({"key": "sheet:%d" % rid, "label": Sheet.browse(rid).display_name, "kind": "Лист"})
        if info["kind"] == "coating" or (parse.decode(query) or {}).get("kind") == "coating":
            Coating = self.env["pmk.paint.coating"]
            text = (parse.decode(query) or {}).get("name") or query
            for rid, _label in Coating.name_search(parse.coating_query(text), limit=6):
                out.append({"key": "coating:%d" % rid, "label": Coating.browse(rid).display_name, "kind": "Покрытие"})
            return out
        if info["kind"] == "piece":
            for rid, _label in Fastener.name_search(parse.piece_query(query), limit=8):
                out.append({"key": "fastener:%d" % rid, "label": Fastener.browse(rid).display_name, "kind": "Метиз"})
        if info["kind"] in ("linear", "piece"):
            for rid, _label in Profile.name_search(query, limit=8):
                out.append({"key": "profile:%d" % rid, "label": Profile.browse(rid).display_name, "kind": "Прокат"})
        if info["kind"] == "linear" and len(out) < 4:
            for rid, _label in Sheet.name_search(query, limit=4):
                out.append({"key": "sheet:%d" % rid, "label": Sheet.browse(rid).display_name, "kind": "Лист"})
        return out[:10]

    def butik_set_position(self, row_id, key):
        """Позиция из подсказки — «выбрано вручную»."""
        self.ensure_one()
        self.check_access("write")
        line = self.line_ids.filtered(lambda l: l.id == row_id)
        if not line:
            raise UserError(_("Строка не найдена — таблица обновится."))
        model, _sep, ident = (key or "").partition(":")
        vals = {"profile_id": False, "sheet_id": False, "fastener_id": False, "coating_id": False,
                "match_state": "manual"}
        field = {"profile": "profile_id", "sheet": "sheet_id", "fastener": "fastener_id",
                 "coating": "coating_id"}.get(model)
        if not field or not ident.isdigit():
            raise UserError(_("Не понял позицию."))
        vals[field] = int(ident)
        if field == "coating_id":
            vals.update(match_state="coating", coating_um=parse.coating_um(line.name))
        if field == "sheet_id" and not line.sheet_width_mm:
            info = parse.classify(line.name)
            if info["kind"] == "sheet" and info["width"]:
                vals["sheet_width_mm"] = info["width"]
        line.with_context(pmk_butik_keep=True).write(vals)
        return self.butik_rows()


# Пасхалка (Антон 16.10): изделие «бутик лох» → «Сам ты лох». Регистр, «ё» и
# лишние пробелы не важны.
_EASTER_RE = re.compile(r"^\s*бутик\s+лох\s*[!.)]*\s*$", re.IGNORECASE)


def _decoded(name):
    """«д1 шв10 1200мм 10шт 09г» → поля строки (см. parse.decode); обычная запись → {}."""
    dec = parse.decode_for_cell(name)
    if not dec:
        return {}
    vals = {k: dec[k] for k in DECODED if k in dec}
    if dec.get("width"):
        vals["sheet_width_mm"] = dec["width"]
    return vals


def _to_float(value):
    if value in (None, False, ""):
        return 0.0
    try:
        # Пробелы разрядов: обычный, неразрывный и узкий (так пишет Intl в ru-RU).
        return float(str(value).replace(",", ".").replace(" ", "").replace("\u00a0", "").replace("\u202f", ""))
    except ValueError:
        return 0.0


def _fmt(value):
    return ("%g" % value).replace(".", ",")


class ButikLine(models.Model):
    _name = "pmk.butik.line"
    _description = "Бутик: строка"
    _order = "sequence, id"

    spec_id = fields.Many2one("pmk.butik.spec", "Спецификация", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("Порядок", default=10)
    kind = fields.Selection(KINDS, "Строка", required=True, default="detail")
    pos = fields.Char("№ поз.")
    name = fields.Char("Наименование")
    product_qty = fields.Integer("Изделий, шт", default=1)
    length_mm = fields.Float("Длина, мм", digits=(12, 1))
    qty = fields.Float("На 1 шт", digits=(12, 2))
    grade = fields.Char("Марка")
    profile_id = fields.Many2one("pmk.metal.profile", "Прокат", ondelete="set null")
    sheet_id = fields.Many2one("pmk.metal.sheet", "Лист", ondelete="set null")
    fastener_id = fields.Many2one("pmk.metal.fastener", "Метиз", ondelete="set null")
    coating_id = fields.Many2one("pmk.paint.coating", "Покрытие", ondelete="set null")
    coating_um = fields.Float("Толщина покрытия, мкм", digits=(8, 1))
    sheet_width_mm = fields.Float("Ширина листовой детали, мм", digits=(12, 1))
    sheet_length_mm = fields.Float("Длина листовой детали из наименования, мм", digits=(12, 1))
    match_state = fields.Selection(MATCH, "Распознано", default="empty")
    qty_total = fields.Float("Всего", compute="_compute_weight", digits=(12, 2))
    weight_one = fields.Float("Вес 1 шт, кг", compute="_compute_weight", digits=(12, 3))
    weight_total = fields.Float("Вес всего, кг", compute="_compute_weight", digits=(12, 3))

    # ─── распознавание ───────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.filtered(lambda l: l.kind == "detail")._butik_resolve()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if "name" in vals and not self.env.context.get("pmk_butik_keep"):
            self.filtered(lambda l: l.kind == "detail")._butik_resolve(force="name" in vals)
        return result

    def _butik_resolve(self, force=False):
        Profile = self.env["pmk.metal.profile"]
        Sheet = self.env["pmk.metal.sheet"]
        Fastener = self.env["pmk.metal.fastener"]
        for line in self:
            if line.match_state == "manual" and not force:
                continue
            info = parse.classify(line.name)
            vals = {"profile_id": False, "sheet_id": False, "fastener_id": False, "coating_id": False,
                    "match_state": "none"}
            if info["kind"] == "empty":
                vals["match_state"] = "empty"
            elif info["kind"] == "coating":
                vals.update(coating_id=False, coating_um=parse.coating_um(line.name))
                found = self.env["pmk.paint.coating"].name_search(parse.coating_query(line.name), limit=1)
                if found:
                    vals.update(coating_id=found[0][0], match_state="coating")
            elif info["kind"] == "sheet" and info["thickness"]:
                found = Sheet.name_search(parse.sheet_query(line.name, info["thickness"]), limit=1)
                if found:
                    vals.update(sheet_id=found[0][0], match_state="auto")
                if info["width"]:
                    vals["sheet_width_mm"] = info["width"]
                if info["length"] and not line.length_mm:
                    vals["length_mm"] = info["length"]
            elif info["kind"] == "piece":
                found = Fastener.name_search(parse.piece_query(line.name), limit=1)
                if found:
                    vals.update(fastener_id=found[0][0], match_state="auto")
            else:
                found = Profile.name_search(line.name, limit=1)
                if found:
                    vals.update(profile_id=found[0][0], match_state="auto")
            super(ButikLine, line).write(vals)

    # ─── вес ─────────────────────────────────────────────────────────────
    def _butik_product_qty(self):
        """Изделий — у ближайшей строки изделия выше."""
        self.ensure_one()
        qty = 1
        for line in self.spec_id._butik_ordered():
            if line.kind == "product":
                qty = line.product_qty or 0
            if line == self:
                return qty
        return qty

    @api.depends("kind", "qty", "length_mm", "profile_id.mass_per_meter", "sheet_id.mass_per_sqm",
                 "fastener_id.weight_kg", "sheet_width_mm", "sheet_length_mm",
                 "spec_id.line_ids.product_qty", "spec_id.line_ids.sequence")
    def _compute_weight(self):
        for line in self:
            if line.kind != "detail":
                line.qty_total = line.weight_one = line.weight_total = 0.0
                continue
            total = (line.qty or 0.0) * line._butik_product_qty()
            one = 0.0
            if line.profile_id:
                one = (line.profile_id.mass_per_meter or 0.0) * (line.length_mm or 0.0) / 1000.0
            elif line.sheet_id:
                length = line.length_mm or line.sheet_length_mm or 0.0
                one = (line.sheet_id.mass_per_sqm or 0.0) * (line.sheet_width_mm or 0.0) * length / 1e6
            elif line.fastener_id:
                one = line.fastener_id.weight_kg or 0.0
            line.qty_total = total
            line.weight_one = one
            line.weight_total = one * total

    def _butik_label(self):
        self.ensure_one()
        if self.profile_id:
            return "%s · %s кг/м" % (self.profile_id.display_name, _fmt(round(self.profile_id.mass_per_meter or 0, 3)))
        if self.sheet_id:
            length = self.length_mm or self.sheet_length_mm
            return "%s · %s×%s мм" % (self.sheet_id.display_name,
                                      _fmt(self.sheet_width_mm) if self.sheet_width_mm else "? ширина",
                                      _fmt(length) if length else "? длина")
        if self.fastener_id:
            return "%s · метиз" % self.fastener_id.display_name
        if self.coating_id:
            return self._butik_coating_label()
        if self.match_state == "none":
            return _("нет в справочнике — выберите из подсказки")
        return ""

    def _butik_coating_label(self):
        """«Грунт ГФ-021 · 0,1 кг/м² при 20 мкм → 0,3 кг/м² при 60 мкм» — расход
        справочника, пересчитанный на толщину заказчика (Антон 16.10: пригодится для
        расчёта краски; площадь деталей — следующим шагом)."""
        coat = self.coating_id
        text = "%s · %s кг/м² при %s мкм" % (coat.name, _fmt(round(coat.consumption, 3)),
                                             _fmt(coat.base_thickness_um))
        if self.coating_um and coat.base_thickness_um and self.coating_um != coat.base_thickness_um:
            need = coat.consumption * self.coating_um / coat.base_thickness_um
            text += " → %s кг/м² при %s мкм" % (_fmt(round(need, 3)), _fmt(self.coating_um))
        return text

    def _butik_row(self, product_number):
        self.ensure_one()
        return {
            "id": self.id,
            "kind": self.kind,
            "number": product_number,
            "pos": self.pos or "",
            "name": self.name or "",
            "product_qty": self.product_qty or 0,
            "length_mm": self.length_mm or 0.0,
            "width": self.sheet_width_mm or 0.0,
            "is_sheet": bool(self.sheet_id) or parse.classify(self.name)["kind"] == "sheet",
            "qty": self.qty or 0.0,
            "grade": self.grade or "",
            "qty_total": self.qty_total,
            # метиз весит граммы — не округлять до 0,1 кг
            "weight_one": round(self.weight_one, 4),
            "weight_total": round(self.weight_total, 3),
            "match_state": self.match_state,
            "label": self._butik_label() if self.kind == "detail" else "",
        }


class PmkButikSpecFlowCount(models.Model):
    """«Связи · N» в заголовке вкладки (шапка «вариант А», 25.10.2026, pmk_flow)."""
    _name = "pmk.butik.spec"
    _inherit = ["pmk.butik.spec", "pmk.flow.count.mixin"]
