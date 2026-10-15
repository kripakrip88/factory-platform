# -*- coding: utf-8 -*-
"""«Купить» и «Металл к закупке» — целыми хлыстами из раскроя сортамента
(Антон 15.10.2026: «показывает чистый вес отрезков, а не целые хлысты»)."""
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCutCost(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        old = fields.Date.context_today(cls.env["res.partner"]) - timedelta(days=30)
        metal = cls.env["res.partner"].create({
            "name": "Металл (тест закупки)", "is_company": True, "pmk_supplier_rank": 1})
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Труба (тест закупки)"})

        def profile(size, mass):
            tmpl = cls.env["product.template"].create({"name": "Труба %s (тест закупки)" % size})
            cls.env["product.supplierinfo"].create({
                "partner_id": metal.id, "product_tmpl_id": tmpl.id, "price": 100.0,
                "date_start": old, "pmk_bar_length_mm": 12000.0})
            return cls.env["pmk.metal.profile"].create({
                "type_id": ptype.id, "profile_type": "Труба (тест закупки)", "gost": "ГОСТ",
                "size_label": size, "mass_per_meter": mass, "product_tmpl_id": tmpl.id})

        cls.p76 = profile("76x3", 5.4)
        cls.p57 = profile("57x3", 4.0)
        line = lambda prof, length, qty: Command.create({  # noqa: E731
            "calc_mode": "linear", "profile_id": prof.id, "length_mm": length, "qty": qty})
        cls.spec = cls.env["pmk.metal.spec"].create({
            "product_ids": [
                Command.create({"name": "Опора А", "qty": 2,
                                "line_ids": [line(cls.p76, 400.0, 2), line(cls.p57, 300.0, 1)]}),
                Command.create({"name": "Опора Б", "qty": 1,
                                "line_ids": [line(cls.p76, 400.0, 1)]}),
            ]})
        cls.a, cls.b = cls.spec.product_ids.sorted("id")

    def _plan(self):
        plan = self.env["pmk.cut.plan"].create({"spec_id": self.spec.id})
        plan.action_fill_from_spec()
        plan.action_compute()
        return plan

    def test_without_cut_buy_is_net(self):
        self.assertAlmostEqual(self.spec.total_weight_fact, self.spec.total_weight, places=2)
        self.assertTrue(self.a.pmk_buy_net, "без раскроя — пометка «чистым весом»")

    def test_buy_whole_bars_from_cut(self):
        plan = self._plan()
        taken = sum(plan.result_ids.mapped("weight_total"))
        self.assertGreater(taken, self.spec.total_weight, "хлыст тяжелее отрезков")
        self.assertAlmostEqual(self.spec.total_weight_fact, taken, places=2,
                               msg="Купить на расчёт = взято хлыстов по раскрою")
        r76 = plan.result_ids.filtered(lambda r: r.profile_id == self.p76)
        net_a = self.a.line_linear_ids.filtered(lambda l: l.profile_id == self.p76).weight_total * 2
        net_b = self.b.line_linear_ids.weight_total
        buy_a = sum(self.a.line_linear_ids.filtered(lambda l: l.profile_id == self.p76)
                    .mapped("weight_fact_total")) * 2
        self.assertAlmostEqual(buy_a, r76.weight_total * net_a / (net_a + net_b), places=2,
                               msg="хлыст делится по чистому весу изделий")
        self.assertFalse(self.a.pmk_buy_net)
        self.assertGreater(self.spec.total_cost_fact, self.spec.total_cost_clean,
                           "металл к закупке — по хлыстам, дороже чистого")

    def test_recut_follows_spec(self):
        plan = self._plan()
        before = self.spec.total_weight_fact
        plan.result_ids.unlink()
        self.assertAlmostEqual(self.spec.total_weight_fact, self.spec.total_weight, places=2,
                               msg="раскрой сброшен — снова чистый вес")
        plan.action_compute()
        self.assertAlmostEqual(self.spec.total_weight_fact, before, places=2)


@tagged("post_install", "-at_install")
class TestSheetBuyAndBars(TransactionCase):
    """Лист — целыми листами раскладки; прокат во вкладке «Металл» и его схема."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест закупки листа)", "thickness_mm": 10.0,
            "gost": "ГОСТ тест", "mass_per_sqm": 78.5})
        cls.spec = cls.env["pmk.metal.spec"].create({
            "product_ids": [Command.create({
                "name": "Опора (лист)", "qty": 2,
                "line_ids": [Command.create({"calc_mode": "sheet", "sheet_id": cls.sheet.id,
                                             "detail_name": "Пластина", "a_mm": 300.0,
                                             "b_mm": 200.0, "qty": 8})]})]})

    def test_sheet_buy_is_whole_sheets(self):
        product = self.spec.product_ids
        self.assertTrue(product.pmk_buy_net, "без раскладки — чистый вес")
        self.spec.action_draft_layout()
        self.assertAlmostEqual(self.spec.total_weight_fact, 1.5 * 6.0 * 78.5, places=1,
                               msg="Купить = целый лист 1500×6000")
        self.assertFalse(product.pmk_buy_net)
