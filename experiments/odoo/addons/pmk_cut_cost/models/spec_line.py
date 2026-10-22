# -*- coding: utf-8 -*-
"""Закупка проката по раскрою сортамента (15.10.2026).

Доля «в детали / купить» по типоразмеру считается на весь расчёт:
    купить_P = взято_P (целые хлысты раскроя) + неразмещённое_P (чистым весом)
    доля_P   = чистый вес всех строк P в расчёте / купить_P
Строка делит свой чистый вес и цену на эту долю — сумма по строкам P даёт
ровно «взято» раскроя. Так хлысты делятся между изделиями пропорционально их
чистому весу, и итог «Металл к закупке» = хлысты × цену.
"""
from collections import defaultdict

from odoo import api, fields, models

MM_IN_M = 1000.0


class MetalSpecLineCutCost(models.Model):
    _inherit = "pmk.metal.spec.line"

    pmk_cut_share = fields.Float(
        "Доля в деталях по раскрою", compute="_compute_pmk_cut_share", store=True, digits=(12, 6),
        help="Сколько от купленных по раскрою хлыстов этого типоразмера уходит в детали "
             "расчёта. 0 — раскроя нет, закупка по чистому весу и использованию.")

    @api.depends("calc_mode", "profile_id", "weight_total", "product_id.qty", "pmk_mass_kg",
                 "spec_id.product_ids.qty",
                 "spec_id.product_ids.line_linear_ids.weight_total",
                 "spec_id.product_ids.line_linear_ids.profile_id",
                 "spec_id.cut_plan_ids.result_ids.weight_total",
                 "spec_id.cut_plan_ids.result_ids.weight_parts")
    def _compute_pmk_cut_share(self):
        shares = {}
        for spec in self.spec_id:
            # Последний РАССЧИТАННЫЙ раскрой: новый, ещё не посчитанный, прежний
            # результат не отменяет.
            plan = spec.cut_plan_ids.filtered("result_ids").sorted("id")[-1:]
            if not plan:
                continue
            net = defaultdict(float)
            for product in spec.product_ids:
                for line in product.line_linear_ids:
                    # Прокат «по КМ» (№307) не режется — в долю раскроя не входит.
                    if line.profile_id and not line.pmk_mass_kg:
                        net[line.profile_id.id] += (line.weight_total or 0.0) * (product.qty or 0)
            for result in plan.result_ids:
                pid = result.profile_id.id
                unplaced = max(0.0, net[pid] - (result.weight_parts or 0.0))
                buy = (result.weight_total or 0.0) + unplaced
                if buy > 0 and net[pid] > 0:
                    shares[(spec.id, pid)] = min(1.0, net[pid] / buy)
        for line in self:
            share = 0.0
            # «По КМ» — доля 0: закупка по чистому весу (использование), без раскроя.
            if line.calc_mode == "linear" and line.profile_id and not line.pmk_mass_kg:
                share = shares.get((line.spec_id.id, line.profile_id.id), 0.0)
            line.pmk_cut_share = share

    @api.depends("pmk_cut_share")
    def _compute_cost(self):
        super()._compute_cost()
        for line in self:
            share = line.pmk_cut_share
            if line.calc_mode != "linear" or not share:
                continue
            # Как в мосте: итог — от локального числа, не от округлённого поля.
            clean_one = (line.price_unit * (line.length_mm / MM_IN_M)
                         if line.price_state in ("ok", "manual") else 0.0)
            qty = line.qty or 0
            fact_one = clean_one / share
            weight_fact = line.weight_one / share
            line.cost_fact_one = fact_one
            line.cost_fact_total = fact_one * qty
            line.weight_fact_one = weight_fact
            line.weight_fact_total = weight_fact * qty


class MetalSpecProductCutCost(models.Model):
    _inherit = "pmk.metal.spec.product"

    pmk_buy_net = fields.Boolean(
        "Купить — чистым весом", compute="_compute_pmk_buy_net",
        help="Прокат не раскладывали (раскрой сортамента) или лист не раскладывали: «Купить» — "
             "чистый вес, не целые хлысты и листы. Вкладка «Металл» — «Разложить прокат», "
             "«Разложить листы».")

    @api.depends("line_linear_ids.pmk_cut_share", "line_linear_ids.profile_id",
                 "line_sheet_ids.pmk_layout_share")
    def _compute_pmk_buy_net(self):
        # Лист — тоже (15.10.2026): деталь без раскладки куплена «чистым весом».
        for product in self:
            linear = product.line_linear_ids.filtered("profile_id")
            product.pmk_buy_net = (any(not line.pmk_cut_share for line in linear)
                                   or any(not line.pmk_layout_share for line in product.line_sheet_ids))
