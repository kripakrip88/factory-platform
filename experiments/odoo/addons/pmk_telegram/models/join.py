# -*- coding: utf-8 -*-
"""Подключение к боту без пересылки ID (задача 317, Антон 28.10.2026: «делаем оба варианта»).

А. Личная ссылка. В Odoo у сотрудника кнопка «Подключить Телеграм» (сам — в «Моих настройках»,
   администратор — в карточке пользователя): t.me/<бот>?start=<разовый код>. Телеграм открывает
   бота с кнопкой «Начать» — нажал, и Телеграм привязан, администратору делать ничего не нужно.
   Код разовый, действует сутки; в базе — только его хеш.
Б. Заявка. Кто нашёл бота сам и нажал «Начать» без ссылки — бот запоминает его (имя, ник, ID) и
   один раз пишет администраторам «X хочет подключиться» с кнопкой в Odoo. Там — «Привязать…»
   (выбрать сотрудника) или «Отклонить». После привязки бот сам пишет человеку «Готово».
"""
import hashlib
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

LINK_TTL = timedelta(days=1)
PARAM_USERNAME = "pmk_telegram.bot_username"
DEFAULT_USERNAME = "Dv_laba_bot"
JOIN_ACTION_XMLID = "pmk_telegram.action_pmk_telegram_join"


def _hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()


def _tg_name(tg_user):
    return " ".join(p for p in (tg_user.get("first_name"), tg_user.get("last_name")) if p).strip()


class PmkTelegramJoin(models.Model):
    _name = "pmk.telegram.join"
    _description = "Хотят подключиться к боту"
    _order = "state_order, last_at desc"
    _rec_name = "name"

    tg_id = fields.Char("Telegram ID", required=True, index=True, readonly=True)
    name = fields.Char("Имя в Телеграме", readonly=True)
    username = fields.Char("Ник", readonly=True)
    first_at = fields.Datetime("Впервые написал", readonly=True)
    last_at = fields.Datetime("Последний раз", readonly=True)
    count = fields.Integer("Сколько раз писал", readonly=True, default=1)
    state = fields.Selection([("new", "Новый"), ("linked", "Привязан"), ("ignored", "Отклонён")],
                             "Статус", default="new", required=True, readonly=True)
    state_order = fields.Integer(compute="_compute_state_order", store=True)
    user_id = fields.Many2one("res.users", "Сотрудник", readonly=True, ondelete="set null")

    _tg_id_uniq = models.Constraint("UNIQUE(tg_id)", "Заявка от этого Телеграма уже есть.")

    @api.depends("state")
    def _compute_state_order(self):
        for rec in self:
            rec.state_order = {"new": 0, "linked": 1, "ignored": 2}.get(rec.state, 3)

    @api.model
    def _pmk_register(self, tg_user):
        """Записать того, кто написал без доступа. → (заявка, надо ли сообщить администраторам)."""
        tg_id = str(tg_user.get("id"))
        now = fields.Datetime.now()
        vals = {"name": _tg_name(tg_user) or False, "username": tg_user.get("username") or False,
                "last_at": now}
        rec = self.sudo().search([("tg_id", "=", tg_id)], limit=1)
        if rec:
            rec.write(dict(vals, count=rec.count + 1))
            return rec, False
        rec = self.sudo().create(dict(vals, tg_id=tg_id, first_at=now))
        return rec, True

    def _pmk_label(self):
        self.ensure_one()
        return " ".join(p for p in (self.name, "(@%s)" % self.username if self.username else "") if p) \
            or self.tg_id

    def action_pmk_link(self):
        """«Привязать…» — окно выбора сотрудника."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "pmk.telegram.join.link", "view_mode": "form",
            "target": "new", "name": _("Привязать Телеграм"), "context": {"default_join_id": self.id},
        }

    def action_pmk_ignore(self):
        self.write({"state": "ignored"})

    def _pmk_done(self, user):
        """Привязано (администратором или по ссылке) — отметить заявку."""
        self.sudo().write({"state": "linked", "user_id": user.id})


class PmkTelegramJoinLink(models.TransientModel):
    _name = "pmk.telegram.join.link"
    _description = "Привязать Телеграм к сотруднику"

    join_id = fields.Many2one("pmk.telegram.join", "Заявка", required=True, ondelete="cascade")
    join_label = fields.Char(related="join_id.name", string="Имя в Телеграме")
    user_id = fields.Many2one(
        "res.users", "Сотрудник", required=True,
        domain="[('share', '=', False), ('pmk_telegram_id', '=', False)]",
        help="Сотрудники без привязанного Телеграма; похожий по имени подставлен сам.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        join = self.env["pmk.telegram.join"].browse(res.get("join_id")).exists()
        if join and "user_id" in fields_list and not res.get("user_id"):
            words = [w.lower() for w in (join.name or "").split() if len(w) > 2]
            if words:
                users = self.env["res.users"].search([("share", "=", False), ("pmk_telegram_id", "=", False)])
                best = max(users, key=lambda u: sum(w in (u.name or "").lower() for w in words), default=None)
                if best and any(w in (best.name or "").lower() for w in words):
                    res["user_id"] = best.id
        return res

    def action_link(self):
        self.ensure_one()
        user, join = self.user_id, self.join_id
        other = self.env["res.users"].sudo().with_context(active_test=False).search(
            [("pmk_telegram_id", "=", join.tg_id)], limit=1)
        if other and other != user:
            raise UserError(_("Этот Телеграм уже привязан к «%s».") % other.name)
        user.sudo().write({"pmk_telegram_id": join.tg_id})
        join._pmk_done(user)
        self.env["pmk.telegram.bot"].sudo()._pmk_welcome(user)
        return {"type": "ir.actions.act_window_close"}


class PmkTelegramLinkShow(models.TransientModel):
    """Личная ссылка на подключение — показать, скопировать, открыть."""
    _name = "pmk.telegram.link.show"
    _description = "Ссылка для подключения Телеграма"

    user_id = fields.Many2one("res.users", "Сотрудник", readonly=True)
    link = fields.Char("Ссылка", readonly=True)
    until = fields.Datetime("Действует до", readonly=True)
    is_self = fields.Boolean(readonly=True)

    def action_open(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.link, "target": "new"}


class ResUsersJoin(models.Model):
    _inherit = "res.users"

    pmk_telegram_link_hash = fields.Char(copy=False, groups="base.group_system")
    pmk_telegram_link_until = fields.Datetime(copy=False, groups="base.group_system")

    def action_pmk_telegram_link(self):
        """Кнопка «Подключить Телеграм»: разовая ссылка t.me/<бот>?start=<код> на сутки.
        Себе — любой сотрудник, другим — только администратор."""
        self.ensure_one()
        if self != self.env.user and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Ссылку для подключения можно получить только себе."))
        token = secrets.token_urlsafe(16)          # 22 знака [A-Za-z0-9_-] — годится для ?start=
        until = fields.Datetime.now() + LINK_TTL
        self.sudo().write({"pmk_telegram_link_hash": _hash(token), "pmk_telegram_link_until": until})
        username = (self.env["ir.config_parameter"].sudo().get_param(PARAM_USERNAME) or DEFAULT_USERNAME).lstrip("@")
        show = self.env["pmk.telegram.link.show"].create({
            "user_id": self.id, "link": "https://t.me/%s?start=%s" % (username, token),
            "until": until, "is_self": self == self.env.user})
        return {"type": "ir.actions.act_window", "res_model": "pmk.telegram.link.show", "res_id": show.id,
                "view_mode": "form", "target": "new", "name": _("Подключить Телеграм")}

    @api.model
    def _pmk_by_link_token(self, token):
        """Сотрудник по коду из ссылки (код не истёк). Пусто — нет такого или истёк."""
        if not token:
            return self.browse()
        user = self.sudo().search([("pmk_telegram_link_hash", "=", _hash(token))], limit=1)
        if user and user.pmk_telegram_link_until and user.pmk_telegram_link_until >= fields.Datetime.now():
            return user
        return self.browse()
