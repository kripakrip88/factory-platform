# -*- coding: utf-8 -*-
"""Кнопки VPN в боте @Dv_laba_bot.

«🔐 VPN» — сотруднику: прислать свой ключ ещё раз.
«🔐 VPN: сотрудники» — администратору: кто подключён, трафик, отключить.
"""
from datetime import timedelta

import pytz

from odoo import fields, models
from odoo.addons.pmk_telegram.models.bot import _esc

from .vpn_key import TZ

BTN_VPN = "🔐 VPN"
BTN_VPN_ADMIN = "🔐 VPN: сотрудники"
ONLINE_MINUTES = 3   # «в сети» — синхронизация видела человека за последние 3 минуты


class PmkTelegramBot(models.AbstractModel):
    _inherit = "pmk.telegram.bot"

    def _pmk_menu(self, user):
        items = super()._pmk_menu(user)
        Key = self.env["pmk.vpn.key"]
        key = Key.pmk_key_of(user)
        if (key and key._pmk_works()) or (not key and Key._pmk_auto()
                                          and Key._pmk_user_eligible(user)):
            items.append((BTN_VPN, "_pmk_menu_vpn"))
        if user.has_group("base.group_system"):
            items.append((BTN_VPN_ADMIN, "_pmk_menu_vpn_admin"))
        return items

    def _pmk_menu_vpn(self, api_, session):
        Key = self.env["pmk.vpn.key"]
        key = Key.pmk_key_of(session.user_id, create=Key._pmk_auto())
        if not key or not key._pmk_works():
            api_.send(session.chat_id, "Доступ к VPN выключен. Если он нужен — "
                                       "скажите администратору.")
            return
        ok, _down = key.pmk_send(api_)
        if ok:
            key.write({"state": "sent", "sent_at": fields.Datetime.now()})
        else:
            api_.send(session.chat_id, "VPN ещё настраивается — попробуйте позже.")

    def _pmk_menu_vpn_admin(self, api_, session):
        if not session.user_id.has_group("base.group_system"):
            return
        text, markup = self._pmk_vpn_admin_view()
        api_.send(session.chat_id, text, markup)

    def _pmk_vpn_admin_view(self):
        keys = self.env["pmk.vpn.key"].sudo().search([])
        if not keys:
            return ("Ключей VPN пока нет. Разослать: Odoo → Настройки → VPN-ключи → "
                    "«Разослать ключи».", None)
        tz = pytz.timezone(TZ)
        fresh = fields.Datetime.now() - timedelta(minutes=ONLINE_MINUTES)
        lines, rows = ["<b>VPN: сотрудники</b> (сегодня / месяц)", ""], []
        for key in keys:
            if not key.access:
                mark = "⛔"
            elif key.last_seen and key.last_seen >= fresh:
                mark = "🟢"
            else:
                mark = "⚪️"
            seen = (pytz.utc.localize(key.last_seen).astimezone(tz).strftime("%d.%m %H:%M")
                    if key.last_seen else "не подключался")
            extra = ""
            if key.devices_now:
                extra += ", устройств: %d" % key.devices_now
            if key.blocked_ips:
                extra += ", ⚠️ лишние отключены"
            if key.state != "sent":
                extra += ", ключ: %s" % dict(key._fields["state"].selection)[key.state].lower()
            lines.append("%s %s — %s / %s, был: %s%s" % (
                mark, _esc(key.user_id.name), key.traffic_today, key.traffic_month,
                seen, extra))
            rows.append([{"text": ("✅ Включить %s" if not key.access else "⛔ Отключить %s")
                          % key.user_id.name[:30],
                          "callback_data": "vpn:%s:%d" % ("on" if not key.access else "off",
                                                          key.id)}])
        lines += ["", "🟢 в сети · ⚪️ не в сети · ⛔ отключён"]
        return "\n".join(lines), {"inline_keyboard": rows}

    def _pmk_on_callback(self, api_, cq):
        data = cq.get("data") or ""
        if not data.startswith("vpn:"):
            return super()._pmk_on_callback(api_, cq)
        user = self._pmk_user(cq.get("from") or {})
        if not user or not user.has_group("base.group_system"):
            api_.answer_callback(cq["id"], "Нет доступа")
            return
        _p, action, key_id = (data.split(":") + ["", ""])[:3]
        key = self.env["pmk.vpn.key"].sudo().browse(
            int(key_id) if key_id.isdigit() else 0).exists()
        if not key:
            api_.answer_callback(cq["id"], "Ключ не найден")
            return
        name = key.user_id.name
        if action == "off":
            key.access = False
            note = "%s: VPN отключён — перестанет работать в течение минуты." % name
        elif action == "on":
            key.access = True
            note = "%s: VPN включён." % name
        elif action == "new":
            key.action_pmk_new_key()
            key.access = True
            note = ("%s: выдан новый ключ — уйдёт ему в Телеграм в течение 5 минут, "
                    "старый перестанет работать." % name)
        else:
            api_.answer_callback(cq["id"])
            return
        api_.answer_callback(cq["id"], note[:190])
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        # Список сотрудников — обновить на месте; тревога — дописать итог.
        if msg.get("text", "").startswith("VPN: сотрудники") and chat_id:
            text, markup = self._pmk_vpn_admin_view()
            api_.edit(chat_id, msg["message_id"], text, markup)
        elif chat_id:
            api_.edit(chat_id, msg["message_id"], _esc(msg.get("text") or "") + "\n\n✅ " + _esc(note))
