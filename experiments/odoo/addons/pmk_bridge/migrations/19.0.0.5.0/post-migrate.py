# -*- coding: utf-8 -*-
"""«Product created» в ленте товара — «Создано: Товар» (разбор UX, шаг 53).

Что, почему и как вернуть — pmk_bridge/tools/product_created_ru.py. Боевая
база, SELECT 07.10.2026: ожидается 753 записи у шаблонов товаров и 757 у
вариантов — 1 510; фактическое число — в журнале сервера. Повторный запуск
ничего не меняет.
"""
import logging

from odoo.addons.pmk_bridge.tools.product_created_ru import translate_product_created

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    changed = translate_product_created(cr)
    _logger.info("Шаг 53: «… created» в ленте товаров → «Создано: …» — %s записей %s",
                 sum(changed.values()), changed)
