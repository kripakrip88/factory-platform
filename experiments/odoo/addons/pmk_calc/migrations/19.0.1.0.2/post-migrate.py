# -*- coding: utf-8 -*-
"""Клиент расчёта — компания, человек — контактное лицо (разбор UX, шаг 11).

Правило действует для новых расчётов (выбор клиента, подстановка из
сделки). Здесь — для уже заведённых: где клиентом записан человек внутри
компании, клиентом ставим компанию, а человека — контактным лицом. Так
было у СМ-00024 («ООО «Арестак-Строй», Цыганов М. А.»). Частное лицо без
компании не трогаем. Контактное лицо, если уже задано, не перезаписываем.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE pmk_metal_spec s
           SET contact_id = p.id,
               partner_id = p.commercial_partner_id
          FROM res_partner p
         WHERE p.id = s.partner_id
           AND NOT p.is_company
           AND p.parent_id IS NOT NULL
           AND p.commercial_partner_id IS NOT NULL
           AND p.commercial_partner_id <> p.id
           AND s.contact_id IS NULL
        """
    )
