# -*- coding: utf-8 -*-
"""Мелочи после приёмки 22–34 — разбор UX, шаг 53 (07.10.2026), почта.

ПАПКА ПИСЬМА (pmk_folder_of). Щелчок по «Письму» на вкладке «Связи»
(pmk_flow) открывает почту на этом письме: браузеру нужна папка письма,
чтобы открыть её первой (static/src/js/step53_open.js). Только тому, кто
может читать письмо (правила доступа модуля почты), и только папку из
дерева его почты (_pmk_tree_folder_id): ящик его или общий с ним, папка
подписана и не в архиве — ровно те, что отдаёт get_inbox_state. Письмо в
неподписанной папке (перенесли на mail.ru в папку, которой в Odoo нет в
дереве) почта открыть не может: список показал бы «Входящие», а письмо —
нет. Тогда False, и вкладка «Связи» ведёт по-старому в лид (pmk_flow,
_letter_action).

СЧЁТЧИК У КАЖДОГО ПУНКТА «ПОЧТА» (pmk_mail_unread_counts). С шага 53 у
«Продажи → Почта» и «Закупки → Почта» разные ящики (params.pmk_mailbox,
data/menus.xml). Число на пункте — непрочитанные во «Входящих» того ящика,
который пункт открывает: на «Продажах» — заявки, на «Закупках» — закупки.
Прайс или спам на zakaz@ больше не поднимает число у Продаж. Ящика с таким
адресом у человека нет — считается ящик, который почта откроет вместо него
(первый по порядку с папками), как и выбирает браузер. Вкладка браузера
«(3) …» — по-прежнему все «Входящие» человека (pmk_mail_unread_count).

АДРЕС info@ → ЛИДЫ ВЫКЛЮЧЕН (pmk_switch_off_lead_aliases). Решение Антона
07.10.2026 («да» на вопрос приёмки шага 27: «на адрес info@ ещё настроен
приём писем в лиды… Выключить так же?»). Приёмник (mail.alias) «info» у
команды «Продажи» завёл бы лид из любого письма на info@pmkpark.ru, если
оно дойдёт до входящего сервера Odoo, — мимо кнопки «Лид» и её правил
разбора темы и адреса (models/mail_client_message.py). Так же, как zakaz@
28.09 (миграция 19.0.1.0.1): у приёмника снимается имя — без имени он не
совпадает ни с одним адресом. Запись остаётся; вернуть — вписать имя
«info» обратно (Настройки → Технический → Псевдонимы или карточка команды
продаж). Само не вернётся: имя «info» ставит crm/data/crm_team_data.xml с
noupdate, -u crm его не перепишет, а пересчёт приёмника команды
(crm.team.write, Настройки CRM) имя не трогает.

ORM, а не SQL: маршрут ищет приёмник по alias_full_name — хранимому
вычисляемому полю; правка одного alias_name через SQL оставила бы адрес.
Ящики счетов sales@ / purchases@ (account.move) не трогаются: условие —
модель crm.lead.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, MissingError

from .mail_client_flags import FLAG_WINDOW_DAYS

_logger = logging.getLogger(__name__)

# Имена приёмников «письмо → лид», которые выключены по решению Антона.
LEAD_ALIASES_OFF = ("info",)

# Пункты «Почта» и их действия (data/menus.xml): какой ящик открывает
# пункт — params.pmk_mailbox действия. Тот же xmlid пункта ищет браузер
# (static/src/js/mail_counter_rules.js, MAIL_MENUS).
MAIL_MENUS = {
    "pmk_mail_ui.menu_mail_sale": "pmk_mail_ui.action_mail_sale",
    "pmk_mail_ui.menu_mail_purchase": "pmk_mail_ui.action_mail_purchase",
}


def _norm_email(value):
    """Адрес без пробелов и регистра — как normEmail в step53_open_rules.js."""
    return (value or "").strip().lower()


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    @api.model
    def pmk_folder_of(self, message_id):
        """Папка письма для открытия почты на нём; False — нет письма или прав."""
        try:
            message = self.browse(int(message_id)).exists()
            if not message:
                return False
            message.check_access("read")
            return message._pmk_tree_folder_id()
        except (AccessError, MissingError, TypeError, ValueError):
            return False

    def _pmk_tree_folder_id(self):
        """Папка письма, если она есть в дереве почты человека; иначе False.

        Дерево — get_inbox_state модуля почты: ящики _accessible_accounts
        (его или общие с ним; администратору чужие ящики правило записи
        открывает, а дерево — нет) и в них подписанные папки, не в архиве.
        Права на само письмо проверяет вызывающий.
        """
        self.ensure_one()
        folder = self.sudo().folder_id
        if not (folder and folder.active and folder.subscribed):
            return False
        accounts = self.env["mail.client.account"]._accessible_accounts()
        return folder.id if folder.account_id.id in accounts.ids else False


class MailClientAccount(models.Model):
    _inherit = "mail.client.account"

    @api.model
    def _pmk_unread_in(self, accounts):
        """Непрочитанные во «Входящих» ящиков ``accounts`` за окно отметок —
        то же правило, что у pmk_mail_unread_count (шаг 41)."""
        if not accounts:
            return 0
        inboxes = self.env["mail.client.folder"].search([
            ("account_id", "in", accounts.ids),
            ("role", "=", "inbox"),
            ("subscribed", "=", True),
        ])
        if not inboxes:
            return 0
        since = fields.Datetime.now() - timedelta(days=FLAG_WINDOW_DAYS)
        return self.env["mail.client.message"].search_count([
            ("folder_id", "in", inboxes.ids),
            ("flag_seen", "=", False),
            ("date", ">=", since),
        ])

    @api.model
    def _pmk_menu_accounts(self, accounts, mailbox):
        """Ящик, который откроет пункт «Почта» с адресом ``mailbox``.

        Как браузер (step53_open_rules.js, pickFolder, и firstFolderId почты):
        ящик с этим адресом, а нет его — первый по порядку, где есть папки.
        """
        wanted = _norm_email(mailbox)
        if wanted:
            matched = accounts.filtered(lambda account: _norm_email(account.email) == wanted)
            if matched:
                return matched
        for account in accounts:
            if account.folder_ids.filtered("subscribed"):
                return account
        return accounts.browse()

    @api.model
    def pmk_mail_unread_counts(self):
        """Счётчики новых: ``total`` — все «Входящие» человека (вкладка
        браузера), ``menus`` — {xmlid пункта «Почта»: число его ящика}.
        Без права на почту — нули, без ошибки (как pmk_mail_unread_count)."""
        total = self.pmk_mail_unread_count()
        menus = dict.fromkeys(MAIL_MENUS, 0)
        if not total:
            return {"total": 0, "menus": menus}
        accounts = self._accessible_accounts()
        for menu_xmlid, action_xmlid in MAIL_MENUS.items():
            action = self.env.ref(action_xmlid, raise_if_not_found=False)
            if not action:
                continue
            params = action.sudo().params or {}
            mailbox = params.get("pmk_mailbox") if isinstance(params, dict) else ""
            menus[menu_xmlid] = self._pmk_unread_in(self._pmk_menu_accounts(accounts, mailbox))
        return {"total": total, "menus": menus}


class MailAlias(models.Model):
    _inherit = "mail.alias"

    @api.model
    def _pmk_switch_off_lead_aliases(self, names=LEAD_ALIASES_OFF):
        """Снять имя у приёмников «письмо → лид» из ``names``.

        Возвращает полные адреса выключенных приёмников; повторный вызов —
        пустой список (имени уже нет).
        """
        aliases = self.sudo().search([
            ("alias_name", "in", list(names)),
            ("alias_model_id.model", "=", "crm.lead"),
        ])
        if not aliases:
            return []
        full = aliases.mapped("alias_full_name")
        _logger.info("pmk_mail_ui: приёмник %s (id %s) больше не создаёт лиды — имя снято",
                     full, aliases.ids)
        aliases.write({"alias_name": False})
        return full
