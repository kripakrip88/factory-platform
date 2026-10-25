# -*- coding: utf-8 -*-
"""19.0.1.0.1 — «Правка PDF» снята с меню «⚙» счёта покупателю (Антон 25.10.2026).
Действие остаётся (xmlid модуля), без привязки к модели — в меню его нет."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    action = env.ref("pmk_pdf.action_edit_pdf_sale_order", raise_if_not_found=False)
    if action and action.binding_model_id:
        action.binding_model_id = False
        _logger.info("pmk_pdf 19.0.1.0.1: «Правка PDF» снята с меню счёта покупателю")
