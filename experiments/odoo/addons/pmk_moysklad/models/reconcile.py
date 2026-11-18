# -*- coding: utf-8 -*-
"""Счета, удалённые в МоёмСкладе, — отменить и в Odoo (18.11.2026).

Синхронизация раз в 10 минут берёт только изменённое («updated после метки»), а
удалённый документ в этот список не попадает: 18.11 менеджер завёл счёт 01294
БСМ-МОСТ на 7,18 млн и через 4 минуты удалил его в МоёмСкладе, а в Odoo черновик
остался на сделке «Перильное ограждение По1».

Раз в сутки ночью: полный список идентификаторов счетов МоегоСклада (без строк —
~6 запросов по 1000) сверяется со счетами Odoo, пришедшими из МоегоСклада. Каждый
пропавший перепроверяется отдельным запросом: отменяем, только если МойСклад
подтвердил удаление (поле deleted или 404). Отменённый счёт снимается со сделки,
в истории счёта и сделки — пометка.

Предохранители: список МоегоСклада не дочитан или в нём меньше половины наших
счетов — ничего не трогаем; пропавших больше RECONCILE_MAX — тоже ничего, только
предупреждение в журнал (такое бывает при сбое, а не при работе менеджеров).
Счета, сделанные в Odoo (pmk_ms_from_odoo), не трогаем: главный для них — Odoo.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RECONCILE_PAGE = 1000
RECONCILE_MAX = 20


class PmkMoyskladReconcile(models.AbstractModel):
    _inherit = "pmk.moysklad"

    @api.model
    def _ms_all_invoice_ids(self):
        """Идентификаторы всех счетов МоегоСклада или None, если список не дочитан."""
        ids, offset, size = set(), 0, None
        while True:
            data = self._ms_get("entity/invoiceout", {"limit": RECONCILE_PAGE, "offset": offset})
            rows = data.get("rows") or []
            size = (data.get("meta") or {}).get("size", size)
            for row in rows:
                href = (row.get("meta") or {}).get("href") or ""
                if href:
                    ids.add(href.rsplit("/", 1)[-1])
            offset += RECONCILE_PAGE
            if not rows or size is None or offset >= size:
                break
        if size is None or len(ids) < size:
            return None
        return ids

    @api.model
    def _ms_invoice_deleted(self, mid):
        """МойСклад подтверждает удаление: документ с пометкой deleted или 404."""
        try:
            row = self._ms_get("entity/invoiceout/%s" % mid)
        except UserError as e:
            return " 404 " in " %s " % e
        return bool(row.get("deleted"))

    @api.model
    def _cron_ms_reconcile(self):
        if not self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.token"):
            return 0
        Order = self.env["sale.order"].with_context(active_test=False)
        ours = Order.search([("pmk_ms_id", "!=", False), ("pmk_ms_from_odoo", "=", False),
                             ("state", "!=", "cancel")])
        if not ours:
            return 0
        try:
            alive = self._ms_all_invoice_ids()
        except UserError as e:
            _logger.warning("pmk_moysklad: сверка удалённых счетов — МойСклад недоступен: %s", e)
            return 0
        if alive is None or len(alive) < len(ours) / 2:
            _logger.warning("pmk_moysklad: сверка удалённых счетов пропущена — список МоегоСклада "
                            "неполный (%s при %s наших)", alive and len(alive), len(ours))
            return 0
        gone = ours.filtered(lambda o: o.pmk_ms_id not in alive)
        if len(gone) > RECONCILE_MAX:
            _logger.warning("pmk_moysklad: в МоёмСкладе не найдено %s счетов (больше %s) — похоже на "
                            "сбой, ничего не отменяю: %s", len(gone), RECONCILE_MAX,
                            ", ".join(gone[:30].mapped("name")))
            return 0
        done = 0
        for order in gone:
            if not self._ms_invoice_deleted(order.pmk_ms_id):
                continue
            order._pmk_ms_cancel_deleted()
            done += 1
        if done:
            _logger.info("pmk_moysklad: отменено счетов, удалённых в МоёмСкладе: %s", done)
        return done


class SaleOrderMsDeleted(models.Model):
    _inherit = "sale.order"

    def _pmk_ms_cancel_deleted(self):
        """Счёт удалён в МоёмСкладе: отменить, снять со сделки, отметить в истории."""
        self.ensure_one()
        deal = self.opportunity_id
        order = self.with_context(pmk_ms_sync=True, tracking_disable=True, mail_notrack=True)
        order.write({"state": "cancel", "opportunity_id": False})
        order.message_post(body=_("Счёт удалён в МоёмСкладе — отменён и в Odoo."),
                           subtype_xmlid="mail.mt_note")
        if deal:
            deal.with_context(pmk_orders_skip=True).message_post(body=_(
                "Счёт %(inv)s на %(sum)s удалён в МоёмСкладе — отменён и отвязан от сделки.",
                inv=self.name, sum="{:,.2f} ₽".format(self.amount_total).replace(",", " ").replace(".", ","),
            ), subtype_xmlid="mail.mt_note")
