# -*- coding: utf-8 -*-
"""Карточка «Сделаю: …» — предложенное ассистентом действие (19.11.2026).

Ассистент только готовит карточку: что именно будет сделано (строки для человека) и данные
для выполнения (JSON). Выполняет её человек кнопкой «Выполнить» — его же правами, без sudo:
нет прав завести сделку — Odoo так и скажет. Повторно выполнить нельзя (состояние «Выполнено»).

Виды:
  deal   — сделка из письма (+ контрагент по ИНН из DaData, контакт, письмо с файлами в сделку);
  konstr — расчёт «Конструкции» в сделке по спецификации из файла сделки.
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

KINDS = [("deal", "Сделка из письма"), ("konstr", "Расчёт по спецификации")]
STATES = [("proposed", "Предложено"), ("done", "Выполнено"), ("cancelled", "Отменено"), ("failed", "Не вышло")]


class PmkAiProposal(models.Model):
    _name = "pmk.ai.proposal"
    _description = "Ассистент: предложенное действие"
    _order = "id"

    user_id = fields.Many2one("res.users", "Кому предложено", required=True, index=True, ondelete="cascade")
    request_id = fields.Many2one("pmk.ai.request", "Вопрос", index=True, ondelete="cascade")
    kind = fields.Selection(KINDS, "Что", required=True)
    title = fields.Char("Заголовок карточки", required=True)
    lines_json = fields.Text("Строки карточки (JSON)")
    warn = fields.Char("Предупреждение")
    payload_json = fields.Text("Данные для выполнения (JSON)")
    state = fields.Selection(STATES, "Состояние", default="proposed", required=True, index=True)
    result_model = fields.Char("Создано: модель")
    result_id = fields.Integer("Создано: id")
    result_name = fields.Char("Создано")
    error = fields.Char("Ошибка")
    done_at = fields.Datetime("Выполнено")

    # ─── для панели ─────────────────────────────────────────────────────
    def _card(self):
        self.ensure_one()
        try:
            lines = json.loads(self.lines_json or "[]")
        except ValueError:
            lines = []
        return {"id": self.id, "kind": self.kind, "title": self.title, "lines": lines, "warn": self.warn or "",
                "state": self.state, "error": self.error or "",
                "result": {"model": self.result_model, "id": self.result_id, "name": self.result_name}
                if self.result_model and self.result_id else False}

    def _payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload_json or "{}")
        except ValueError:
            return {}


class PmkAiChatProposals(models.AbstractModel):
    _inherit = "pmk.ai.chat"

    def _own_proposal(self, proposal_id):
        prop = self.env["pmk.ai.proposal"].sudo().browse(int(proposal_id or 0)).exists()
        if not prop or prop.user_id != self.env.user:
            raise AccessError(_("Карточка не найдена."))
        return prop

    @api.model
    def execute_proposal(self, proposal_id):
        """Кнопка «Выполнить»: действие правами нажавшего. → карточка в новом состоянии."""
        prop = self._own_proposal(proposal_id)
        if prop.state != "proposed":
            return prop._card()
        # Карточку читаем служебно (sudo), а действие — правами нажавшего: self здесь без sudo.
        handler = getattr(self.sudo(False), "_do_%s" % prop.kind, None)
        if not handler:
            raise UserError(_("Неизвестное действие."))
        payload = prop._payload()
        try:
            with self.env.cr.savepoint():
                model, res_id, name = handler(payload)
        except (UserError, AccessError) as exc:
            prop.write({"state": "failed", "error": str(exc)[:500]})
            return prop._card()
        except Exception as exc:  # noqa: BLE001 — карточка не должна ронять панель
            _logger.exception("pmk_ai_actions: карточка %s", prop.id)
            prop.write({"state": "failed", "error": _("Не вышло: %s") % exc.__class__.__name__})
            return prop._card()
        prop.write({"state": "done", "result_model": model, "result_id": res_id, "result_name": name,
                    "done_at": fields.Datetime.now(), "error": False})
        return prop._card()

    @api.model
    def cancel_proposal(self, proposal_id):
        prop = self._own_proposal(proposal_id)
        if prop.state == "proposed":
            prop.state = "cancelled"
        return prop._card()

    def _request_cards(self, request):
        return [p._card() for p in self.env["pmk.ai.proposal"].sudo().search(
            [("request_id", "=", request.id)], order="id")]

    @api.model
    def poll(self, request_id):
        out = super().poll(request_id)
        if out.get("state") == "done":
            req = self.env["pmk.ai.request"].sudo().browse(int(request_id)).exists()
            if req and req.user_id == self.env.user:
                out["proposals"] = self._request_cards(req)
        return out

    @api.model
    def thread_messages(self, thread_id):
        """Как у pmk_ai, плюс карточки у ответов (ответ = каждая вторая реплика, по порядку вопросов)."""
        out = super().thread_messages(thread_id)
        if out.get("error"):
            return out
        thread = self.env["pmk.ai.thread"].sudo().browse(int(thread_id))
        answers = [i for i in out.get("items", []) if i.get("role") == "assistant"]
        for req, item in zip(thread.request_ids.sorted("id"), answers):
            if not item.get("pending") and not item.get("error"):
                cards = self._request_cards(req)
                if cards:
                    item["proposals"] = cards
        return out

    @api.model
    def _process_request(self, request_id):
        # Номер вопроса — инструментам propose_*: карточка привязывается к своему ответу.
        return super(PmkAiChatProposals, self.with_context(pmk_ai_request_id=request_id))._process_request(request_id)

    def _new_proposal(self, kind, title, lines, payload, warn=""):
        """Записать карточку от имени спрашивающего → короткий ответ для модели."""
        prop = self.env["pmk.ai.proposal"].sudo().create({
            "user_id": self.env.uid, "request_id": self.env.context.get("pmk_ai_request_id") or False,
            "kind": kind, "title": title[:200], "lines_json": json.dumps(lines, ensure_ascii=False),
            "warn": (warn or "")[:250] or False, "payload_json": json.dumps(payload, ensure_ascii=False)})
        return {"карточка": prop.id, "статус": "показана человеку с кнопкой «Выполнить» — ещё НЕ сделано",
                "что": title, "строки": lines}
