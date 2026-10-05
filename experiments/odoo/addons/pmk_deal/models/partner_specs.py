# -*- coding: utf-8 -*-
"""Карточка клиента → «Расчёты» (разбор UX, шаг 28, 01.10.2026).

Кнопка-счётчик рядом со «Сделками»: расчёты металлопроката этого клиента.
По правилу разбора это НАШ шаг, поэтому у клиента она видна всегда и ноль
серым (stat_buttons.js темы) — «расчёта ещё не было». У поставщика (признак
pmk_is_supplier из pmk_bridge — вместе с его контактными лицами), у
пользователя системы и у своей компании — только когда расчёты есть.

ПОЧЕМУ ЗДЕСЬ, А НЕ В pmk_partner ИЛИ pmk_calc. Кнопка встаёт сразу за
штатной «Сделки», а ту объявляет crm; модуль должен знать и контрагента, и
расчёт. pmk_deal зависит от crm и pmk_calc и уже правит кнопку «Сделки»
(models/res_partner.py). pmk_partner пришлось бы сделать зависимым от
калькулятора, а калькулятор (pmk_calc) намеренно лёгкий и CRM не знает.

ЧЬИ РАСЧЁТЫ. Где контрагент — клиент или контактное лицо, вместе с его
контактными лицами (child_of): у компании — и расчёты старого вида, где
клиентом записан человек (до шага 11 клиентом становился инженер заказчика);
у человека — где он клиент или контактное лицо.

У человека — только его расчёты, не все расчёты компании (решение по
умолчанию, утверждает владелец). Так же устроены «Сделки» рядом: на карточке
человека — сделки, где клиент он сам. Все расчёты компании — на карточке
компании. Показывать человеку расчёты компании — заменить в _pmk_spec_domain
партнёра на commercial_partner_id.
"""

from odoo import _, fields, models


class ResPartnerSpecs(models.Model):
    _inherit = "res.partner"

    pmk_spec_count = fields.Integer(
        "Расчётов", compute="_compute_pmk_spec_count",
        help="Расчёты металлопроката, где контрагент — клиент или контактное "
             "лицо, вместе с его контактными лицами.")

    def _pmk_spec_domain(self):
        self.ensure_one()
        partner_id = self._origin.id
        return ["|", ("partner_id", "child_of", partner_id),
                ("contact_id", "child_of", partner_id)]

    def _compute_pmk_spec_count(self):
        Spec = self.env["pmk.metal.spec"]
        # Нет права читать расчёты — ноль, как у штатных счётчиков ядра.
        if not Spec.has_access("read"):
            self.pmk_spec_count = 0
            return
        for partner in self:
            # Новая карточка ещё не сохранена — расчётов у неё быть не может.
            partner.pmk_spec_count = (Spec.search_count(partner._pmk_spec_domain())
                                      if partner._origin.id else 0)

    def action_pmk_view_specs(self):
        """Список расчётов клиента — всегда список, даже из одной строки.

        «Расчёты» на сделке ведут сразу в дело (нет — новый, один — он сам):
        у сделки расчёт обычно один. У клиента их копится много — по каждой
        заявке свой, — и смотрят их списком. Новый расчёт отсюда — с клиентом
        (компанией) и, если открыт человек, с ним как контактным лицом.
        """
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_calc.action_metal_spec")
        context = {"default_partner_id": self.commercial_partner_id.id}
        if not self.is_company and self.parent_id:
            context["default_contact_id"] = self.id
        # Заголовок — и в display_name (разбор UX, шаг 38, доводка): клиент
        # берёт его раньше name (action_service.js), а _for_xml_id отдаёт
        # display_name записи — окно называлось «Расчёт металлопроката», а не
        # как кнопка.
        title = _("Расчёты")
        action.update({
            "name": title,
            "display_name": title,
            "domain": self._pmk_spec_domain(),
            "context": context,
        })
        return action
