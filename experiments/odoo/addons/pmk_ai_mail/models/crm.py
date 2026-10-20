# -*- coding: utf-8 -*-
"""Колонка «Разобрал ассистент» и блок разбора в сделке (20.10.2026).

Колонка стоит первой (sequence −1), но стадией по умолчанию НЕ становится: ядро
CRM ставит новой сделке стадию с наименьшим порядком (_stage_find), и без
исключения в неё падали бы все сделки — из почты кнопкой, вручную, из бота.
Такие стадии помечены pmk_ai_only и из выбора по умолчанию убраны.
"""
from odoo import _, api, fields, models
from odoo.fields import Domain


class CrmStageAi(models.Model):
    _inherit = "crm.stage"

    pmk_ai_only = fields.Boolean(
        "Только для ассистента",
        help="Сюда кладёт сделки ассистент из разбора почты. Новая сделка по умолчанию сюда не попадает.")


class CrmLeadAi(models.Model):
    _inherit = "crm.lead"

    pmk_ai_triage_id = fields.Many2one("pmk.ai.mail.triage", "Разбор ассистента", index=True,
                                       ondelete="set null", copy=False)
    pmk_ai_card = fields.Html("Разобрал ассистент", compute="_compute_pmk_ai_card", sanitize=False)
    pmk_ai_rating = fields.Selection(related="pmk_ai_triage_id.rating", string="Оценка разбора")
    pmk_ai_feedback = fields.Text(related="pmk_ai_triage_id.feedback", readonly=False,
                                  string="Замечание к разбору",
                                  help="Что ассистент понял не так или что учесть в следующий раз — "
                                       "он прочитает это с правилами при разборе следующих писем.")

    @api.depends("pmk_ai_triage_id.data_json", "pmk_ai_triage_id.summary")
    def _compute_pmk_ai_card(self):
        for lead in self:
            lead.pmk_ai_card = lead.pmk_ai_triage_id.sudo()._card_html() if lead.pmk_ai_triage_id else False

    def _stage_find(self, team_id=False, domain=None, order="sequence, id", limit=1):
        domain = Domain(domain or []) & Domain("pmk_ai_only", "=", False)
        return super()._stage_find(team_id=team_id, domain=domain, order=order, limit=limit)

    def write(self, vals):
        # Замечание пишут прямо в сделке — запись разбора у человека без прав
        # на неё (только админ) — пишем точечно sudo.
        if "pmk_ai_feedback" in vals:
            feedback = vals.pop("pmk_ai_feedback")
            for lead in self.filtered("pmk_ai_triage_id"):
                lead.check_access("write")
                lead.pmk_ai_triage_id.sudo().write({
                    "feedback": feedback or False, "rated_by": self.env.uid,
                    "rated_on": fields.Datetime.now()})
        return super().write(vals) if vals else True

    def action_pmk_ai_good(self):
        self.ensure_one()
        self.check_access("write")
        self.pmk_ai_triage_id._rate("good")
        return True

    def action_pmk_ai_bad(self):
        self.ensure_one()
        self.check_access("write")
        self.pmk_ai_triage_id._rate("bad")
        return True
