# -*- coding: utf-8 -*-
"""Контактное лицо расчёта — только имя человека (приёмка 01.10.2026, R2).

Штатное имя контакта в Odoo — «Компания, Человек»: в поле «Контактное лицо»
расчёта читалось «ООО «Арестак-Строй», Цыганов…» — компания дважды подряд,
сразу под «Клиентом». Ядро умеет показывать человека без компании по ключу
контекста partner_display_name_hide_company (res.partner._get_complete_name;
CRM ставит его так же на «Контакт» сделки). Ключ стоит в контексте одного поля
формы (views/metal_spec_views.xml, contact_id), display_name в других местах
прежний.

ЗАЧЕМ ЭТОТ ФАЙЛ. Ключа нет в depends_context у display_name контакта: если
имя этого человека уже посчитано в той же транзакции без ключа, кэш вернул бы
полное «Компания, Человек». depends_context всех переопределений ядро
складывает (orm/fields.py, get_depends → resolve_mro), поэтому достаточно
объявить ключ здесь — само вычисление не меняется.
"""

from odoo import api, models


class ResPartnerHideCompany(models.Model):
    _inherit = "res.partner"

    @api.depends_context("partner_display_name_hide_company")
    def _compute_display_name(self):
        return super()._compute_display_name()
