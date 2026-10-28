# -*- coding: utf-8 -*-
"""Личный ключ VPN сотрудника: выдача, рассылка, приём данных с VPN-сервера.

Одна строка на человека. Частые записи (трафик, «был в сети») идут сюда и в
pmk.vpn.traffic, а не в res.users: запись в пользователя каждую минуту
сбрасывала бы кэши Odoo.
"""
import json
import logging
import uuid as uuid_lib
from datetime import datetime

import pytz

from odoo import api, fields, models, modules

from . import links

_logger = logging.getLogger(__name__)

PARAM_SERVER = "pmk_vpn.server"        # JSON с параметрами сервера — пишет синхронизация
PARAM_AUTO = "pmk_vpn.auto"            # «1» — ключи выдаются всем с Телеграмом (кнопка «Разослать»)
PARAM_LIMIT = "pmk_vpn.device_limit"   # устройств на ключ, по умолчанию 3
PARAM_TOKEN = "pmk_vpn.sync_token"     # секрет VPN-сервера; не в репозитории
TZ = "Asia/Vladivostok"                # «сегодня» для трафика — по Хабаровску
DEFAULT_LIMIT = 3
SEND_BATCH = 10                        # ключей за один проход крона
MAX_ATTEMPTS = 3                       # Телеграм отказал три раза — «не доставлен»
KEY_NAME = "ПМК VPN"

INSTRUCTION = (
    "<b>Как подключить VPN</b>\n\n"
    "📱 <b>iPhone</b> — приложение <b>V2Box</b> из App Store.\n"
    "🤖 <b>Android</b> — приложение <b>v2rayNG</b> из Google Play.\n"
    "💻 <b>Компьютер</b> — приложение <b>Hiddify</b>.\n\n"
    "В приложении нажмите «+» и отсканируйте QR-код с другого экрана. "
    "Если открываете с этого же телефона — нажмите на ссылку под QR-кодом "
    "(она скопируется) и выберите «Импорт из буфера».\n\n"
    "Сначала включайте <b>основной</b> ключ. Не подключается — <b>запасной</b>.\n\n"
    "🔒 Ключ личный: работает не больше чем на %(limit)d устройствах "
    "одновременно, лишние отключаются. Не пересылайте его — он записан на вас.\n"
    "Потеряли ключ — кнопка «🔐 VPN» в меню бота."
)


def _today():
    return datetime.now(pytz.timezone(TZ)).date()


class PmkVpnKey(models.Model):
    _name = "pmk.vpn.key"
    _description = "Ключ VPN сотрудника"
    _order = "user_id"
    _rec_name = "user_id"

    user_id = fields.Many2one("res.users", "Сотрудник", required=True,
                              ondelete="cascade", index=True)
    uuid = fields.Char("Ключ", required=True, copy=False,
                       default=lambda _self: str(uuid_lib.uuid4()), groups="base.group_system")
    access = fields.Boolean(
        "Доступ", default=True,
        help="Снять — ключ перестаёт работать в течение минуты. Пользователь в "
             "архиве или без Telegram ID отключается сам.")
    state = fields.Selection([
        ("pending", "Ждёт отправки"),
        ("sent", "Отправлен"),
        ("failed", "Не доставлен"),
    ], "Отправка", default="pending", required=True)
    sent_at = fields.Datetime("Отправлен", readonly=True)
    attempts = fields.Integer(readonly=True)
    last_seen = fields.Datetime("Был в сети", readonly=True)
    devices_now = fields.Integer("Устройств сейчас", readonly=True)
    blocked_ips = fields.Char("Отключены лишние", readonly=True,
                              help="Адреса сверх лимита устройств, которые VPN-сервер сейчас не пускает.")
    alert_day = fields.Date(readonly=True)
    traffic_today = fields.Char("Сегодня", compute="_compute_traffic")
    traffic_month = fields.Char("За месяц", compute="_compute_traffic")

    _user_uniq = models.Constraint("UNIQUE(user_id)", "У сотрудника уже есть ключ.")

    # ── вычисляемое ───────────────────────────────────────────────────────

    def _compute_traffic(self):
        today = _today()
        rows = self.env["pmk.vpn.traffic"].sudo().search_read(
            [("key_id", "in", self.ids), ("day", ">=", today.replace(day=1))],
            ["key_id", "day", "bytes_up", "bytes_down"])
        day, month = {}, {}
        for r in rows:
            kid = r["key_id"][0]
            total = r["bytes_up"] + r["bytes_down"]
            month[kid] = month.get(kid, 0) + total
            if r["day"] == today:
                day[kid] = day.get(kid, 0) + total
        for key in self:
            key.traffic_today = links.human_bytes(day.get(key.id, 0))
            key.traffic_month = links.human_bytes(month.get(key.id, 0))

    # ── кому положен ключ ─────────────────────────────────────────────────

    @api.model
    def _pmk_eligible_users(self):
        """Сотрудники с привязанным Телеграмом (порталу и архиву — нет)."""
        return self.env["res.users"].sudo().search(
            [("share", "=", False), ("pmk_telegram_id", "!=", False)])

    @api.model
    def _pmk_user_eligible(self, user):
        user = user.sudo()
        return bool(user.active and not user.share and user.pmk_telegram_id)

    def _pmk_works(self):
        """Ключи, которые VPN-сервер должен пускать."""
        return self.filtered(lambda k: k.access and self._pmk_user_eligible(k.user_id))

    @api.model
    def _pmk_auto(self):
        return self.env["ir.config_parameter"].sudo().get_param(PARAM_AUTO) == "1"

    @api.model
    def _pmk_limit(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_LIMIT)
        return int(raw) if raw and raw.isdigit() else DEFAULT_LIMIT

    @api.model
    def _pmk_server(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_SERVER)
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    @api.model
    def pmk_key_of(self, user, create=False):
        """Ключ человека; create — выдать, если ещё нет (только тем, кому положен)."""
        key = self.sudo().search([("user_id", "=", user.id)], limit=1)
        if not key and create and self._pmk_user_eligible(user):
            key = self.sudo().create({"user_id": user.id})
        return key

    # ── кнопки в Odoo ─────────────────────────────────────────────────────

    @api.model
    def action_pmk_issue_all(self):
        """«Разослать ключи»: ключ каждому с Телеграмом, кто ещё не получал.

        Заодно включает выдачу новым: привязали человеку Телеграм — ключ
        уйдёт ему сам при следующем проходе крона.
        """
        self.env["ir.config_parameter"].sudo().set_param(PARAM_AUTO, "1")
        created = self._pmk_create_missing()
        unsent = self.sudo().search([("state", "!=", "sent"), ("access", "=", True)])
        unsent.write({"state": "pending", "attempts": 0})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "sticky": False,
            "message": "Ключи уйдут в Телеграм в течение 5 минут: %d человек%s." % (
                len(unsent), " (новых ключей: %d)" % len(created) if created else ""),
            "next": {"type": "ir.actions.client", "tag": "soft_reload"},
        }}

    def action_pmk_resend(self):
        self.write({"state": "pending", "attempts": 0})

    def action_pmk_new_key(self):
        """Новый ключ вместо старого (старый раздали или потеряли телефон).
        Старый перестаёт работать в течение минуты, новый уходит в Телеграм."""
        for key in self:
            key.write({"uuid": str(uuid_lib.uuid4()), "state": "pending", "attempts": 0,
                       "blocked_ips": False})

    # ── рассылка ──────────────────────────────────────────────────────────

    @api.model
    def _pmk_create_missing(self):
        have = self.sudo().search([]).user_id
        todo = self._pmk_eligible_users() - have
        return self.sudo().create([{"user_id": u.id} for u in todo])

    @api.model
    def _cron_pmk_send(self):
        """Раз в 5 минут: выдать ключи новым (если рассылка включена) и
        отправить те, что ждут. Пачкой по SEND_BATCH — крон не занимает поток
        надолго."""
        if self._pmk_auto():
            self._pmk_create_missing()
        if not links.server_ready(self._pmk_server()):
            return  # VPN-сервер ещё ни разу не приходил — ссылку не из чего собрать
        keys = self.sudo().search([("state", "=", "pending"), ("access", "=", True)],
                                  limit=SEND_BATCH)
        for key in keys._pmk_works():
            ok, network_down = key.pmk_send()
            if ok:
                key.write({"state": "sent", "sent_at": fields.Datetime.now()})
            elif network_down:
                break  # нет связи с Телеграмом — остальным тоже не уйдёт
            else:
                key.attempts += 1
                if key.attempts >= MAX_ATTEMPTS:
                    key.state = "failed"
            # Отправленное фиксируем сразу: сбой на следующем человеке не
            # должен откатить отметку и повторить рассылку тому, кто уже получил.
            if not modules.module.current_test:   # в Odoo 19 нет registry.in_test_mode()
                self.env.cr.commit()

    def _pmk_links(self):
        self.ensure_one()
        server = self._pmk_server()
        return (links.vless_main(self.uuid, server, KEY_NAME),
                links.vless_reserve(self.uuid, server, KEY_NAME + " запасной"))

    def _pmk_qr(self, link):
        return self.env["ir.actions.report"].barcode(
            "QR", link, width=600, height=600, barBorder=4)

    def pmk_send(self, api_=None):
        """QR-коды и инструкция человеку в личку. → (дошло, нет_связи).

        Ответ — сразу: всё собирается в Odoo, на VPN-сервер не ходим.
        """
        self.ensure_one()
        bot = self.env["pmk.telegram.bot"].sudo()
        api_ = api_ or bot._pmk_api()
        chat = self.user_id.pmk_telegram_id
        if not api_ or not chat or not links.server_ready(self._pmk_server()):
            return False, False
        main, reserve = self._pmk_links()
        parts = [("Основной ключ", main)]
        if reserve:
            parts.append(("Запасной ключ", reserve))
        for title, link in parts:
            res = api_.send_photo(chat, ("vpn.png", self._pmk_qr(link)),
                                  "🔐 <b>%s</b>\n<code>%s</code>" % (title, link))
            if not res:
                return False, getattr(api_, "network_down", False)
        res = api_.send(chat, INSTRUCTION % {"limit": self._pmk_limit()},
                        bot._pmk_menu_markup(self.user_id))
        return bool(res), getattr(api_, "network_down", False)

    # ── синхронизация с VPN-сервером ──────────────────────────────────────

    @api.model
    def pmk_sync(self, payload):
        """Приём с VPN-сервера (раз в минуту) → список ключей, которые пускать.

        payload = {"server": {host, sni, pbk, sid, port_tcp, port_xhttp, xhttp_path},
                   "stats": {"u12": {"up": байты, "down": байты, "ips": [...]}},
                   "blocked": {"u12": ["адрес", ...]}}
        Трафик приходит приростом с прошлого раза.
        """
        icp = self.env["ir.config_parameter"].sudo()
        server = payload.get("server") or {}
        if links.server_ready(server):
            text = json.dumps(server, sort_keys=True)
            # Писать параметр только при изменении: запись сбрасывает кэш.
            if icp.get_param(PARAM_SERVER) != text:
                icp.set_param(PARAM_SERVER, text)

        Keys = self.sudo()
        all_keys = Keys.search([])
        by_email = {links.email_of(k.user_id.id): k for k in all_keys}
        stats = payload.get("stats") or {}
        blocked = payload.get("blocked") or {}
        now = fields.Datetime.now()
        today = _today()

        for email, key in by_email.items():
            st = stats.get(email) or {}
            ips = st.get("ips") or []
            vals = {}
            if ips:
                vals["last_seen"] = now
            if key.devices_now != len(ips):
                vals["devices_now"] = len(ips)
            bl = ", ".join(blocked.get(email) or []) or False
            if (key.blocked_ips or False) != bl:
                vals["blocked_ips"] = bl
            if vals:
                key.write(vals)
            up, down = int(st.get("up") or 0), int(st.get("down") or 0)
            if up or down:
                self.env["pmk.vpn.traffic"].sudo().pmk_add(key, today, up, down)
            if bl and key.alert_day != today and key._pmk_works():
                key.alert_day = today
                key._pmk_alert_over_limit(len(ips))

        works = all_keys._pmk_works()
        return {"users": [{"email": links.email_of(k.user_id.id), "uuid": k.uuid}
                          for k in works],
                "limit": self._pmk_limit()}

    def _pmk_alert_over_limit(self, devices):
        """Тревога администраторам: ключ работает на большем числе устройств,
        чем можно, — похоже, его раздали. Раз в сутки на человека."""
        self.ensure_one()
        text = ("⚠️ <b>VPN</b>: ключ «%s» сейчас на %d устройствах при лимите %d — "
                "лишние отключены. Если ключ раздали, выдайте новый: старый "
                "перестанет работать." % (self.user_id.name, devices, self._pmk_limit()))
        markup = {"inline_keyboard": [[
            {"text": "🔄 Новый ключ", "callback_data": "vpn:new:%d" % self.id},
            {"text": "⛔ Отключить", "callback_data": "vpn:off:%d" % self.id},
        ]]}
        bot = self.env["pmk.telegram.bot"].sudo()
        for admin in self._pmk_admins():
            bot.pmk_send_user(admin, text, markup)

    @api.model
    def _pmk_admins(self):
        users = self.env["res.users"].sudo().search(
            [("share", "=", False), ("pmk_telegram_id", "!=", False)])
        return users.filtered(lambda u: u.has_group("base.group_system"))
