# -*- coding: utf-8 -*-
"""«Запрос КП» вместо «Запрос на коммерческое предложение» у закупки.

Антон, 28.09.2026: «запрос коммерческого предложения можем переделать в
запрос КП?». Длинное штатное название не влезало в кнопку стадий и читалось
тяжело. Пара статусов переименована вместе, чтобы читалась цепочкой:
«Запрос КП → Запрос КП отправлен → Заказ на покупку» (было непонятное
«ЗП отправлен»). Заодно — пункт меню и название списка запросов: они же
видны в строке пути.

Заголовок над номером в форме закупки правит вид
views/purchase_order_views.xml — разметка вида хранится иначе.

ПОЧЕМУ SQL ПО ТЕКУЩЕМУ ЗНАЧЕНИЮ. Это переводы из базы (jsonb по языкам).
Меняем русский ключ, только если там ещё штатный перевод Odoo: ручную правку
не затираем, повторный прогон ничего не делает. Обновление модуля purchase
без --i18n-overwrite записанный перевод не перезапишет (проверено 20.09).
"""

SELECTION = [
    ("draft", "Запрос на коммерческое предложение", "Запрос КП"),
    ("sent", "ЗП отправлен", "Запрос КП отправлен"),
]
NAMES = [("Запросы на коммерческое предложение", "Запросы КП")]


def migrate(cr, version):
    for value, old, new in SELECTION:
        cr.execute(
            """
            UPDATE ir_model_fields_selection s
               SET name = jsonb_set(s.name, '{ru_RU}', to_jsonb(%s::text))
              FROM ir_model_fields f
             WHERE f.id = s.field_id
               AND f.model = 'purchase.order' AND f.name = 'state'
               AND s.value = %s AND s.name->>'ru_RU' = %s
            """,
            (new, value, old),
        )
    for table in ("ir_ui_menu", "ir_act_window"):
        for old, new in NAMES:
            cr.execute(
                f"""
                UPDATE {table}
                   SET name = jsonb_set(name, '{{ru_RU}}', to_jsonb(%s::text))
                 WHERE name->>'ru_RU' = %s
                """,
                (new, old),
            )
