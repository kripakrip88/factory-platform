# -*- coding: utf-8 -*-
from odoo import fields, models

from ..tools import claude


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pmk_ai_api_key = fields.Char(
        "Ключ API Anthropic", config_parameter="pmk_ai.api_key",
        help="console.anthropic.com → API Keys. Вписывает администратор; в чат и в письма не отправлять.")
    pmk_ai_model = fields.Char("Модель", config_parameter="pmk_ai.model", default=claude.DEFAULT_MODEL)
    pmk_ai_api_base = fields.Char(
        "Адрес API", config_parameter="pmk_ai.api_base", default=claude.DEFAULT_BASE,
        help="Обычно https://api.anthropic.com. Если связь с сервера плохая — адрес ретранслятора.")
    pmk_ai_status = fields.Char("Последняя проверка", compute="_compute_pmk_ai_status")
    # Расход (18.10.2026: «пусть сотрудники видят лимиты и расходы»): лимит месяца и цена
    # токенов модели — для подсчёта в панели; тарифы Anthropic меняются, поэтому настройка.
    pmk_ai_budget = fields.Float("Лимит в месяц, $", config_parameter="pmk_ai.budget", default=100.0)
    pmk_ai_price_in = fields.Float("Цена входа, $ за 1 млн токенов (модель не из списка)", config_parameter="pmk_ai.price_in", default=2.0)
    pmk_ai_price_out = fields.Float("Цена выхода, $ за 1 млн токенов (модель не из списка)", config_parameter="pmk_ai.price_out", default=10.0)

    def _compute_pmk_ai_status(self):
        status = self.env["ir.config_parameter"].sudo().get_param("pmk_ai.last_status") or "ещё не было"
        for rec in self:
            rec.pmk_ai_status = status

    def action_pmk_ai_check(self):
        self.execute()  # сначала сохранить введённое
        params = self.env["ir.config_parameter"].sudo()
        try:
            text = claude.ping(params.get_param("pmk_ai.api_key"), params.get_param("pmk_ai.model"),
                               params.get_param("pmk_ai.api_base"))
            ok = True
        except claude.ClaudeError as exc:
            text, ok = str(exc), False
        stamp = fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%d.%m %H:%M")
        params.set_param("pmk_ai.last_status", "%s — %s" % (stamp, text))
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success" if ok else "danger", "title": "Ассистент", "message": text, "sticky": True}}
