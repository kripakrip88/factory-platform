# -*- coding: utf-8 -*-
"""Разбор почты — работа фона ассистента: в свободные потоки, по JOBS_AT_ONCE."""
from odoo import api, models

from .triage import JOBS_AT_ONCE


class AiChatMailJobs(models.AbstractModel):
    _inherit = "pmk.ai.chat"

    @api.model
    def _worker_jobs(self, free):
        jobs = super()._worker_jobs(free)
        Triage = self.env["pmk.ai.mail.triage"].sudo()
        left = min(free - len(jobs), JOBS_AT_ONCE - Triage.search_count([("state", "=", "running")]))
        if not Triage._enabled():
            return jobs
        Triage._enqueue()
        return jobs + [("pmk.ai.mail.triage", "_process", tid) for tid in Triage._claim(left)]
