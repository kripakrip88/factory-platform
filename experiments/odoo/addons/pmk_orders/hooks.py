# -*- coding: utf-8 -*-
"""Установка pmk_orders (шаг З-2): номер счёта по-русски.

Штатный нумератор заказов клиента sale.seq_sale_order (noupdate) даёт
«S00001» — английская буква в номере документа, который уходит клиенту.
Ставим «СЧ-00001» (как «СМ-» у расчёта и «СД-» у сделки), ТОЛЬКО пока
заказов клиента нет вовсе: у выставленных номер менять нельзя, иначе в
одной базе были бы «S00003» и «СЧ-00004».

Вызывается только при -i. Вернуть: Настройки → Технические → Нумерация →
«Sales Order» → префикс «S».
"""
import logging

_logger = logging.getLogger(__name__)

PREFIX = "СЧ-"


def post_init_hook(env):
    seq = env.ref("sale.seq_sale_order", raise_if_not_found=False)
    if not seq:
        return
    if seq.prefix != "S":
        _logger.info("pmk_orders: префикс счетов «%s» — не штатный, не трогаем", seq.prefix)
        return
    if env["sale.order"].sudo().with_context(active_test=False).search_count([], limit=1):
        _logger.info("pmk_orders: заказы клиента уже есть — префикс «S» оставлен")
        return
    seq.sudo().write({"prefix": PREFIX, "padding": 5})
    _logger.info("pmk_orders: номер счёта покупателю — %s00001", PREFIX)
