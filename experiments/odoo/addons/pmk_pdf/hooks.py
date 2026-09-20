# -*- coding: utf-8 -*-
"""Привязка редактора к документам — МЯГКАЯ, без зависимостей между модулями.

Кнопка «Правка PDF» должна появиться в меню действий у документов завода. Но
объявить это данными нельзя, не сделав pmk_pdf зависимым от pmk_calc (или
наоборот) — а они независимы намеренно: калькуляторы должны работать без
редактора, редактор без калькуляторов.

Поэтому при установке просто смотрим, какие из перечисленных моделей вообще
есть в системе, и привязываемся к ним. Нет модуля — нет и привязки, никто не
падает. Список дополняется одной строкой.
"""

import logging

_logger = logging.getLogger(__name__)

# Документы, у которых бывают приложенные PDF. Штатные модели Odoo включены
# на случай, если продажи и закупки начнут вести в системе.
TARGET_MODELS = (
    "pmk.metal.spec",
    "pmk.dobor.order",
    "sale.order",
    "purchase.order",
    "res.partner",
)

ACTION_CODE = """
target = records[:1] if records else record
if target:
    action = {
        "type": "ir.actions.client",
        "tag": "pmk_pdf_editor",
        "name": "Правка PDF",
        "context": {
            "pmk_res_model": target._name,
            "pmk_res_id": target.id,
        },
    }
"""


def post_init_hook(env):
    bound = []
    for model_name in TARGET_MODELS:
        model = env["ir.model"].search([("model", "=", model_name)], limit=1)
        if not model:
            continue
        key = "action_edit_pdf_%s" % model_name.replace(".", "_")
        if env.ref("pmk_pdf.%s" % key, raise_if_not_found=False):
            continue
        action = env["ir.actions.server"].create({
            "name": "Правка PDF",
            "model_id": model.id,
            "binding_model_id": model.id,
            "binding_type": "action",
            "state": "code",
            "code": ACTION_CODE,
        })
        # Свой xmlid — чтобы повторная установка не плодила копии, а удаление
        # модуля убрало привязку за собой.
        env["ir.model.data"].create({
            "name": key,
            "module": "pmk_pdf",
            "model": "ir.actions.server",
            "res_id": action.id,
            "noupdate": True,
        })
        bound.append(model_name)
    _logger.info("pmk_pdf: редактор привязан к моделям: %s", ", ".join(bound) or "нет")
