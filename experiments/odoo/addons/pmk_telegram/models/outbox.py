# -*- coding: utf-8 -*-
"""Очередь сообщений в группу, которые не дошли до Телеграма (16.10.2026).

Зачем. В ночь на 16.10 с сервера пропал маршрут до api.telegram.org: бот
получал нажатия, а ответить не мог, и уведомление о деньгах ушло без файла.
Теперь сообщение в группу (поступления, сводки) при обрыве связи не теряется:
ложится сюда и досылается по расписанию раз в 2 минуты, когда связь вернётся.

Правила:
* в очередь идёт только обрыв СВЯЗИ (requests: нет соединения, таймаут); отказ
  самого Телеграма (неверный формат, бот выгнан из группы) — не повод слать
  снова то же самое;
* порядок сохраняется: пока в очереди что-то есть, новые сообщения встают за
  ним, а не обгоняют;
* сутки без связи — запись помечается «просрочено» и остаётся в журнале.
"""
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

EXPIRE_HOURS = 24
MAX_REFUSALS = 5


class PmkTelegramOutbox(models.Model):
    _name = "pmk.telegram.outbox"
    _description = "Очередь сообщений в Телеграм"
    _order = "id"

    state = fields.Selection([("pending", "Ждёт связи"), ("sent", "Отправлено"),
                              ("dead", "Не отправлено")], default="pending", required=True,
                             index=True)
    kind = fields.Char("Вид уведомления", default="main")
    text = fields.Text("Текст")
    markup = fields.Text("Кнопки (JSON)")
    file_ids = fields.Many2many("ir.attachment", string="Файлы")
    attempts = fields.Integer("Попыток")
    last_error = fields.Char("Ошибка")
    sent_at = fields.Datetime("Отправлено")

    @api.model
    def pmk_pending(self):
        return self.search_count([("state", "=", "pending")]) > 0

    @api.model
    def pmk_enqueue(self, text, files, markup, kind):
        files = files or []
        atts = self.env["ir.attachment"].sudo().create([{
            "name": name, "raw": raw, "res_model": self._name} for name, raw in files])
        rec = self.sudo().create({
            "kind": kind, "text": text, "file_ids": [(6, 0, atts.ids)],
            "markup": json.dumps(markup, ensure_ascii=False) if markup else False,
        })
        atts.write({"res_id": rec.id})
        _logger.warning("Телеграм: сообщение в очередь (%s), всего ждёт %d",
                        kind, self.search_count([("state", "=", "pending")]))
        return rec

    def _pmk_files(self):
        return [(a.name, a.raw) for a in self.file_ids.sorted("id")]

    @api.model
    def _cron_flush(self):
        bot = self.env["pmk.telegram.bot"].sudo()
        now = fields.Datetime.now()
        for rec in self.search([("state", "=", "pending")]):
            if rec.create_date < now - timedelta(hours=EXPIRE_HOURS):
                rec.write({"state": "dead", "last_error": "сутки без связи с Телеграмом"})
                continue
            ok, network_down = bot._pmk_group_deliver(
                rec.text, rec._pmk_files(), json.loads(rec.markup) if rec.markup else None,
                rec.kind)
            rec.attempts += 1
            if ok:
                rec.write({"state": "sent", "sent_at": now, "last_error": False})
                rec.file_ids.sudo().unlink()
                continue
            if network_down:
                rec.last_error = "нет связи с Телеграмом"
                break                          # связи нет — остальные тоже не дойдут, порядок держим
            rec.last_error = "Телеграм отказал"
            if rec.attempts >= MAX_REFUSALS:
                rec.state = "dead"
