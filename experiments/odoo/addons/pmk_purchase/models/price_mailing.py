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
# Кому пишет рассылка — реестр прайсов (как у крона, _cron_send_price_requests).
REGISTRY_DOMAIN = [("pmk_price_supplier", "=", True)]

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
        help="Пока выключено, задание просыпается по расписанию и ничего не "
             "отправляет. Это главный рубильник.",
    )
    max_per_run = fields.Integer("Не больше писем за раз", default=30,
                                 help="Остальные подождут следующего раза.")

    # ── расписание (живёт в плановом задании; nextcall хранится в UTC)
    weekday = fields.Selection(WEEKDAYS, string="День недели", default="0")
    # Час и минута остаются полями модели: из них _push_to_system собирает
    # nextcall задания, а _pull_from_system раскладывает его обратно. На
    # экране их нет — вместо двух полей одно «Время» (ниже).
    hour = fields.Integer("Час", default=9)
    minute = fields.Integer("Минута", default=10)
    # Разбор UX, шаг 28 (01.10.2026): «Час» и «Минута» двумя полями → одно
    # «Время» в виде 09:10 (виджет float_time: 9,1667 часа = 09:10). Своего
    # значения не хранит: читается из часа и минуты и пишет в них же, а
    # запись часа и минуты, как и раньше, раскладывает расписание в задание.
    send_time = fields.Float(
        "Время", compute="_compute_send_time", inverse="_inverse_send_time",
        help="Во сколько по Владивостоку уходят письма, часы:минуты.")
    next_run = fields.Char("Следующая отправка", compute="_compute_runtime")
    last_run = fields.Datetime("Последний прогон", compute="_compute_runtime")

    # ── письмо (живёт в шаблоне)
    subject = fields.Char("Тема письма")
    body_html = fields.Html(
        "Текст письма", sanitize=False,
        help="Доступны подстановки Odoo. Список групп поставки подставляется "
             "автоматически по каждому получателю.")

    # ── что происходит сейчас
    recipient_count = fields.Integer("Получателей в рассылке", compute="_compute_runtime")
    supplier_count = fields.Integer("Всего поставщиков в реестре", compute="_compute_runtime")
    queue_count = fields.Integer("Писем в очереди на отправку", compute="_compute_runtime")
    server_ready = fields.Boolean("Почтовый сервер настроен", compute="_compute_runtime")
    test_email = fields.Char("Адрес для пробного письма",
                             help="Пробное письмо уходит только сюда и никому больше.")

    # ------------------------------------------------------------------
    # вход
    # ------------------------------------------------------------------
    @api.model
    def action_open(self):
        """Открыть единственную запись, создав её при первом заходе."""
        record = self.search([], limit=1) or self.create({})
        # Подтягиваем при каждом открытии: настройки могли поменять напрямую —
        # в плановом задании, системных параметрах или шаблоне письма. Так
        # расхождение «в окне одно, в системе другое» не переживает открытия.
        record._pull_from_system()
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

    def _pull_from_system(self):
        """Прочитать настоящее состояние из задания, параметров и шаблона."""
        icp, cron, tmpl = self._icp(), self._cron(), self._template()
        tz = pytz.timezone(TZ)
        for rec in self:
            vals = {
                "enabled": icp.get_param(PARAM_ENABLED, "0") == "1",
                "max_per_run": int(icp.get_param(PARAM_MAX, "30") or 30),
            }
            if cron and cron.nextcall:
                local = pytz.UTC.localize(cron.nextcall).astimezone(tz)
                vals.update(weekday=str(local.weekday()), hour=local.hour, minute=local.minute)
            if tmpl:
                vals.update(subject=tmpl.subject, body_html=tmpl.body_html)
            # super, иначе write() тут же погонит те же значения обратно
            super(PriceMailing, rec).write(vals)

    def _push_to_system(self):
        """Разложить изменения туда, где значения живут на самом деле."""
        icp, cron, tmpl = self._icp(), self._cron(), self._template()
        for rec in self:
            icp.set_param(PARAM_ENABLED, "1" if rec.enabled else "0")
            icp.set_param(PARAM_MAX, str(max(1, rec.max_per_run or 1)))
            if cron:
                cron.sudo().write({"nextcall": self._next_occurrence(
                    int(rec.weekday or 0), rec.hour or 0, rec.minute or 0)})
            if tmpl and (rec.subject or rec.body_html):
                tmpl.sudo().write({"subject": rec.subject, "body_html": rec.body_html})
            _logger.info("Рассылка прайсов: %s, %s в %02d:%02d, потолок %s — правил %s",
                         "ВКЛЮЧЕНА" if rec.enabled else "выключена",
                         dict(WEEKDAYS).get(rec.weekday, "?"), rec.hour or 0,
                         rec.minute or 0, rec.max_per_run, self.env.user.login)

    def write(self, vals):
        res = super().write(vals)
        # Раскладываем только когда меняли настройки, а не служебные поля
        # вроде адреса для пробного письма. «Время» (send_time) здесь не
        # нужно: его запись — это запись часа и минуты (_inverse_send_time),
        # и раскладка срабатывает на ней.
        if {"enabled", "max_per_run", "weekday", "hour", "minute",
            "subject", "body_html"} & set(vals):
            self._push_to_system()
        return res

    @api.depends("hour", "minute")
    def _compute_send_time(self):
        for rec in self:
            rec.send_time = (rec.hour or 0) + (rec.minute or 0) / 60.0

    def _inverse_send_time(self):
        """09:10 → час 9, минута 10. Округляем до минуты: виджет хранит
        время дробью часа (9,1666…), и без округления 09:10 могло бы стать
        09:09. Вне суток — понятная ошибка, а не ValueError из
        datetime(…, hour=25) при раскладке в задание (_next_occurrence)."""
        for rec in self:
            total = round((rec.send_time or 0.0) * 60)
            if not 0 <= total <= 23 * 60 + 59:
                raise UserError(_("Время — от 00:00 до 23:59."))
            rec.write({"hour": total // 60, "minute": total % 60})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._pull_from_system()
        return records

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

    def _compute_runtime(self):
        """Что происходит прямо сейчас — считается, не хранится."""
        P = self.env["res.partner"]
        cron = self._cron()
        tz = pytz.timezone(TZ)
        # Получатель — как у крона: в реестре И в рассылке. Флажок «В
        # рассылке» у снятого с реестра поставщика письма не даёт.
        recipients = P.search_count([("pmk_price_supplier", "=", True),
                                     ("pmk_price_mailing", "=", True)])
        suppliers = P.search_count([("pmk_price_supplier", "=", True)])
        queued = self.env["mail.mail"].sudo().search_count([("state", "=", "outgoing")])
        ready = bool(self.env["ir.mail_server"].sudo().search_count([]))
        for rec in self:
            rec.recipient_count = recipients
            rec.supplier_count = suppliers
            rec.queue_count = queued
            rec.server_ready = ready
            if cron and cron.nextcall:
                local = pytz.UTC.localize(cron.nextcall).astimezone(tz)
                rec.next_run = local.strftime("%d.%m.%Y в %H:%M") + " (Владивосток)"
                rec.last_run = cron.lastcall
            else:
                rec.next_run, rec.last_run = _("расписание не заведено"), False

    # ------------------------------------------------------------------
    # кнопки
    # ------------------------------------------------------------------
    # Окна получателей — список «Закупки → Поставщики» (тот же вид и поиск),
    # но (доводка шага 38, 05.10.2026):
    #   • только реестр прайсов. С шага 38 «Поставщики» показывают и
    #     поставщиков по штатному признаку (домен действия,
    #     views/res_partner_views.xml), а рассылка пишет только реестру —
    #     отмечать там некого;
    #   • заголовок — и в display_name. Клиент берёт его раньше name
    #     (action_service.js: action.display_name || action.name), а
    #     _for_xml_id отдаёт display_name записи: окно называлось бы
    #     «Поставщики», как пункт меню.
    # После F5 окно грузится по номеру действия (так было и до шага) — это
    # уже «Поставщики» со своими доменом и заголовком.
    def _pmk_recipients_action(self, title, context):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pmk_purchase.action_price_supplier")
        action.update({
            "name": title,
            "display_name": title,
            "domain": list(REGISTRY_DOMAIN),
            "context": context,
        })
        return action

    def action_choose_recipients(self):
        """Весь реестр прайсов — чтобы было кого отмечать."""
        self.ensure_one()
        # Группировку снимаем: отмечать галочками удобнее в плоском списке,
        # а по группам поставщик с несколькими группами встречается несколько раз.
        return self._pmk_recipients_action(
            _("Выберите получателей рассылки"),
            {"default_pmk_price_supplier": True, "default_is_company": True})

    def action_open_recipients(self):
        """Только те, кто уже в рассылке."""
        self.ensure_one()
        return self._pmk_recipients_action(
            _("Получатели рассылки"),
            {"default_pmk_price_supplier": True, "default_is_company": True,
             "search_default_in_mailing": 1})

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
