# -*- coding: utf-8 -*-
"""«Клиент» → «Контрагент» по всей системе (Антон 14.10.2026).

Подписи полей в коде уже «Контрагент», но у штатных полей (счёт, задача, сделка)
русский перевод «Клиент» лежит в базе (ir_model_fields.field_description,
ru_RU) и перекрывал бы новую подпись. Меню «Клиенты» — так же (ir_ui_menu.name).
Меняем только точное «Клиент» / «Клиенты»."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_fields
           SET field_description = field_description
               || jsonb_build_object('ru_RU', 'Контрагент', 'en_US',
                    CASE WHEN field_description->>'en_US' = 'Клиент' THEN 'Контрагент'
                         ELSE field_description->>'en_US' END)
         WHERE field_description->>'ru_RU' = 'Клиент'
           AND name IN ('partner_id', 'pmk_client_id', 'pmk_partner_id')
    """)
    fields_n = cr.rowcount
    cr.execute("""
        UPDATE ir_ui_menu
           SET name = name || jsonb_build_object('ru_RU', 'Контрагенты')
         WHERE name->>'ru_RU' = 'Клиенты'
    """)
    _logger.info("pmk_orders: «Клиент» → «Контрагент» — полей %s, меню %s", fields_n, cr.rowcount)
