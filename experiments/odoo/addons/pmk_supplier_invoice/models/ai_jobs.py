# -*- coding: utf-8 -*-
"""Счета поставщиков — работа фона ассистента (odoo-ai-worker), по одному за раз."""
from odoo import api, models

from .recognize import JOBS_AT_ONCE


class AiChatSupplierInvoiceJobs(models.AbstractModel):
    _inherit = "pmk.ai.chat"

    @api.model
    def _worker_jobs(self, free):
        jobs = super()._worker_jobs(free)
        Invoice = self.env["pmk.supplier.invoice"].sudo()
        left = min(free - len(jobs), JOBS_AT_ONCE - Invoice.search_count([("state", "=", "running")]))
        if Invoice._enabled():
            Invoice._enqueue()
        # Загруженный вручную файл распознаётся и при выключенном отборе почты.
        return jobs + [("pmk.supplier.invoice", "_process", iid) for iid in Invoice._claim(left)]
