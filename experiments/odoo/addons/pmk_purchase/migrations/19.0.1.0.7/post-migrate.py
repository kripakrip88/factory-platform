# -*- coding: utf-8 -*-
"""Рассылка запросов прайсов — только с zakaz@pmkpark.ru (18.10.2026).

Шаблон письма помечен noupdate (текст правят в «Закупки → Рассылка прайсов»),
поэтому новое значение из XML до живой базы само не доедет. Меняем одно поле —
отправителя; тему и текст, которые мог поправить Антон, не трогаем. Письмо
с этого адреса уходит через сервер Бегет: его фильтр отправителя —
zakaz@pmkpark.ru, и Odoo выбирает сервер по нему.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tmpl = env.ref("pmk_purchase.mail_template_price_request", raise_if_not_found=False)
    if tmpl:
        tmpl.email_from = "zakaz@pmkpark.ru"
