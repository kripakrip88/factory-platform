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
        """«Расчёт и КП» и кнопка-счётчик «Расчёты»: сразу к делу.

        Разбор UX, шаг 31 (30.09.2026). Главная кнопка сделки ведёт не в
        список, а туда, где продолжают работу:
          • расчёта нет — форма нового, сделка и клиент уже подставлены;
          • расчёт один — он сам;
          • несколько — список расчётов сделки (выбрать нужный).
        Стадию сделки кнопка не двигает — решение «без автоперехода».
        """
        self.ensure_one()
        specs = self.env["pmk.metal.spec"].search([("opportunity_id", "=", self.id)])
        action = {
            "type": "ir.actions.act_window",
            "name": _("Расчёты по сделке"),
            "res_model": "pmk.metal.spec",
            "target": "current",
            "context": self._pmk_spec_defaults(),
        }
        if not specs:
            action.update(name=_("Новый расчёт"), views=[(False, "form")])
        elif len(specs) == 1:
            action.update(name=specs.name, res_id=specs.id, views=[(False, "form")])
        else:
            # Список — штатным действием «Расчёты и КП» (с его id), как
            # кнопка клиента (partner_specs.py): у действия-словаря без id
            # настройка колонок (pmk_list_prefs, ключ list|модель|вид|действие)
            # была бы своя, не та, что в меню, и общая администратора сюда
            # не доходила бы. Заголовок — и в display_name: клиент берёт его
            # раньше name (action_service.js).
            title = _("Расчёты по сделке")
            listed = self.env["ir.actions.act_window"]._for_xml_id("pmk_calc.action_metal_spec")
            listed.update(
                name=title,
                display_name=title,
                target="current",
                context=action["context"],
                view_mode="list,form",
                views=[(False, "list"), (False, "form")],
                domain=[("opportunity_id", "=", self.id)],
            )
            return listed
        return action

    def _pmk_spec_defaults(self):
        """Что подставить в новый расчёт со сделки.

        Менеджер пришёл сюда со сделки, повторять её выбор руками незачем.
        Клиент — КОМПАНИЯ контакта сделки, сам человек — контактное лицо
        (разбор UX, шаг 11); предмет КП — черновиком из названия сделки.
        """
        self.ensure_one()
        return {
            "default_opportunity_id": self.id,
            "default_partner_id": self.partner_id.commercial_partner_id.id,
            "default_contact_id": self._pmk_contact_person().id,
            "default_note": self.name,
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

    # copy=True (приёмка 01.10.2026, R4): копия расчёта остаётся в той же
    # сделке. Раньше сделка переносилась только при «Дублировать» из формы,
    # открытой кнопкой «Расчёт и КП» (её контекст default_opportunity_id), а
    # из меню «Калькулятор» копия теряла сделку. Копия датирована сегодняшним
    # днём (pmk_calc) — значит она и становится главным расчётом сделки
    # (main_spec в deal_money.py): новый расчёт заменяет старый.
    opportunity_id = fields.Many2one(
        "crm.lead", "Сделка", index=True, ondelete="set null", copy=True,
        # Только возможности, не лиды: считают по заявке, которую взяли в
        # работу. Лид — это ещё интерес, у него нет ни объёма, ни сортамента.
        domain="[('type', '=', 'opportunity')]",
        help="К какой сделке относится расчёт. Клиент подставляется из неё.")

    def _pmk_main_spec_candidates(self):
        """Из каких расчётов сделки выбирается главный (main_spec,
        deal_money.py). Здесь — из всех; pmk_tech (шаг З-4) убирает
        технические расчёты инженера: они копия для закупки, а не КП."""
        return self

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
