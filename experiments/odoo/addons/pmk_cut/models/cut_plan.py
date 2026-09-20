# -*- coding: utf-8 -*-
"""Документ раскроя: заготовки, отрезки, результат.

Расчёт живёт отдельно, в cutting.py, и базы не касается — здесь только
подготовка данных и раскладка результата по полям. Так арифметику можно
проверять тестами, не поднимая окружение.

ПОЧЕМУ РАСЧЁТ ИДЁТ ПО ТИПОРАЗМЕРАМ ОТДЕЛЬНО. Из хлыста уголка 50x50
швеллер не выкроить. Поэтому и у заготовки, и у отрезка есть позиция
сортамента, а расчёт группирует по ней и считает каждую группу сама по
себе. Один документ при этом может закрывать всю спецификацию.
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .cutting import cut_plan

_logger = logging.getLogger(__name__)

MM_IN_M = 1000.0


class PmkCutPlan(models.Model):
    _name = "pmk.cut.plan"
    _description = "Раскрой сортамента"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    note = fields.Char("Примечание")

    spec_id = fields.Many2one(
        "pmk.metal.spec", "Из спецификации",
        help="Откуда взять отрезки. Кнопка «Заполнить» перенесёт линейные детали.")

    # Пропил — свойство станка, а не металла: ленточная пила съедает больше,
    # дисковая меньше. Поэтому поле документа, а не справочника.
    kerf_mm = fields.Float("Ширина пропила, мм", default=3.0, digits=(6, 1), required=True)
    min_useful_mm = fields.Float(
        "Годный остаток от, мм", default=500.0, digits=(8, 1), required=True,
        help="Остаток не короче этого возвращается на склад как заготовка. "
             "Всё короче считается ломом.")

    stock_ids = fields.One2many("pmk.cut.stock", "plan_id", "Заготовки", copy=True)
    part_ids = fields.One2many("pmk.cut.part", "plan_id", "Отрезки", copy=True)
    result_ids = fields.One2many("pmk.cut.result", "plan_id", "Результат", readonly=True, copy=False)

    total_bars = fields.Integer("Заготовок", compute="_compute_totals", store=True)
    total_weight = fields.Float("Взято металла, кг", compute="_compute_totals", store=True, digits=(12, 2))
    scrap_weight = fields.Float("В лом, кг", compute="_compute_totals", store=True, digits=(12, 2))
    waste_ratio = fields.Float("Отход, %", compute="_compute_totals", store=True, digits=(5, 2))
    has_unplaced = fields.Boolean("Есть неразмещённые", compute="_compute_totals", store=True)

    @api.depends("result_ids.bars_used", "result_ids.weight_total",
                 "result_ids.scrap_weight", "result_ids.unplaced_text")
    def _compute_totals(self):
        for plan in self:
            results = plan.result_ids
            plan.total_bars = sum(results.mapped("bars_used"))
            plan.total_weight = sum(results.mapped("weight_total"))
            plan.scrap_weight = sum(results.mapped("scrap_weight"))
            # Отход считаем по металлу, а не по числу заготовок: две заготовки
            # разной длины — это разный металл.
            plan.waste_ratio = (
                100.0 * plan.scrap_weight / plan.total_weight if plan.total_weight else 0.0)
            plan.has_unplaced = any(results.mapped("unplaced_text"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.cut.plan") or "Черновик"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Заполнение из спецификации
    # ------------------------------------------------------------------

    def action_fill_from_spec(self):
        """Перенести линейные детали спецификации в отрезки.

        Количество перемножаем: в спецификации количество указано НА ОДНО
        изделие, а изделий в документе может быть сто. Не перемножить —
        значит посчитать раскрой на одну ферму вместо партии.
        """
        self.ensure_one()
        if not self.spec_id:
            raise UserError(_("Не выбрана спецификация."))

        rows = {}
        for product in self.spec_id.product_ids:
            for line in product.line_linear_ids:
                if not line.profile_id or line.length_mm <= 0:
                    continue
                key = (line.profile_id.id, round(line.length_mm, 1))
                qty = (line.qty or 0) * (product.qty or 0)
                if qty <= 0:
                    continue
                rows.setdefault(key, {"qty": 0, "names": set()})
                rows[key]["qty"] += qty
                if line.detail_name:
                    rows[key]["names"].add(line.detail_name)

        if not rows:
            raise UserError(_("В спецификации нет линейного проката с длиной."))

        self.part_ids.unlink()
        self.env["pmk.cut.part"].create([
            {
                "plan_id": self.id,
                "profile_id": profile_id,
                "length_mm": length,
                "qty": data["qty"],
                # Имена деталей склеиваем: в раскрое важно, что это за отрезок,
                # но перечислять по одному — только раздувать таблицу.
                "name": ", ".join(sorted(data["names"]))[:120],
            }
            for (profile_id, length), data in sorted(rows.items(), key=lambda kv: -kv[0][1])
        ])
        # Заготовки не трогаем: какие хлысты есть в наличии, знает человек,
        # а не спецификация.
        return True

    # ------------------------------------------------------------------
    # Расчёт
    # ------------------------------------------------------------------

    def action_compute(self):
        for plan in self:
            plan._compute_plan()
        return True

    def _compute_plan(self):
        self.ensure_one()
        if not self.part_ids:
            raise UserError(_("Нечего резать: не задано ни одного отрезка."))
        if not self.stock_ids:
            raise UserError(_("Не из чего резать: не задано ни одной заготовки."))

        self.result_ids.unlink()

        profiles = self.part_ids.mapped("profile_id")
        created = []
        for profile in profiles:
            parts = self.part_ids.filtered(lambda p, pr=profile: p.profile_id == pr)
            stocks = self.stock_ids.filtered(lambda s, pr=profile: s.profile_id == pr)
            if not stocks:
                raise UserError(_(
                    "Для «%s» не задано ни одной заготовки — не из чего резать.",
                    profile.display_name))

            res = cut_plan(
                [{
                    "length": s.length_mm,
                    # Пустое количество — заготовка неограничена: докупим
                    # столько, сколько понадобится.
                    "qty": s.qty or None,
                    "name": s.name or s.display_name,
                    "priority": s.priority,
                } for s in stocks],
                [{"length": p.length_mm, "qty": p.qty, "name": p.name} for p in parts],
                kerf=self.kerf_mm,
                min_useful=self.min_useful_mm,
            )
            created.append(self._result_values(profile, res))

        self.env["pmk.cut.result"].create(created)
        _logger.info("pmk_cut: %s — посчитано групп: %s", self.name, len(created))
        return True

    def _result_values(self, profile, res):
        mass = profile.mass_per_meter or 0.0
        to_kg = lambda mm: mm / MM_IN_M * mass  # noqa: E731

        return {
            "plan_id": self.id,
            "profile_id": profile.id,
            "bars_used": res["bars_used"],
            "stock_mm": res["total_stock"],
            "parts_mm": res["total_parts"],
            "kerf_mm": res["total_kerf"],
            "scrap_mm": res["scrap"],
            "weight_total": to_kg(res["total_stock"]),
            "weight_parts": to_kg(res["total_parts"]),
            "leftover_weight": to_kg(sum(res["useful_leftovers"])),
            "scrap_weight": to_kg(res["scrap"]),
            # Отход — ТОЛЬКО безвозвратные потери. Годный остаток уходит на
            # склад и металлом быть не перестаёт; считать его отходом значит
            # пугать цифрой 22% там, где реально потеряно полкилограмма.
            "waste_ratio": round(
                100.0 * res["scrap"] / res["total_stock"], 2) if res["total_stock"] else 0.0,
            "lower_bound": res["lower_bound"],
            "layout_html": self._layout_html(res),
            "leftovers_text": self._leftovers_text(res),
            "unplaced_text": self._unplaced_text(res),
            "result_json": json.dumps(res, ensure_ascii=False),
        }

    # ------------------------------------------------------------------
    # Представление результата
    # ------------------------------------------------------------------

    def _layout_html(self, res):
        """Схемы раскроя полосками — цеху понятнее числа в столбик.

        Показываем схему и сколько раз её повторить: сто одинаковых строк
        читать невозможно, а «вот так режь, двенадцать раз» — можно.
        """
        from markupsafe import Markup, escape

        if not res["patterns"]:
            return False

        blocks = []
        for pattern in res["patterns"]:
            total = pattern["stock_length"] or 1
            cells = []
            for piece in pattern["pieces"]:
                width = 100.0 * piece / total
                cells.append(
                    '<div class="pmk-cut__piece" style="width:%.3f%%" title="%s мм">%s</div>'
                    % (width, escape(self._fmt(piece)), escape(self._fmt(piece)))
                )
            if pattern["leftover"] > 0:
                width = 100.0 * pattern["leftover"] / total
                kind = "useful" if pattern["leftover"] >= self.min_useful_mm else "scrap"
                cells.append(
                    '<div class="pmk-cut__rest pmk-cut__rest--%s" style="width:%.3f%%" title="%s мм">%s</div>'
                    % (kind, width, escape(self._fmt(pattern["leftover"])),
                       escape(self._fmt(pattern["leftover"])))
                )
            blocks.append(
                '<div class="pmk-cut__pattern">'
                '<div class="pmk-cut__head"><b>%s мм</b> — повторить %s раз</div>'
                '<div class="pmk-cut__bar">%s</div></div>'
                % (escape(self._fmt(pattern["stock_length"])), pattern["count"], "".join(cells))
            )
        return Markup('<div class="pmk-cut">%s</div>' % "".join(blocks))

    def _leftovers_text(self, res):
        if not res["useful_leftovers"]:
            return False
        return ", ".join("%s мм" % self._fmt(x) for x in res["useful_leftovers"])

    def _unplaced_text(self, res):
        if not res["unplaced"]:
            return False
        return "; ".join(
            "%s мм — %s шт" % (self._fmt(u["length"]), u["qty"]) for u in res["unplaced"])

    @staticmethod
    def _fmt(value):
        value = float(value or 0)
        return str(int(value)) if value == int(value) else ("%.1f" % value)


class PmkCutStock(models.Model):
    """Заготовка: целый хлыст или обрезок со склада — разницы для расчёта нет."""

    _name = "pmk.cut.stock"
    _description = "Заготовка раскроя"
    _order = "priority, sequence, id"

    plan_id = fields.Many2one("pmk.cut.plan", "Раскрой", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер", required=True)
    length_mm = fields.Float("Длина, мм", required=True, digits=(10, 1))
    qty = fields.Integer(
        "Количество", default=0,
        help="Сколько таких заготовок в наличии. Пусто или 0 — не ограничено, "
             "докупим сколько понадобится.")
    name = fields.Char("Название", help="Например «Хлыст 6 м» или «Обрезок от РК-00007».")
    priority = fields.Integer(
        "Очерёдность", default=10,
        help="Меньше — раньше идёт в дело. Обрезкам со склада ставьте 1, "
             "чтобы расходовались первыми.")


class PmkCutPart(models.Model):
    """Отрезок: что нужно получить."""

    _name = "pmk.cut.part"
    _description = "Отрезок раскроя"
    _order = "sequence, id"

    plan_id = fields.Many2one("pmk.cut.plan", "Раскрой", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер", required=True)
    length_mm = fields.Float("Длина, мм", required=True, digits=(10, 1))
    qty = fields.Integer("Количество", required=True, default=1)
    name = fields.Char("Деталь")


class PmkCutResult(models.Model):
    """Результат по одному типоразмеру."""

    _name = "pmk.cut.result"
    _description = "Результат раскроя"
    _order = "id"

    plan_id = fields.Many2one("pmk.cut.plan", "Раскрой", required=True, ondelete="cascade")
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер", required=True)

    bars_used = fields.Integer("Заготовок")
    stock_mm = fields.Float("Взято, мм", digits=(12, 1))
    parts_mm = fields.Float("В деталях, мм", digits=(12, 1))
    kerf_mm = fields.Float("В пропил, мм", digits=(12, 1))
    scrap_mm = fields.Float("В лом, мм", digits=(12, 1))

    weight_total = fields.Float("Взято, кг", digits=(12, 2))
    weight_parts = fields.Float("В деталях, кг", digits=(12, 2))
    leftover_weight = fields.Float("В годные остатки, кг", digits=(12, 2))
    scrap_weight = fields.Float("В лом, кг", digits=(12, 2))
    waste_ratio = fields.Float("Отход, %", digits=(5, 2))
    # Грубая нижняя граница: показывает, есть ли куда ужиматься вообще.
    lower_bound = fields.Integer("Теоретический минимум")

    layout_html = fields.Html("Схемы раскроя", sanitize=False)
    leftovers_text = fields.Char("Годные остатки")
    unplaced_text = fields.Char("Не размещено")
    result_json = fields.Text("Расчёт (json)")
