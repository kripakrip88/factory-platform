# -*- coding: utf-8 -*-
"""Рабочее окно рассылки запросов прайсов.

Механизм рассылки разложен по трём техническим экранам Odoo: расписание — в
плановых заданиях, рубильник и потолок — в системных параметрах, текст письма —
в шаблонах. Снабженцу туда ходить незачем и страшно.

Эта модель — одно окно поверх них. Своих данных она НЕ хранит: каждое поле
читает и пишет туда, где значение живёт на самом деле. Так нельзя получить
расхождение «в окне одно, в задании другое».
"""
import datetime
import logging

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TZ = "Asia/Vladivostok"
CRON_XMLID = "pmk_purchase.cron_price_request"
TEMPLATE_XMLID = "pmk_purchase.mail_template_price_request"
PARAM_ENABLED = "pmk.price_request.enabled"
PARAM_MAX = "pmk.price_request.max_per_run"

WEEKDAYS = [
    ("0", "Понедельник"), ("1", "Вторник"), ("2", "Среда"), ("3", "Четверг"),
    ("4", "Пятница"), ("5", "Суббота"), ("6", "Воскресенье"),
]


class PriceMailing(models.Model):
    _name = "pmk.price.mailing"
    _description = "Рассылка запросов прайсов"

    name = fields.Char(default="Рассылка запросов прайсов", readonly=True)

    # ── рубильник и потолок (живут в системных параметрах)
    enabled = fields.Boolean(
        "Рассылка включена",
        compute="_compute_settings", inverse="_inverse_enabled",
        help="Пока выключено, задание просыпается по расписанию и ничего не "
             "отправляет. Это главный рубильник.",
    )
    max_per_run = fields.Integer(
        "Не больше писем за раз",
        compute="_compute_settings", inverse="_inverse_max",
        help="Остальные подождут следующего раза.",
    )

    # ── расписание (живёт в плановом задании; nextcall хранится в UTC)
    weekday = fields.Selection(
        WEEKDAYS, string="День недели",
        compute="_compute_schedule", inverse="_inverse_schedule")
    hour = fields.Integer("Час", compute="_compute_schedule", inverse="_inverse_schedule")
    minute = fields.Integer("Минута", compute="_compute_schedule", inverse="_inverse_schedule")
    next_run = fields.Char("Следующая отправка", compute="_compute_schedule")
    last_run = fields.Datetime("Последний прогон", compute="_compute_schedule")

    # ── письмо (живёт в шаблоне)
    subject = fields.Char("Тема письма", compute="_compute_letter", inverse="_inverse_letter")
    body_html = fields.Html(
        "Текст письма", compute="_compute_letter", inverse="_inverse_letter",
        sanitize=False,
        help="Доступны подстановки Odoo. Список групп поставки подставляется "
             "автоматически по каждому получателю.")

    # ── что происходит сейчас
    recipient_count = fields.Integer("Получателей в рассылке", compute="_compute_stats")
    supplier_count = fields.Integer("Всего поставщиков в реестре", compute="_compute_stats")
    queue_count = fields.Integer("Писем в очереди на отправку", compute="_compute_stats")
    server_ready = fields.Boolean("Почтовый сервер настроен", compute="_compute_stats")
    test_email = fields.Char("Адрес для пробного письма",
                             help="Пробное письмо уходит только сюда и никому больше.")

    # ------------------------------------------------------------------
    # вход
    # ------------------------------------------------------------------
    @api.model
    def action_open(self):
        """Открыть единственную запись, создав её при первом заходе."""
        record = self.search([], limit=1) or self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("Рассылка прайсов"),
            "res_model": self._name,
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    # чтение и запись настоящих хранилищ
    # ------------------------------------------------------------------
    def _icp(self):
        return self.env["ir.config_parameter"].sudo()

    def _cron(self):
        return self.env.ref(CRON_XMLID, raise_if_not_found=False)

    def _template(self):
        return self.env.ref(TEMPLATE_XMLID, raise_if_not_found=False)

    def _compute_settings(self):
        icp = self._icp()
        on = icp.get_param(PARAM_ENABLED, "0") == "1"
        cap = int(icp.get_param(PARAM_MAX, "30") or 30)
        for rec in self:
            rec.enabled = on
            rec.max_per_run = cap

    def _inverse_enabled(self):
        for rec in self:
            self._icp().set_param(PARAM_ENABLED, "1" if rec.enabled else "0")
            _logger.info("Рассылка прайсов %s пользователем %s",
                         "ВКЛЮЧЕНА" if rec.enabled else "выключена", self.env.user.login)

    def _inverse_max(self):
        for rec in self:
            self._icp().set_param(PARAM_MAX, str(max(1, rec.max_per_run or 1)))

    def _compute_schedule(self):
        cron = self._cron()
        tz = pytz.timezone(TZ)
        for rec in self:
            if not cron or not cron.nextcall:
                rec.weekday, rec.hour, rec.minute = "0", 9, 10
                rec.next_run, rec.last_run = _("расписание не заведено"), False
                continue
            local = pytz.UTC.localize(cron.nextcall).astimezone(tz)
            rec.weekday = str(local.weekday())
            rec.hour, rec.minute = local.hour, local.minute
            rec.next_run = local.strftime("%d.%m.%Y в %H:%M") + " (Владивосток)"
            rec.last_run = cron.lastcall

    def _inverse_schedule(self):
        cron = self._cron()
        if not cron:
            return
        for rec in self:
            cron.sudo().write({"nextcall": self._next_occurrence(
                int(rec.weekday or 0), rec.hour or 0, rec.minute or 0)})

    @staticmethod
    def _next_occurrence(weekday, hour, minute):
        """Ближайшее наступление дня недели и времени — в UTC.

        Считаем в часовом поясе завода: `nextcall` хранится в UTC, и записать
        туда местное время значит промахнуться на десять часов.
        """
        tz = pytz.timezone(TZ)
        now = datetime.datetime.now(tz)
        ahead = (weekday - now.weekday()) % 7
        day = now + datetime.timedelta(days=ahead)
        local = tz.localize(datetime.datetime(day.year, day.month, day.day, hour, minute))
        if local <= now:
            local += datetime.timedelta(days=7)
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _compute_letter(self):
        tmpl = self._template()
        for rec in self:
            rec.subject = tmpl.subject if tmpl else False
            rec.body_html = tmpl.body_html if tmpl else False

    def _inverse_letter(self):
        tmpl = self._template()
        if not tmpl:
            return
        for rec in self:
            tmpl.sudo().write({"subject": rec.subject, "body_html": rec.body_html})

    def _compute_stats(self):
        P = self.env["res.partner"]
        recipients = P.search_count([("pmk_price_mailing", "=", True)])
        suppliers = P.search_count([("pmk_price_supplier", "=", True)])
        queued = self.env["mail.mail"].sudo().search_count([("state", "=", "outgoing")])
        ready = bool(self.env["ir.mail_server"].sudo().search_count([]))
        for rec in self:
            rec.recipient_count = recipients
            rec.supplier_count = suppliers
            rec.queue_count = queued
            rec.server_ready = ready

    # ------------------------------------------------------------------
    # кнопки
    # ------------------------------------------------------------------
    def action_open_recipients(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pmk_purchase.action_price_supplier")
        action["context"] = dict(self.env.context, search_default_in_mailing=1)
        return action

    def action_open_queue(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Очередь исходящих писем"),
            "res_model": "mail.mail",
            "view_mode": "list,form",
            "domain": [("state", "in", ("outgoing", "exception"))],
        }

    def action_send_test(self):
        """Пробное письмо — только на указанный адрес, никому больше."""
        self.ensure_one()
        if not self.test_email:
            raise UserError(_("Укажите адрес, на который отправить пробное письмо."))
        tmpl = self._template()
        if not tmpl:
            raise UserError(_("Шаблон письма не найден."))
        sample = self.env["res.partner"].search(
            [("pmk_price_supplier", "=", True)], limit=1)
        if not sample:
            raise UserError(_("В реестре нет ни одного поставщика — не на чём показать письмо."))
        # force_send=True намеренно: пробное письмо должно уйти сразу, иначе
        # человек не поймёт, работает оно или встало в очередь.
        tmpl.send_mail(sample.id, force_send=True,
                       email_values={"email_to": self.test_email})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Пробное письмо отправлено"),
                "message": _("Отправлено на %s. Подставлены данные поставщика «%s».",
                             self.test_email, sample.display_name),
                "sticky": False,
            },
        }

    def action_run_now(self):
        """Запустить рассылку немедленно, не дожидаясь расписания."""
        self.ensure_one()
        if not self.enabled:
            raise UserError(_(
                "Рассылка выключена. Включите её, иначе запуск ничего не сделает."))
        sent = self.env["res.partner"]._cron_send_price_requests()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success" if sent else "warning",
                "title": _("Рассылка запущена"),
                "message": _("Поставлено в очередь писем: %s.", sent or 0),
                "sticky": False,
            },
        }
