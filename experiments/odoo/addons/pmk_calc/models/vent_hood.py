# -*- coding: utf-8 -*-
"""Вентзонты: заказ из нескольких размеров, развёртки для лазера (DXF),
чертёж заготовок (PNG) и спецификация на каждый размер.

Вся геометрия и все числа — в tools/vent_hood.py. Это генератор Антона,
перенесённый КАК ЕСТЬ, файл в файл (11.10.2026): правила сняты с 25 шаблонов
КОМПАС и сверены до 0.01 мм, по DXF режет лазер. Здесь формул нет — модель
только передаёт генератору размер шахты, толщину и цвет и показывает ответ.
Сверка переноса — тест test_vent_hood.py (51 эталон, tests/vent_hood_golden).
Правила меняются только в генераторе и только через его --regen и сверку с
шаблонами (README генератора, раздел 6). Чертёж — tools/vent_hood_drawing.py,
тоже как есть (единственная правка — запасной шрифт для сервера).

Толщина и цвет — из тех же справочников, что у доборки (решение Антона
11.10.2026: «справочник для доборки и вентзонтов один и тот же»): металл —
оцинкованный лист справочника «Лист», цвет — «Цвета доборки (RAL)».
Стандарт — лист 0,65 мм («толщина в стандарте 0,65 мм всегда»), цвет
выбирают всегда сами («цвет на выбор обязательно») — умолчания нет.
Толщина и цвет геометрию не меняют (DXF байт в байт тот же), меняют
материал, массу и предупреждения.
"""

import base64
import io
import re
import json
import os
import tempfile
import zipfile

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.pmk_calc.tools import vent_hood as V

STANDARD_THICKNESS = 0.65


def _num(value, digits=1):
    """Число по-русски: запятая, без хвостовых нулей до digits знаков."""
    text = ("%.*f" % (digits, value)).rstrip("0").rstrip(".")
    return escape(text.replace(".", ","))


class VentHoodOrder(models.Model):
    _name = "pmk.vent.hood.order"
    _description = "Заказ вентзонтов"
    _inherit = ["mail.thread"]
    _order = "order_date desc, id desc"
    # Архив (Антон 12.10.2026: демо-данные «просто всё убрать в архив»): снятый документ
    # не виден в списках и связях, вернуть — фильтр «Архив» → «Разархивировать».
    active = fields.Boolean("Активен", default=True)

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    partner_id = fields.Many2one("res.partner", "Контрагент", tracking=True)
    customer = fields.Char("Изделие / объект", tracking=True,
                           help="На какой объект (адрес, дом). Клиент — полем «Клиент».")
    order_date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    state = fields.Selection(
        [("draft", "Черновик"), ("confirmed", "В работе"), ("done", "Изготовлен")],
        "Статус", default="draft", tracking=True)
    line_ids = fields.One2many("pmk.vent.hood", "order_id", "Размеры", copy=True)

    total_positions = fields.Integer("Размеров", compute="_compute_totals", store=True)
    total_qty = fields.Integer("Зонтов, шт", compute="_compute_totals", store=True)
    total_sheet_1250_m = fields.Float("Лист 1250, пог. м", compute="_compute_totals",
                                      store=True, digits=(12, 2))
    total_mass_net_kg = fields.Float("Вес деталей, кг", compute="_compute_totals",
                                     store=True, digits=(12, 1))
    has_errors = fields.Boolean("Есть ошибки размеров", compute="_compute_totals", store=True)

    @api.depends("line_ids.qty", "line_ids.total_sheet_1250_m",
                 "line_ids.total_mass_net_kg", "line_ids.spec_error")
    def _compute_totals(self):
        for order in self:
            lines = order.line_ids
            order.total_positions = len(lines)
            order.total_qty = sum(lines.mapped("qty"))
            order.total_sheet_1250_m = sum(lines.mapped("total_sheet_1250_m"))
            order.total_mass_net_kg = sum(lines.mapped("total_mass_net_kg"))
            order.has_errors = any(lines.mapped("spec_error"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                # Код нумератора — с первой версии (там документ был один
                # на размер): запись noupdate, на бою уже создана.
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.vent.hood") or "Черновик"
        return super().create(vals_list)

    def _vh_good_lines(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.spec_json)
        if not lines:
            raise UserError("В заказе нет ни одного размера, по которому можно построить развёртку.")
        return lines

    def action_download_all(self):
        """ZIP: на каждый размер — DXF для лазера и чертёж PNG; сборочная ведомость."""
        lines = self._vh_good_lines()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for line in lines:
                zf.writestr(line._vh_dxf_name(), line._vh_dxf())
                zf.writestr(line._vh_png_name(), line._vh_png())
            zf.writestr(self._vh_assembly_name(), self._vh_assembly_xlsx())
        return self._vh_download(buf.getvalue(), "%s.zip" % self.name, "application/zip")

    def action_download_assembly(self):
        """Сборочная ведомость (Excel): зонты, их детали, лапки и клёпки, итог."""
        self._vh_good_lines()
        return self._vh_download(
            self._vh_assembly_xlsx(), self._vh_assembly_name(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def _vh_assembly_name(self):
        return "%s_сборка.xlsx" % self.name

    # Колонки ведомости. Ячейки зонта (№…Зонтов, лапки, клёпки) объединены на
    # высоту его деталей; «всего» — формулой от «на зонт» × «Зонтов, шт»,
    # чтобы правка количества в самом файле пересчитывала итог.
    # «Зонт, мм» — габарит самого зонта (длина × ширина шахты + свес 150 с
    # каждой стороны): так зонт записан в номенклатуре склада («Зонт 4960мм x
    # 1000мм (шахта: 4660мм x700мм)»), и по нему жестянщики сверяют
    # собранный зонт (Антон 11.10.2026). Первым столбцом.
    ASSEMBLY_COLS = [
        ("№", 4), ("Зонт, мм", 14), ("Шахта, мм", 14), ("Цвет", 20), ("Металл, мм", 10),
        ("Зонтов, шт", 9), ("Деталь", 18), ("Заготовка, мм", 16), ("Деталей на зонт", 10),
        ("Деталей всего", 10), ("Лапок на зонт", 9), ("Лапок всего", 9), ("Клёпок на зонт", 9),
        ("Клёпок всего", 9),
    ]

    def _vh_assembly_xlsx(self):
        self.ensure_one()
        lines = self._vh_good_lines()
        buf = io.BytesIO()
        book = xlsxwriter.Workbook(buf, {"in_memory": True})
        ws = book.add_worksheet("Сборка")
        border = {"border": 1, "valign": "vcenter"}
        f_title = book.add_format({"bold": True, "font_size": 14})
        f_info = book.add_format({})
        f_head = book.add_format(dict(border, bold=True, text_wrap=True, align="center",
                                      bg_color="#EDEDED"))
        f_text = book.add_format(dict(border))
        f_hood = book.add_format(dict(border, bold=True))
        f_int = book.add_format(dict(border, align="center"))
        f_mm = book.add_format(dict(border, num_format="0.00", align="center"))
        f_total_lbl = book.add_format(dict(border, bold=True, bg_color="#EDEDED"))
        f_total = book.add_format(dict(border, bold=True, align="center", bg_color="#EDEDED"))
        f_warn = book.add_format({"italic": True, "font_color": "#9C5700"})

        for col, (_title, width) in enumerate(self.ASSEMBLY_COLS):
            ws.set_column(col, col, width)
        ws.write(0, 0, "Сборочная ведомость вентзонтов — заказ %s" % self.name, f_title)
        info = [("Контрагент", self.partner_id.display_name or "—"),
                ("Изделие / объект", self.customer or "—"),
                ("Дата", self.order_date.strftime("%d.%m.%Y") if self.order_date else "—")]
        for i, (label, value) in enumerate(info, start=1):
            ws.write(i, 0, "%s: %s" % (label, value), f_info)
        row = len(info) + 2
        ws.set_row(row, 32)
        for col, (title, _width) in enumerate(self.ASSEMBLY_COLS):
            ws.write(row, col, title, f_head)
        ws.freeze_panes(row + 1, 0)
        row += 1
        first = row

        def cell(r, c):
            return xl_rowcol_to_cell(r, c)

        def merged(r0, r1, c, value, fmt, formula=None):
            if formula:
                if r1 > r0:
                    ws.merge_range(r0, c, r1, c, "", fmt)
                ws.write_formula(r0, c, formula, fmt, value)
            elif r1 > r0:
                ws.merge_range(r0, c, r1, c, value, fmt)
            else:
                ws.write(r0, c, value, fmt)

        C = {title: i for i, (title, _w) in enumerate(self.ASSEMBLY_COLS)}
        totals = {"qty": 0, "lapki": 0, "klepki": 0}
        for n, line in enumerate(lines, start=1):
            spec = line._vh_spec()
            parts = spec["parts"]
            top, bottom = row, row + len(parts) - 1
            qty = line.qty or 0
            merged(top, bottom, C["№"], n, f_int)
            merged(top, bottom, C["Зонт, мм"], line.hood_size or "", f_hood)
            merged(top, bottom, C["Шахта, мм"], line.shaft_size or "", f_text)
            merged(top, bottom, C["Цвет"], line.coating_id.name or "", f_text)
            merged(top, bottom, C["Металл, мм"], line.thickness or 0.0, f_mm)
            merged(top, bottom, C["Зонтов, шт"], qty, f_int)
            q = cell(top, C["Зонтов, шт"])
            for i, part in enumerate(parts):
                r = top + i
                ws.write(r, C["Деталь"], part["name"], f_text)
                ws.write(r, C["Заготовка, мм"], "%s × %s" % (
                    str(_num(part["size_mm"][0])), str(_num(part["size_mm"][1]))), f_text)
                ws.write(r, C["Деталей на зонт"], part["qty"], f_int)
                ws.write_formula(r, C["Деталей всего"], "=%s*%s" % (cell(r, C["Деталей на зонт"]), q),
                                 f_int, part["qty"] * qty)
            merged(top, bottom, C["Лапок на зонт"], spec["lapki"], f_int)
            merged(top, bottom, C["Лапок всего"], spec["lapki"] * qty, f_int,
                   "=%s*%s" % (cell(top, C["Лапок на зонт"]), q))
            merged(top, bottom, C["Клёпок на зонт"], spec["klepki"], f_int)
            merged(top, bottom, C["Клёпок всего"], spec["klepki"] * qty, f_int,
                   "=%s*%s" % (cell(top, C["Клёпок на зонт"]), q))
            totals["qty"] += qty
            totals["lapki"] += spec["lapki"] * qty
            totals["klepki"] += spec["klepki"] * qty
            row = bottom + 1
        last = row - 1

        ws.merge_range(row, 0, row, C["Металл, мм"], "ИТОГО", f_total_lbl)
        for title, key in (("Зонтов, шт", "qty"), ("Лапок всего", "lapki"), ("Клёпок всего", "klepki")):
            ws.write_formula(row, C[title], "=SUM(%s:%s)" % (cell(first, C[title]), cell(last, C[title])),
                             f_total, totals[key])
        for title in ("Деталь", "Заготовка, мм", "Деталей на зонт", "Деталей всего",
                      "Лапок на зонт", "Клёпок на зонт"):
            ws.write_blank(row, C[title], None, f_total)
        row += 1
        skipped = self.line_ids - lines
        for line in skipped:
            row += 1
            ws.write(row, 0, "Не вошёл: %s — %s" % (line.display_name, line.spec_error or "размер не задан"),
                     f_warn)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(len(info) + 2)
        book.close()
        return buf.getvalue()

    def _vh_stamp(self):
        """Дата и время создания файла для имени: «12.10.26_14-35» по поясу пользователя.
        Двоеточия нет — его не пускает Windows (Антон 12.10.2026: в «Загрузках» копились
        одноимённые ведомости и архивы, не понять, какой свежий)."""
        return fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%d.%m.%y_%H-%M")

    def _vh_download(self, data, fname, mimetype, stamp=True):
        """Файл во вложения записи и скачать. stamp — дата и время в имени
        («ВЗ-00002_сборка_12.10.26_14-35.xlsx»); прежний файл того же вида (то же имя с
        любой датой или без) заменяется. DXF — без даты: по имени DXF CypCut называет
        детали, а раскрой узнаёт размер (vsh_ШxД_tТОЛЩ_ЦВЕТ.dxf)."""
        self.ensure_one()
        base, ext = os.path.splitext(fname)
        name = "%s_%s%s" % (base, self._vh_stamp(), ext) if stamp else fname
        same = re.compile(r"^%s(_\d\d\.\d\d\.\d\d_\d\d-\d\d)?%s$" % (re.escape(base), re.escape(ext)))
        Attachment = self.env["ir.attachment"]
        Attachment.search([("res_model", "=", self._name), ("res_id", "=", self.id),
                           ("name", "=like", base + "%")]).filtered(lambda a: same.match(a.name)).unlink()
        att = Attachment.create({"name": name, "raw": data, "mimetype": mimetype,
                                 "res_model": self._name, "res_id": self.id})
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/web/content/%s?download=true" % att.id}


class VentHood(models.Model):
    """Строка заказа: один размер шахты × количество."""

    _name = "pmk.vent.hood"
    _description = "Вентзонт (размер в заказе)"
    _order = "order_id, sequence, id"

    order_id = fields.Many2one("pmk.vent.hood.order", "Заказ", required=True,
                               ondelete="cascade", index=True)
    sequence = fields.Integer("№", default=10)

    width = fields.Integer(
        "Ширина шахты, мм",
        help="Короткая сторона шахты: в обозначении «вш Ш×Д» Ш ≤ Д, конёк идёт "
             "вдоль длинной стороны.")
    length = fields.Integer("Длина шахты, мм")
    qty = fields.Integer("Количество, шт", default=1)

    # Тот же справочник и тот же отбор, что у доборки (pmk.dobor.order.line):
    # только оцинковка. Толщина приходит из металла.
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Металл",
        # Выбирают толщину оцинковки; RAL сам переводит на «Окрашенный» (sheet_coating.py).
        domain=[("sheet_type", "=", "Оцинкованный")],
        default=lambda self: self._default_sheet(),
        help="Оцинкованный лист из справочника «Лист» — тот же список, что у доборки. "
             "Стандарт — 0,65 мм.")
    thickness = fields.Float("Толщина, мм", related="sheet_id.thickness_mm", store=True,
                             digits=(6, 2))
    sves = fields.Integer(
        "Свес торцов, мм", default=150, required=True,
        help="Стандарт — 150. Меньше (до 125 по СНиП) — только по решению инженера: обычно его "
             "выбирают во вкладке «Раскрой», и он применяется к заказу. От свеса зависят заготовки, "
             "ведомость, DXF, чертёж и габарит зонта.")
    coating_id = fields.Many2one(
        "pmk.dobor.coating", "Цвет", required=True,
        help="Цинк или RAL — справочник «Цвета доборки (RAL)», общий с доборкой. "
             "Выбирается всегда: умолчания нет.")

    # Ответ генератора. Хранится: список и итоги считаются без генератора.
    spec_json = fields.Text("Спецификация (JSON)", compute="_compute_spec", store=True)
    spec_error = fields.Char("Ошибка размера", compute="_compute_spec", store=True)
    hood_label = fields.Char("Зонт", compute="_compute_spec", store=True)
    material_name = fields.Char("Материал", compute="_compute_spec", store=True)
    panels = fields.Integer("Панелей", compute="_compute_spec", store=True)
    layout = fields.Char("Раскладка", compute="_compute_spec", store=True)
    lapki = fields.Integer("Лапок на зонт", compute="_compute_spec", store=True)
    klepki = fields.Integer("Клёпок на зонт", compute="_compute_spec", store=True)
    metal_net_m2 = fields.Float("Металл нетто, м²", compute="_compute_spec", store=True,
                                digits=(12, 3))
    sheet_1250_m = fields.Float("Лист 1250, пог. м", compute="_compute_spec", store=True,
                                digits=(12, 2))
    mass_net_kg = fields.Float("Вес деталей, кг", compute="_compute_spec", store=True,
                               digits=(12, 1))
    mass_sheet_kg = fields.Float("Вес листа по расходу, кг", compute="_compute_spec",
                                 store=True, digits=(12, 1))
    total_mass_net_kg = fields.Float("Вес деталей всего, кг", compute="_compute_spec",
                                     store=True, digits=(12, 1))
    total_sheet_1250_m = fields.Float("Лист 1250 всего, пог. м", compute="_compute_spec",
                                      store=True, digits=(12, 2))

    # Габарит зонта и шахты «длина × ширина» — как в номенклатуре склада:
    # «Зонт 4960мм x 1000мм (шахта: 4660мм x700мм)». Зонт = шахта + свес
    # генератора (V.SVES, 150 мм) с каждой стороны.
    hood_size = fields.Char("Зонт, мм", compute="_compute_sizes")
    shaft_size = fields.Char("Шахта, мм", compute="_compute_sizes")
    subtitle = fields.Char("Зонт и материал", compute="_compute_subtitle")
    spec_html = fields.Html("Детали", compute="_compute_spec_html", sanitize=False)
    warnings_text = fields.Text("Предупреждения", compute="_compute_spec_html")
    # Чертёж — в окне размера, строится при открытии (≈0,3 с); не хранится:
    # он целиком следует из размера, толщины и цвета.
    drawing_png = fields.Binary("Чертёж заготовок", compute="_compute_drawing")

    # Конёк зонта всегда вдоль длинной стороны шахты (так сделаны все 25
    # шаблонов КОМПАС; решение Антона 11.10.2026: другого зонта не бывает),
    # и генератор принимает «вш Ш×Д» только с Ш ≤ Д. Шахта 1200×900 — та же
    # шахта, что 900×1200: стороны переставляем сами, генератор не трогаем.
    sides_swapped = fields.Boolean(
        "Стороны переставлены",
        help="Ввели ширину больше длины — меньшая сторона поставлена первой: "
             "конёк идёт вдоль длинной стороны.")

    def _default_sheet(self):
        return self.env["pmk.metal.sheet"].search(
            [("sheet_type", "=", "Оцинкованный"), ("thickness_mm", "=", STANDARD_THICKNESS)],
            limit=1).id

    @staticmethod
    def _vh_sides(vals, width, length):
        """vals с меньшей стороной в «Ширине» (и отметкой), если ввели наоборот."""
        if width and length and 0 < length < width:
            return dict(vals, width=length, length=width, sides_swapped=True)
        if "width" in vals or "length" in vals:
            return dict(vals, sides_swapped=False)
        return vals

    @api.onchange("width", "length")
    def _onchange_sides(self):
        for rec in self:
            if rec.width and rec.length and 0 < rec.length < rec.width:
                rec.width, rec.length = rec.length, rec.width
                rec.sides_swapped = True

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._vh_sides(vals, vals.get("width"), vals.get("length"))
                     for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        if "width" not in vals and "length" not in vals:
            return super().write(vals)
        for rec in self:
            fixed = self._vh_sides(dict(vals), vals.get("width", rec.width),
                                   vals.get("length", rec.length))
            if vals.get("sides_swapped") and not fixed.get("sides_swapped"):
                # Отметку поставил onchange в форме (стороны уже переставлены).
                fixed["sides_swapped"] = True
            super(VentHood, rec).write(fixed)
        return True

    # ── генератор ────────────────────────────────────────────────────────

    def _vh_color(self):
        """Цвет для генератора: None — оцинковка, иначе код RAL."""
        self.ensure_one()
        return (self.coating_id.ral_code or "").strip() or None

    def _vh_thickness(self):
        self.ensure_one()
        return self.thickness or None

    @api.constrains("sves")
    def _check_sves(self):
        for rec in self:
            if not (V.SVES_MIN <= rec.sves <= V.SVES):
                raise ValidationError("Свес торцов — от %d до %d мм (%s)." % (
                    V.SVES_MIN, V.SVES, rec.display_name))

    def _vh_sves(self):
        return float(self.sves or V.SVES)

    def _vh_geometry(self):
        """hood() генератора; ValueError — размер невозможен (Ш > Д, ≤ 0) или свес вне 125…150."""
        self.ensure_one()
        return V.hood(self.width, self.length, self._vh_sves())

    def _vh_spec(self):
        self.ensure_one()
        return json.loads(self.spec_json) if self.spec_json else {}

    def _vh_checked_geometry(self):
        self.ensure_one()
        if not self.width or not self.length:
            raise UserError("Укажите ширину и длину шахты.")
        try:
            return self._vh_geometry()
        except ValueError as e:
            raise UserError("Размер %s×%s не подходит: %s" % (self.width, self.length, e)) from None

    def _vh_dxf_name(self):
        return V.out_name(self.width, self.length, self._vh_thickness(), self._vh_color())

    def _vh_png_name(self):
        return self._vh_dxf_name()[:-4] + "_чертёж.png"

    def _vh_dxf(self):
        return V.to_dxf(self._vh_checked_geometry()).encode("utf-8")

    def _vh_dxf_standard(self):
        """DXF при стандартном свесе 150 — вход раскроя: пакет сверяет DXF заказа со своим
        генератором при 150 и уменьшенный свес применяет сам (pmk_vent_nest)."""
        self._vh_checked_geometry()
        return V.to_dxf(V.hood(self.width, self.length)).encode("utf-8")

    def _vh_png(self):
        """Чертёж заготовок генератора (vent_hood_drawing.main пишет в файл)."""
        self._vh_checked_geometry()
        from odoo.addons.pmk_calc.tools import vent_hood_drawing as D
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            D.main(self.width, self.length, path, self._vh_thickness(), self._vh_color(),
                   sves=None if self._vh_sves() == V.SVES else self._vh_sves())
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            os.unlink(path)

    @api.depends("width", "length", "qty", "thickness", "coating_id.ral_code", "sves")
    def _compute_spec(self):
        empty = dict(spec_json=False, hood_label=False, material_name=False, panels=0,
                     layout=False, lapki=0, klepki=0, metal_net_m2=0.0, sheet_1250_m=0.0,
                     mass_net_kg=0.0, mass_sheet_kg=0.0, total_mass_net_kg=0.0,
                     total_sheet_1250_m=0.0)
        for rec in self:
            rec.update(dict(empty, spec_error=False))
            if not rec.width or not rec.length:
                continue
            try:
                g = rec._vh_geometry()
                s = V.spec(g, rec._vh_thickness(), rec._vh_color())
            except ValueError as e:
                rec.spec_error = str(e)
                continue
            qty = rec.qty or 0
            rec.update({
                "spec_json": json.dumps(s, ensure_ascii=False),
                "hood_label": s["hood"],
                "material_name": s["material"]["full_name"],
                "panels": s["panels"],
                "layout": s["layout"],
                "lapki": s["lapki"],
                "klepki": s["klepki"],
                "metal_net_m2": s["metal_net_m2"],
                "sheet_1250_m": s["sheet_1250_m"],
                "mass_net_kg": s.get("mass_net_kg", 0.0),
                "mass_sheet_kg": s.get("mass_sheet_kg", 0.0),
                "total_mass_net_kg": s.get("mass_net_kg", 0.0) * qty,
                "total_sheet_1250_m": s["sheet_1250_m"] * qty,
            })

    @api.depends("width", "length", "spec_json", "sves")
    def _compute_sizes(self):
        for rec in self:
            if rec.spec_json:
                sves = 2 * int(round(rec._vh_sves()))
                rec.hood_size = "%d × %d" % (rec.length + sves, rec.width + sves)
                rec.shaft_size = "%d × %d" % (rec.length, rec.width)
            else:
                rec.hood_size = rec.shaft_size = False

    @api.depends("hood_label", "material_name")
    def _compute_subtitle(self):
        for rec in self:
            rec.subtitle = " · ".join(filter(None, [rec.hood_label, rec.material_name])) or False

    @api.depends("spec_json", "spec_error", "qty")
    def _compute_spec_html(self):
        for rec in self:
            s = rec._vh_spec()
            if not s:
                rec.spec_html = False
                rec.warnings_text = False
                continue
            qty = rec.qty or 0
            rows = Markup("").join(
                Markup("<tr><td>%s</td><td class='text-end'>%s × %s</td>"
                       "<td class='text-end'>%s</td><td class='text-end'>%s</td>"
                       "<td class='text-end'>%s</td></tr>") % (
                    p["name"], _num(p["size_mm"][0]), _num(p["size_mm"][1]), p["qty"],
                    p["qty"] * qty, _num(p["area_m2_each"], 4))
                for p in s["parts"])
            head = Markup(
                "<thead><tr><th>Деталь</th><th class='text-end'>Заготовка, мм</th>"
                "<th class='text-end'>На зонт, шт</th><th class='text-end'>Всего, шт</th>"
                "<th class='text-end'>Площадь шт, м²</th></tr></thead>")
            rec.spec_html = Markup(
                "<table class='table table-sm o_pmk_vh_parts'>%s<tbody>%s</tbody></table>"
            ) % (head, rows)
            rec.warnings_text = "\n".join(s["rule_flags"] + s["material"]["warnings"]) or False

    @api.depends("spec_json")
    def _compute_drawing(self):
        for rec in self:
            # Binary вне вложений хранит base64 — так его ждёт виджет картинки.
            rec.drawing_png = base64.b64encode(rec._vh_png()) if rec.spec_json else False

    @api.depends("hood_label", "width", "length")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.hood_label or "Размер %s×%s" % (rec.width or "?", rec.length or "?")

    # ── действия ─────────────────────────────────────────────────────────

    def action_open_line(self):
        """Окно размера поверх заказа: детали, предупреждения, чертёж."""
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "views": [(self.env.ref("pmk_calc.view_vent_hood_form").id, "form")],
                "target": "new", "name": self.display_name}

    def action_download_dxf(self):
        """DXF развёрток для лазера — во вложения заказа и сразу скачать."""
        self.ensure_one()
        return self.order_id._vh_download(self._vh_dxf(), self._vh_dxf_name(), "application/dxf", stamp=False)

    def action_download_png(self):
        """Чертёж заготовок с размерами и спецификацией (PNG)."""
        self.ensure_one()
        return self.order_id._vh_download(self._vh_png(), self._vh_png_name(), "image/png")
