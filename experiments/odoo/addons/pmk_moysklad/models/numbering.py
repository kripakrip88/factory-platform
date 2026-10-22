# -*- coding: utf-8 -*-
"""Номер счёта, сделанного в Odoo: продолжает нумерацию МоегоСклада в его же виде — «01233»
(Антон 22.10.2026: «продолжать номера МС»; сначала с буквой «д», в тот же день — «давай номер без
д, просто статус документа сделаем Odoo»: откуда счёт, покажет статус «Из Odoo» в МоёмСкладе —
этап 6 плана «сделка → счёт»).

Следующий номер = наибольший номер этого года среди счетов МС и наших + 1, пять цифр с нулями.
Пока счёт не выгружен в МС (этап 6), МС может выдать то же число своему счёту — номера совпадут;
различают их сделка и контрагент. Номер выдаётся под блокировкой транзакции (два счёта в одну
секунду не получат один номер). Счета из МоегоСклада приходят со своим номером, редакции («ред. 2»)
— с номером счёта: их не трогаем — только те, что заводятся без номера.
"""
from odoo import _, api, fields, models

PADDING = 5


class SaleOrderNumber(models.Model):
    _inherit = "sale.order"

    def _pmk_next_ms_number(self):
        cr = self.env.cr
        cr.execute("SELECT pg_advisory_xact_lock(hashtext('pmk_sale_order_ms_number'))")
        year_start = fields.Date.context_today(self).replace(month=1, day=1)
        cr.execute("""
            SELECT COALESCE(MAX(name::bigint), 0) FROM sale_order
             WHERE name ~ '^[0-9]{1,9}$' AND date_order >= %s
        """, (year_start,))
        return str(cr.fetchone()[0] + 1).zfill(PADDING)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (None, False, "", "New", _("New")) and not vals.get("pmk_ms_id"):
                vals["name"] = self._pmk_next_ms_number()
        return super().create(vals_list)
