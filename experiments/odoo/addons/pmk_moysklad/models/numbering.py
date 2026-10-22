# -*- coding: utf-8 -*-
"""Номер счёта, сделанного в Odoo: продолжает нумерацию МоегоСклада с буквой «д» (Антон
22.10.2026: «наши счета можно маркировать например счёт 433д — буква д будет означать, что счёт
сделан из Odoo»; выбрал «продолжать номера МС: 1233д…»).

Следующий номер = наибольший номер этого года среди счетов МС («01232») и наших («1232д») + 1.
Счёт МС, пришедший позже, может взять то же число без «д» — так договорились: буква и различает.
Номер выдаётся под блокировкой транзакции (два счёта в одну секунду не получат один номер).
Счета из МоегоСклада приходят со своим номером, редакции («ред. 2») — с номером счёта: их не
трогаем — только те, что заводятся без номера.
"""
from odoo import _, api, fields, models

SUFFIX = "д"


class SaleOrderNumber(models.Model):
    _inherit = "sale.order"

    def _pmk_next_d_number(self):
        cr = self.env.cr
        cr.execute("SELECT pg_advisory_xact_lock(hashtext('pmk_sale_order_d_number'))")
        year_start = fields.Date.context_today(self).replace(month=1, day=1)
        cr.execute("""
            SELECT COALESCE(MAX(substring(name FROM '^0*([0-9]{1,9})(?:%s)?$')::int), 0)
              FROM sale_order
             WHERE name ~ '^[0-9]{1,9}(%s)?$' AND date_order >= %%s
        """ % (SUFFIX, SUFFIX), (year_start,))
        return "%s%s" % (cr.fetchone()[0] + 1, SUFFIX)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (None, False, "", "New", _("New")) and not vals.get("pmk_ms_id"):
                vals["name"] = self._pmk_next_d_number()
        return super().create(vals_list)
