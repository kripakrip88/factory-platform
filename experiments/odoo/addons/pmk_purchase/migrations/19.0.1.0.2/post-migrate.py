# -*- coding: utf-8 -*-
"""Поля закупки: «Поставщик» и «Закупщик» вместо «Продавец» и «Покупатель».

Антон, 29.09.2026: «штатные надписи Odoo переименовывай». Перевод ядра
называет поставщика закупки «Продавцом», а нашего сотрудника, который
закупает, — «Покупателем»; на заводе «покупатель» — это клиент. Меняем
название самого поля — тогда подпись сменится везде: в форме, списке,
фильтрах и группировках.

Как и в 19.0.1.0.1: меняем русский ключ, только если там ещё штатный
перевод; повторный прогон ничего не делает.
"""

FIELDS = [
    ("purchase.order", "partner_id", "Продавец", "Поставщик"),
    ("purchase.order", "user_id", "Покупатель", "Закупщик"),
]


def migrate(cr, version):
    for model, name, old, new in FIELDS:
        cr.execute(
            """
            UPDATE ir_model_fields
               SET field_description = jsonb_set(field_description, '{ru_RU}', to_jsonb(%s::text))
             WHERE model = %s AND name = %s
               AND field_description->>'ru_RU' = %s
            """,
            (new, model, name, old),
        )
