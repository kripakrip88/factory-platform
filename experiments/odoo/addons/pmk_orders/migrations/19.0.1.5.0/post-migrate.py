# -*- coding: utf-8 -*-
"""19.0.1.5.0 — согласование счёта убрано (Антон 25.10.2026): статуса «На
согласовании» / «Согласован» больше нет — такие черновики снова «Черновик»."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("UPDATE sale_order SET pmk_status = 'draft' WHERE pmk_status IN ('approval', 'approved')")
    _logger.info("pmk_orders 19.0.1.5.0: статус согласования снят у %s счетов", cr.rowcount)
