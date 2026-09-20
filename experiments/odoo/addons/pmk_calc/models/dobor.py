# -*- coding: utf-8 -*-
"""Доборные элементы: развёртка, вес, расход металла.

Перенос с ERPNext. Ядро расчёта (_compute_dobor) — точный порт функции
compute из dobor/api.py, которая и в исходнике была чистой, без фреймворка.
Формулы не трогались намеренно: по ним печатают производственные листы,
и расхождение здесь означало бы брак в цеху.

Что считаем:
  развёртка = сумма полок + завальцовки × длина завальцовки
  площадь    = развёртка × длина планки (обе в метрах)
  вес        = площадь × масса 1 м² по толщине
  гибов      = (полок − 1) + завальцовки + 2, если замок
  полос из рулона = ширина рулона // развёртка, остаток — отход
"""

import json

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MM_IN_M = 1000.0
STEEL_DENSITY_FACTOR = 7.85  # кг на м² при толщине 1 мм


def compute_dobor(flanges, hem_left, hem_right, hem_len, mass_per_sqm,
                  plank_length, qty, coil_width=0.0, lock=False):
    """Чистый расчёт доборки — БЕЗ обращения к базе, поэтому проверяем тестом.

    Единственное место, где живёт эта арифметика: ею пользуются и форма
    позиции, и печатный лист. Если развести расчёт по двум местам, числа
    рано или поздно разойдутся — ровно это уже произошло между Odoo и
    ERPNext в правиле гибов.

    Завальцовка СЧИТАЕТСЯ гибом: это подгиб 180°, металл там гнут. На
    П-образном профиле из трёх полок выходит 4 гиба — два угла и две
    завальцовки, именно столько и гнёт станок. Правило то же, что в ERPNext,
    системы в этом сходятся.
    """
    flange_sum = sum(float(f.get("len") or 0) for f in (flanges or []) if isinstance(f, dict))
    hem_count = (1 if hem_left else 0) + (1 if hem_right else 0)
    developed = flange_sum + hem_count * hem_len

    area_one = (developed / MM_IN_M) * (plank_length / MM_IN_M)
    weight_one = area_one * mass_per_sqm

    bends = max(0, len(flanges or []) - 1) + hem_count + (2 if lock else 0)

    if developed > 0 and coil_width > 0:
        strips = int(coil_width // developed)
        strip_waste = coil_width - strips * developed
    else:
        strips = 0
        strip_waste = coil_width or 0.0

    return {
        "developed_width": developed,
        "flanges_count": len(flanges or []),
        "bends": bends,
        "area_one": area_one,
        "area_total": area_one * (qty or 0),
        "weight_one": weight_one,
        "weight_total": weight_one * (qty or 0),
        "strips": strips,
        "strip_waste": strip_waste,
    }


class DoborCoating(models.Model):
    _name = "pmk.dobor.coating"
    _description = "Покрытие доборки"
    _order = "name"

    name = fields.Char("Покрытие", required=True)
    ral_code = fields.Char("RAL")
    hex_color = fields.Char("Цвет", help="Образец цвета для подбора на экране")


class DoborProfile(models.Model):
    """Шаблон профиля: сохранённая форма сечения для повторного использования."""

    _name = "pmk.dobor.profile"
    _description = "Шаблон профиля доборки"
    _order = "name"

    name = fields.Char("Название профиля", required=True)
    flanges_json = fields.Text(
        "Полки (JSON)", required=True, default="[]",
        help='Список полок: [{"len": 100, "dir": 0}, ...]. Длины в мм, dir — направление гиба.')
    hem_left = fields.Boolean("Завальцовка слева")
    hem_right = fields.Boolean("Завальцовка справа")
    hem_len = fields.Float("Длина завальцовки, мм", default=10.0)
    lock = fields.Boolean("Замок", help="Специальное соединение, добавляет два гиба")
    paint_side = fields.Integer("Сторона окраски", default=1)


class DoborOrder(models.Model):
    _name = "pmk.dobor.order"
    _description = "Заказ доборных элементов"
    _inherit = ["mail.thread"]
    _order = "order_date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    customer = fields.Char("Клиент / изделие", tracking=True)
    order_date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    state = fields.Selection(
        [("draft", "Черновик"), ("confirmed", "В работе"), ("done", "Изготовлен")],
        "Статус", default="draft", tracking=True)
    line_ids = fields.One2many("pmk.dobor.order.line", "order_id", "Доборки", copy=True)

    total_positions = fields.Integer("Позиций", compute="_compute_totals", store=True)
    total_qty = fields.Integer("Планок, шт", compute="_compute_totals", store=True)
    total_area = fields.Float("Площадь, м²", compute="_compute_totals", store=True, digits=(12, 4))
    total_weight = fields.Float("Вес, кг", compute="_compute_totals", store=True, digits=(12, 3))

    @api.depends("line_ids.weight_total", "line_ids.area_total", "line_ids.qty")
    def _compute_totals(self):
        for order in self:
            order.total_positions = len(order.line_ids)
            order.total_qty = sum(order.line_ids.mapped("qty"))
            order.total_area = sum(order.line_ids.mapped("area_total"))
            order.total_weight = sum(order.line_ids.mapped("weight_total"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.dobor.order") or "Черновик"
        return super().create(vals_list)

    # ── печатный производственный лист ────────────────────────────────────

    def _sheet_html(self):
        """HTML производственного листа.

        Вёрстку строит перенесённый с ERPNext генератор — он ничего не знает
        ни про Odoo, ни про Frappe, поэтому данные отдаём ему обычным словарём,
        а массу 1 м² — функцией: так модуль печати не ходит в базу сам и его
        можно проверить без запущенной системы.
        """
        self.ensure_one()
        from .dobor_report import order_html

        sheets = self.env["pmk.metal.sheet"]

        def mps(thickness):
            row = sheets.search(
                [("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", thickness)], limit=1)
            return row.mass_per_sqm if row else thickness * STEEL_DENSITY_FACTOR

        order = {
            "name": self.name,
            "customer": self.customer or "—",
            "order_date": fields.Date.to_string(self.order_date) if self.order_date else "",
            "items": [{
                "title": line.title,
                "coating": line.coating_id.name or "",
                "thickness": line.thickness,
                "plank_length": line.plank_length,
                "qty": line.qty,
                "profile_snapshot_json": line.profile_snapshot_json,
            } for line in self.line_ids],
        }
        # Обёртка class="article" ОБЯЗАТЕЛЬНА: по ней Odoo находит содержимое
        # и оборачивает его в minimal_layout, где есть <meta charset="utf-8">.
        # Без неё срабатывает запасной путь — в wkhtmltopdf уходит фрагмент
        # без объявления кодировки, и кириллица печатается абракадаброй.
        return Markup(
            '<div class="article" data-oe-model="%s" data-oe-id="%s">%s</div>'
            % (self._name, self.id, order_html(order, mps, author=self.env.user.name or "")))

    def action_print_sheet(self):
        return self.env.ref("pmk_calc.action_report_dobor_sheet").report_action(self)


class DoborOrderLine(models.Model):
    _name = "pmk.dobor.order.line"
    _description = "Позиция заказа доборки"
    _order = "sequence, id"

    order_id = fields.Many2one("pmk.dobor.order", "Заказ", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    # Не обязательное: пока профиль рисуют, название придумывать рано, а
    # форма не должна этого требовать. Пустое заполняется само — см. create().
    title = fields.Char("Название доборки")
    coating_id = fields.Many2one("pmk.dobor.coating", "Покрытие")
    # Металл берём из ОБЩЕГО справочника, того же, что у калькулятора
    # металлопроката: иначе толщина и масса живут в двух местах и расходятся.
    # НЕ required на уровне модели: поле добавлено позже, и обязательность
    # уронила бы обновление на уже заведённых доборках. Обязательность задана
    # в форме, а существующим строкам металл проставляет post_init_hook
    # по их толщине.
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Металл",
        domain=[("thickness_mm", "<=", 2)],
        help="Тонколистовой прокат, из которого гнётся доборка")
    thickness = fields.Float("Толщина, мм", default=0.5, digits=(6, 2))

    @api.onchange("sheet_id")
    def _onchange_sheet_id(self):
        """Толщина приходит из справочника — вводить её вторично незачем."""
        if self.sheet_id:
            self.thickness = self.sheet_id.thickness_mm
    # 2500 — стандартная длина планки доборки.
    plank_length = fields.Float("Длина планки, мм", required=True, default=2500.0, digits=(12, 1))
    qty = fields.Integer("Количество, шт", required=True, default=1)
    coil_width = fields.Float("Ширина рулона, мм", digits=(12, 1),
                              help="Если задана — считается, сколько полос выходит из рулона и какой остаётся отход")

    # Форма сечения. Хранится снимком, а не ссылкой на шаблон: шаблон могут
    # потом поправить, а заказ должен остаться таким, каким его изготовили.
    profile_snapshot_json = fields.Text("Снимок профиля (JSON)", default="[]")
    # Завальцовка, её длина и замок задаются в построителе и живут ВНУТРИ
    # снимка профиля. Здесь они вычисляемые, а не вводимые: раньше это были
    # обычные поля, построитель их не заполнял, и расчёт шёл без завальцовок —
    # развёртка выходила на 2×длину короче, чем показывал чертёж.
    hem_left = fields.Boolean("Завальцовка слева", compute="_compute_dobor", store=True)
    hem_right = fields.Boolean("Завальцовка справа", compute="_compute_dobor", store=True)
    hem_len = fields.Float("Длина завальцовки, мм", compute="_compute_dobor", store=True, digits=(6, 2))
    lock = fields.Boolean("Замок", compute="_compute_dobor", store=True)

    # Эскиз профиля прямо в списке позиций: иначе, чтобы понять, что за
    # доборка, приходится открывать каждую. Рисует тот же генератор, что и
    # печатный лист — двух разных чертежей одной позиции быть не должно.
    sketch = fields.Html("Эскиз", compute="_compute_sketch", store=True, sanitize=False)

    developed_width = fields.Float("Развёртка, мм", compute="_compute_dobor", store=True, digits=(12, 2))
    bends = fields.Integer("Гибов", compute="_compute_dobor", store=True)
    area_one = fields.Float("Площадь шт, м²", compute="_compute_dobor", store=True, digits=(12, 4))
    area_total = fields.Float("Площадь всего, м²", compute="_compute_dobor", store=True, digits=(12, 4))
    weight_one = fields.Float("Вес шт, кг", compute="_compute_dobor", store=True, digits=(12, 3))
    weight_total = fields.Float("Вес всего, кг", compute="_compute_dobor", store=True, digits=(12, 3))
    strips = fields.Integer("Полос из рулона", compute="_compute_dobor", store=True)
    strip_waste = fields.Float("Отход рулона, мм", compute="_compute_dobor", store=True, digits=(12, 2))

    @api.depends("profile_snapshot_json")
    def _compute_sketch(self):
        from .dobor_report import sketch_svg

        for line in self:
            try:
                snapshot = json.loads(line.profile_snapshot_json or "{}")
            except (ValueError, TypeError):
                snapshot = {}
            if not isinstance(snapshot, dict) or not snapshot.get("segs"):
                line.sketch = False
                continue
            try:
                line.sketch = Markup(sketch_svg(snapshot))
            except Exception:
                # Кривой снимок не должен ронять список позиций.
                line.sketch = False

    def _mass_per_sqm(self, thickness):
        """Масса 1 м² — из выбранной позиции справочника.

        Раньше здесь был поиск по толщине с откатом на формулу «толщина × 7.85»,
        потому что тонкого проката в справочнике не было вовсе. Теперь он там
        есть, и масса берётся у самой записи: один справочник на калькулятор
        металлопроката и на доборку, расходиться нечему. Формула осталась
        только как страховка, если запись почему-то не выбрана.
        """
        self.ensure_one()
        if self.sheet_id:
            return self.sheet_id.mass_per_sqm
        return (thickness or 0.0) * STEEL_DENSITY_FACTOR

    @api.depends("profile_snapshot_json", "thickness", "plank_length", "qty", "coil_width")
    def _compute_dobor(self):
        for line in self:
            try:
                snapshot = json.loads(line.profile_snapshot_json or "{}")
            except (ValueError, TypeError):
                snapshot = {}
            if not isinstance(snapshot, dict):
                # Старый формат: голый список полок без настроек завальцовки.
                snapshot = {"segs": snapshot or []}

            flanges = snapshot.get("segs") or []
            hem_left = bool(snapshot.get("hemLeft"))
            hem_right = bool(snapshot.get("hemRight"))
            hem_len = float(snapshot.get("hemLen") or 0.0)
            lock = bool(snapshot.get("lock") or snapshot.get("lockOn"))

            res = compute_dobor(
                flanges, hem_left, hem_right, hem_len,
                line._mass_per_sqm(line.thickness), line.plank_length,
                line.qty, line.coil_width, lock,
            )
            line.hem_left = hem_left
            line.hem_right = hem_right
            line.hem_len = hem_len
            line.lock = lock
            line.developed_width = res["developed_width"]
            line.bends = res["bends"]
            line.area_one = res["area_one"]
            line.area_total = res["area_total"]
            line.weight_one = res["weight_one"]
            line.weight_total = res["weight_total"]
            line.strips = res["strips"]
            line.strip_waste = res["strip_waste"]

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if not (line.title or "").strip():
                line.title = line._default_title()
        return lines

    def _default_title(self):
        """Имя по умолчанию: «Доборка N» с номером по порядку внутри заказа.

        Считаем по количеству уже заведённых позиций, а не по sequence:
        позиции переставляют перетаскиванием, и номер в названии от этого
        меняться не должен — он часть имени, а не порядковый номер строки.
        """
        self.ensure_one()
        others = self.search_count([("order_id", "=", self.order_id.id), ("id", "!=", self.id)])
        return "Доборка %s" % (others + 1)

    @api.constrains("plank_length", "qty")
    def _check_positive(self):
        for line in self:
            if line.plank_length <= 0:
                raise ValidationError("Длина планки должна быть больше нуля.")
            if line.qty <= 0:
                raise ValidationError("Количество должно быть больше нуля.")
