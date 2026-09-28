# -*- coding: utf-8 -*-
"""Сделка знает свои расчёты, расчёт знает свою сделку.

ЗАЧЕМ. До этого файла найти расчёт к сделке можно было только глазами по
названию: в спецификации не было ни поля сделки, ни поля возможности. При
десятке сделок это терпимо, при сотне — источник ошибок: менеджер отправляет
клиенту цену из чужого расчёта.

Связь двусторонняя по смыслу, но хранится ОДНИМ полем на расчёте: у сделки
расчётов бывает несколько (пересчитали объём, поменялся сортамент), а у
расчёта сделка ровно одна.
"""

from odoo import _, api, fields, models


class CrmLeadDeal(models.Model):
    _inherit = "crm.lead"

    spec_ids = fields.One2many(
        "pmk.metal.spec", "opportunity_id", "Расчёты металлопроката")
    spec_count = fields.Integer("Расчётов", compute="_compute_spec_count")

    @api.depends("spec_ids")
    def _compute_spec_count(self):
        # Считаем запросом, а не длиной набора: на списке сделок иначе
        # подгружаются все расчёты каждой строки.
        data = self.env["pmk.metal.spec"]._read_group(
            [("opportunity_id", "in", self.ids)], ["opportunity_id"], ["__count"])
        counts = {lead.id: count for lead, count in data}
        for lead in self:
            lead.spec_count = counts.get(lead.id, 0)

    def action_open_specs(self):
        """Расчёты этой сделки; из пустого списка сразу создаётся новый."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Расчёты по сделке"),
            "res_model": "pmk.metal.spec",
            "view_mode": "list,form",
            "domain": [("opportunity_id", "=", self.id)],
            # Клиент и сделка подставляются в новый расчёт: менеджер пришёл
            # сюда со сделки, повторять её выбор руками незачем. Клиент —
            # КОМПАНИЯ контакта сделки, сам человек — контактное лицо
            # (разбор UX, шаг 11); предмет КП — черновиком из названия сделки.
            "context": {
                "default_opportunity_id": self.id,
                "default_partner_id": self.partner_id.commercial_partner_id.id,
                "default_contact_id": self._pmk_contact_person().id,
                "default_note": self.name,
            },
        }


    def _pmk_contact_person(self):
        """Человек из «Контакта» сделки, если это человек внутри компании."""
        self.ensure_one()
        person = self.partner_id
        if person and not person.is_company and person.parent_id:
            return person
        return self.env["res.partner"]


class MetalSpecDeal(models.Model):
    _inherit = "pmk.metal.spec"

    opportunity_id = fields.Many2one(
        "crm.lead", "Сделка", index=True, ondelete="set null", copy=False,
        # Только возможности, не лиды: считают по заявке, которую взяли в
        # работу. Лид — это ещё интерес, у него нет ни объёма, ни сортамента.
        domain="[('type', '=', 'opportunity')]",
        help="К какой сделке относится расчёт. Клиент подставляется из неё.")

    @api.onchange("opportunity_id")
    def _onchange_opportunity_id(self):
        """Клиент, контактное лицо и предмет КП — из сделки, если их ещё нет.

        Не перетираем заполненного: у сделки может стоять головная компания, а
        считают для филиала — и выбор менеджера важнее автоподстановки.
        Клиент — компания контакта сделки, человек — контактное лицо (разбор
        UX, шаг 11): иначе клиентом расчёта становился инженер заказчика, и
        список, поиск и группировка «Клиент» разбивались по людям.
        """
        for spec in self:
            deal = spec.opportunity_id
            if not deal:
                continue
            if not spec.partner_id:
                spec.partner_id = deal.partner_id.commercial_partner_id
            if not spec.contact_id:
                spec.contact_id = deal._pmk_contact_person()
            if not spec.note:
                spec.note = deal.name
