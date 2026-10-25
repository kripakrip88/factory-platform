# -*- coding: utf-8 -*-
"""Счёт покупателю: «Технический расчёт» и «Заявки на металл» (шаг З-4).

Кнопка «Технический расчёт» заводит копию расчёта, по которому выставлен
счёт (pmk_spec_id), — или открывает уже заведённую: технический расчёт один
на счёт. Прежняя редакция (снимок) своего технического не имеет — кнопки у
неё спрятаны, а в коде она ведёт к действующей.

Заявки на металл счёта — заказы поставщику с pmk_sale_order_id; счётчик и
список — только «Закупкам» (поле под группой: без прав на заказы поставщику
его не прочитать).
"""
from odoo import _, api, fields, models


class SaleOrderTech(models.Model):
    _inherit = "sale.order"

    pmk_tech_spec_ids = fields.One2many(
        "pmk.metal.spec", "pmk_tech_order_id", "Технические расчёты",
        domain=[("pmk_kind", "=", "tech")])
    pmk_tech_spec_id = fields.Many2one(
        "pmk.metal.spec", "Технический расчёт", compute="_compute_pmk_tech_spec_id",
        help="Копия расчёта КП для инженера: состав, материалы, листы по факту. "
             "Расчёт, по которому выставлен счёт, не меняется.")
    pmk_metal_request_ids = fields.One2many(
        "purchase.order", "pmk_sale_order_id", "Заявки на металл",
        groups="purchase.group_purchase_user")
    pmk_metal_request_count = fields.Integer(
        "Заявки на металл", compute="_compute_pmk_metal_request_count",
        groups="purchase.group_purchase_user")

    @api.depends("pmk_tech_spec_ids")
    def _compute_pmk_tech_spec_id(self):
        for order in self:
            order.pmk_tech_spec_id = order.pmk_tech_spec_ids[:1]

    @api.depends("pmk_metal_request_ids.state")
    def _compute_pmk_metal_request_count(self):
        for order in self:
            order.pmk_metal_request_count = len(
                order.pmk_metal_request_ids.filtered(lambda po: po.state != "cancel"))

    # ─── «Создать ▾ → Технический расчёт» (шапка «вариант А», 25.10.2026) ──
    def _pmk_tech_spec_allowed(self):
        """Технический расчёт завести можно: его нет, счёт отправлен или в работе
        (те же условия, что у кнопок шапки — views/sale_order_views.xml)."""
        self.ensure_one()
        return not self.pmk_tech_spec_id and not self.pmk_is_revision and self.state in ("sent", "sale")

    def pmk_doc_menu(self):
        menu = super().pmk_doc_menu()
        if self[:1] and self._pmk_tech_spec_allowed():
            menu["create"].append({"key": "tech", "label": _("Технический расчёт"), "icon": "fa-wrench",
                                   "method": "action_pmk_tech_spec"})
        return menu

    def action_pmk_tech_spec(self):
        self.ensure_one()
        tech = self.env["pmk.metal.spec"]._pmk_tech_for_order(self)
        return {
            "type": "ir.actions.act_window",
            "name": tech.name,
            "res_model": "pmk.metal.spec",
            "res_id": tech.id,
            "views": [(False, "form")],
            "target": "current",
        }

    def action_pmk_metal_requests(self):
        self.ensure_one()
        order = self.pmk_revision_of_id if self.pmk_is_revision and self.pmk_revision_of_id else self
        return self.env["purchase.order"]._pmk_requests_window(
            [("pmk_sale_order_id", "=", order.id)])
