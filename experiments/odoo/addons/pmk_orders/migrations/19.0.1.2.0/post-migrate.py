# -*- coding: utf-8 -*-
"""Шаг З-15: у строк, где «Сдача (план)» уже стоит, — «правили руками».

Новое поле pmk_date_due_manual: сдачу, поставленную человеком, расчёт срока
(дата оплаты, очистка, «Выиграно») больше не трогает. До шага сдачу ставили
только руками (импорт из Excel, форма строки) — значит, у всех заполненных
она ручная. Строки без сдачи остаются «не правили»: внесут дату оплаты, а в
счёте «N раб. дней с момента оплаты» — сдача посчитается сама.

Названия строк, даты и суммы не меняются. Повторный прогон ничего не меняет.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE project_task
           SET pmk_date_due_manual = TRUE
         WHERE pmk_date_due IS NOT NULL
           AND pmk_date_due_manual IS NOT TRUE
    """)
    _logger.info("pmk_orders 19.0.1.2.0: «Сдачу правили руками» — у %s строк", cr.rowcount)
