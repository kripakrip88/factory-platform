# -*- coding: utf-8 -*-
"""Разовое заполнение связи «справочник → карточка товара» при установке моста.

Связь между 752 строками справочника и карточками номенклатуры уже существует в
базе — но в виде служебных записей `ir_model_data`, которые создали скрипты
загрузки. Поле `product_tmpl_id` (см. models/reference_link.py) появляется
пустым, и заполнять его руками по одной позиции немыслимо.

Хук переносит готовое соответствие в поле по тому же правилу имён, по которому
его и создавали: строка `pmk_calc.<имя>` → карточка `pmk_bridge.product_<имя>`.

⚠️ ХУК РАБОТАЕТ ТОЛЬКО ПРИ УСТАНОВКЕ. Ядро зовёт post_init_hook лишь когда
операция — install (odoo/modules/loading.py: `if update_operation == 'install'`).
При обновлении модуля (-u pmk_bridge) он НЕ выполнится. Если связи понадобится
перезаполнить позже, зовите функцию вручную из odoo shell:

    from odoo.addons.pmk_bridge.hooks import link_reference_products
    link_reference_products(env)

Повторный запуск безопасен: заполняются только пустые связи, уже проставленные
не трогаются — вдруг их поправили руками, зная лучше.
"""

import logging

from .models.reference_link import LINKED_MODELS

_logger = logging.getLogger(__name__)


def link_reference_products(env):
    """Проставить product_tmpl_id всем строкам справочника, у которых он пуст."""
    # Карту строим одним запросом на обе стороны, а не поиском в цикле по 753
    # позициям: иначе на установку уходит полторы тысячи мелких SELECT.
    data = env["ir.model.data"].sudo()

    for model_name in LINKED_MODELS:
        refs = data.search([("module", "=", "pmk_calc"), ("model", "=", model_name)])
        if not refs:
            _logger.info("pmk_bridge: у справочника %s нет строк с xml_id", model_name)
            continue

        # имя строки справочника → её id
        ref_by_name = {r.name: r.res_id for r in refs}

        cards = data.search([
            ("module", "=", "pmk_bridge"),
            ("model", "=", "product.template"),
            ("name", "in", ["product_%s" % name for name in ref_by_name]),
        ])
        # имя строки справочника → id карточки товара
        card_by_name = {c.name[len("product_"):]: c.res_id for c in cards}

        records = env[model_name].sudo().browse(list(ref_by_name.values())).exists()
        linked = skipped = missing = 0

        for name, res_id in ref_by_name.items():
            record = records.filtered(lambda r, i=res_id: r.id == i)
            if not record:
                continue
            if record.product_tmpl_id:
                skipped += 1
                continue
            tmpl_id = card_by_name.get(name)
            if not tmpl_id:
                missing += 1
                continue
            record.product_tmpl_id = tmpl_id
            linked += 1

        _logger.info(
            "pmk_bridge: %s — связано %s, уже было %s, без карточки %s",
            model_name, linked, skipped, missing,
        )
        # Позиция без карточки — не ошибка установки, а факт, который надо
        # видеть: такая строка посчитается в спецификации по нулевой цене.
        # Поэтому предупреждение, а не тихий пропуск.
        if missing:
            _logger.warning(
                "pmk_bridge: у %s позиций справочника %s нет карточки товара — "
                "материал по ним посчитается без цены",
                missing, model_name,
            )
