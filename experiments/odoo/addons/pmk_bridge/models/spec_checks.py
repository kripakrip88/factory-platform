# -*- coding: utf-8 -*-
"""«Проверка» расчёта — что система сама нашла не так (Антон 28.10.2026, по макету Lovable).

Не галочки, которые жмут руками, а список найденного; каждый пункт ведёт к месту ошибки
(вкладка или поле), ничего не запрещает (правило «сначала наблюдать»). Всё в порядке — одна
зелёная строка «Всё заполнено». Список заменяет большие жёлтые плашки над шапкой; показывает
его виджет pmk_spec_checks в колонке «Итог» (static/src/js/spec_checks.js).
"""
import json

from odoo import api, fields, models


def _money(amount):
    return ("{:,.0f}".format(abs(amount or 0.0))).replace(",", " ")


class MetalSpecChecks(models.Model):
    _inherit = "pmk.metal.spec"

    pmk_checks_json = fields.Char("Проверка", compute="_compute_pmk_checks")

    @api.depends("no_price_count", "kp_skip_count", "margin_amount", "price_customer_total",
                 "partner_id", "layout_stale")
    def _compute_pmk_checks(self):
        for spec in self:
            items = []
            if spec.no_price_count:
                items.append({"key": "no_price", "tone": "warn", "tab": "prices",
                              "text": "Нет цены у %d поз. — металл занижен" % spec.no_price_count})
            if spec.price_customer_total and spec.margin_amount < 0:
                items.append({"key": "margin", "tone": "bad", "tab": "pmk_summary",
                              "text": "Маржа в минусе: −%s ₽" % _money(spec.margin_amount)})
            if spec.kp_skip_count:
                items.append({"key": "kp_skip", "tone": "warn", "tab": "pmk_summary",
                              "text": "Без цены клиенту: %d изд. — не попадут в КП" % spec.kp_skip_count})
            if spec.layout_stale:
                items.append({"key": "layout", "tone": "warn", "tab": "layout",
                              "text": "Раскладка устарела — разложить листы заново"})
            if not spec.partner_id:
                items.append({"key": "partner", "tone": "warn", "field": "partner_id",
                              "text": "Не выбран контрагент"})
            spec.pmk_checks_json = json.dumps(items, ensure_ascii=False)
