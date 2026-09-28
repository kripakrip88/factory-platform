# -*- coding: utf-8 -*-
"""Цвета стадий воронки по карте цветов разбора UX.

Кнопка стадий в сделке красится бледным тоном цвета стадии (pmk_theme,
statusbar_compact.js). У «Расчёта» стоял красный, а красный в согласованной
карте цветов — «проблема». Решение Антона 28.09.2026 («делай»):
Расчёт — голубой («в работе»), КП отправлено — жёлтый («ждём клиента»).
Заявка (фиолетовый) и Выиграно (зелёный) не меняются.

Цвет — номер палитры Odoo: 1 красный, 3 жёлтый, 8 синий. Меняем, только если
стоит прежний цвет: выбранный потом в «Настройки CRM → Этапы» не затираем.
"""

COLORS = [
    # xmlid в crm, прежний цвет, новый
    ("stage_lead2", 1, 8),
    ("stage_lead3", 8, 3),
]


def migrate(cr, version):
    for xmlid, old, new in COLORS:
        cr.execute(
            """
            UPDATE crm_stage s
               SET color = %s
              FROM ir_model_data d
             WHERE d.module = 'crm' AND d.name = %s
               AND d.model = 'crm.stage' AND d.res_id = s.id
               AND s.color = %s
            """,
            (new, xmlid, old),
        )
