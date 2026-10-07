# -*- coding: utf-8 -*-
"""Почта, остальное — разбор удобства, шаг 41 (05.10.2026).

Пункты плана «Почта как в Mail.ru», шаг 6. Здесь — то, что хранит данные и
связывает почту с системой; вид и поведение — в модуле почты (наша копия,
vendor/README.md, раздел «mail_client — наша копия»).

ИМЕНА ВЛОЖЕНИЙ В СТРОКЕ СПИСКА (В4). Модуль почты при синхронизации уже
читает описание письма (BODYSTRUCTURE): имя, тип и размер каждой части
приходят даром, без скачивания файлов. Но имён он не хранил — строки
вложений заводились только при открытии письма (37 писем из 2 146 с
вложениями). Теперь имена пишутся в pmk_attachment_names при синхронизации
(крючок папки _structure_values), при дочитке старых писем (тот же крючок,
крон «Describe Older Messages») и при открытии (_sync_attachment_records).
Файлы при этом не качаются, отметка «прочитано» на mail.ru не меняется
(EXAMINE и BODYSTRUCTURE — только чтение). Картинки из подписи (часть с
Content-ID, на которую ссылается текст) вложением не считаются — их в
именах нет.

ЛИД У СТРОКИ (А5). Строка списка несёт значок лида: лид самого письма, а
если его нет — самый новый лид его переписки в том же ящике (кнопкой «Лид»
лид заводится из одного письма, а в работе — вся переписка). Только тому,
кто может читать лиды (право на модель и правило записи); архивные —
тоже, с признаком active. Кнопка «Лид» (и клавиша L) у письма переписки,
где лид уже есть, открывает этот лид и привязывает к нему письмо, второго
не заводит (доводка шага 41: ответ клиента — новое письмо без своего лида).

ФИЛЬТР «С ЛИДОМ» (А7). Переписки, где лид есть хотя бы у одного письма
(включая архивные лиды). Имя фильтра — 'pmk_lead'; словарь фильтров модуля
почты закрытый (MESSAGE_FILTERS), поэтому имя пропускает _filter_domain
здесь, а условие дописывает _message_domain.

СЧЁТЧИК НОВЫХ (Г12). Непрочитанные во «Входящих» ящиков, доступных
человеку, за последние FLAG_WINDOW_DAYS (30) дней — то же окно, в котором
отметки «прочитано» общие с mail.ru (models/mail_client_flags.py). Старше
окна отметка с mail.ru не обновляется, и число врало бы: на 05.10 во
«Входящих» pmkpark@ 313 непрочитанных, из них 212 старше 30 дней. Число —
во вкладке браузера (static/src/js/mail_counter.js); на пунктах «Почта» с
шага 53 — число ящика, который пункт открывает (mail_client_step53.py,
pmk_mail_unread_counts). Первое значение приходит со страницей (ir_http.py).
"""
import re
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.fields import Domain

from odoo.addons.mail_client.tools import bodystructure

from .mail_client_flags import FLAG_WINDOW_DAYS

# Имена вложений: сколько хранить у письма, длина имени, сколько показывать
# в строке (дальше — «+N»).
NAMES_KEEP = 20
NAME_MAX = 120
ROW_NAMES = 3

# Строку вложения без имени файла модуль почты называет «part 2» («часть 2»
# в русском переводе, _sync_attachment_records) — это не имя, в строку
# списка его не берём.
_UNNAMED_PART = re.compile(r"^(?:part|часть) [\d.]+$", re.IGNORECASE)

# Быстрый фильтр «С лидом».
LEAD_FILTER = "pmk_lead"

# Где дочитывать имена у старых писем: везде, кроме Спама и Корзины.
BACKFILL_SKIP_ROLES = ("spam", "trash")


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    pmk_attachment_names = fields.Text(
        "Имена вложений", readonly=True, copy=False,
        help="Имена файлов-вложений из описания письма (BODYSTRUCTURE), по одному "
             "в строке. Пишутся при синхронизации; сами файлы не скачиваются.")

    # ------------------------------------------------------------------
    # имена вложений (В4)
    # ------------------------------------------------------------------
    @staticmethod
    def _pmk_names_from_parts(parts):
        """Имена настоящих вложений из разобранного BODYSTRUCTURE — по правилу
        модуля почты (bodystructure.attachments: картинка из текста с
        Content-ID вложением не считается). Без пустых и повторов."""
        names = []
        for part in bodystructure.attachments(parts or []):
            name = " ".join((part.get("filename") or "").split())[:NAME_MAX]
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _pmk_join_names(names):
        return "\n".join(list(names)[:NAMES_KEEP]) or False

    def _pmk_name_list(self):
        self.ensure_one()
        return [name for name in (self.pmk_attachment_names or "").split("\n") if name]

    def _sync_attachment_records(self, parts):
        """Письмо открыли (модуль почты прочитал состав) — имена тоже.
        Нумерацию строк вложений не трогаем: на неё рассчитан
        _pmk_record_inline_parts (vendor/README.md, хрупкие места)."""
        result = super()._sync_attachment_records(parts)
        names = self._pmk_join_names(self._pmk_names_from_parts(parts))
        for message in self:
            if (message.pmk_attachment_names or False) != names:
                message.pmk_attachment_names = names
        return result

    # ------------------------------------------------------------------
    # лид у строки (А5)
    # ------------------------------------------------------------------
    @api.model
    def _pmk_lead_badge(self, lead):
        return {
            "id": lead.id,
            "name": lead.name or "",
            "type": lead.type or "lead",
            "active": bool(lead.active),
        }

    def _pmk_thread_leads(self):
        """{id письма: значок лида} — лид самого письма или самый новый лид
        его переписки в том же ящике. Пусто, если лиды человеку не видны."""
        Lead = self.env["crm.lead"]
        if not self or not Lead.has_access("read"):
            return {}
        keys = sorted({key for key in self.mapped("thread_key") if key})
        linked = self.filtered("pmk_lead_id")
        if keys:
            linked |= self.search([
                ("pmk_lead_id", "!=", False),
                ("thread_key", "in", keys),
                ("account_id", "in", self.account_id.ids),
            ])
        if not linked:
            return {}
        readable = linked.pmk_lead_id.with_context(active_test=False)._filtered_access("read")
        badges = {lead.id: self._pmk_lead_badge(lead) for lead in readable}
        by_thread = {}
        for message in linked.sorted(key=lambda m: (m.date or datetime.min, m.id), reverse=True):
            badge = badges.get(message.pmk_lead_id.id)
            if badge and message.thread_key:
                by_thread.setdefault((message.account_id.id, message.thread_key), badge)
        result = {}
        for message in self:
            badge = badges.get(message.pmk_lead_id.id) or by_thread.get(
                (message.account_id.id, message.thread_key))
            if badge:
                result[message.id] = badge
        return result

    @api.model
    def pmk_lead_badges(self, message_ids):
        """Значки лида для писем — строке списка после кнопки «Лид» в окне
        письма (step41_mail.js): значок встаёт сразу, без перечитывания."""
        messages = self.browse(message_ids or []).exists()
        messages.check_access("read")
        badges = messages._pmk_thread_leads()
        return [{
            "id": message.id,
            "thread_key": message.thread_key or False,
            "lead": badges.get(message.id, False),
        } for message in messages]

    def _pmk_thread_lead(self):
        """Лид переписки этого письма в том же ящике (самый новый, архивный
        тоже), если человеку можно его читать; иначе пусто."""
        self.ensure_one()
        badge = self._pmk_thread_leads().get(self.id)
        return self.env["crm.lead"].browse(badge["id"]) if badge else self.env["crm.lead"]

    def _pmk_find_lead(self):
        """Доводка шага 41: у переписки уже есть лид — кнопка «Лид» (и клавиша
        L, и «Лид» у строки) открывает его, второго не заводит.

        Лид заводят из одного письма, а в работе вся переписка: клиент
        ответил — новое письмо без своего лида, и кнопка завела бы второй лид
        на ту же переписку (9 переписок с лидом на 05.10). Порядок: лид
        самого письма и лид из алиаса (как было), потом лид переписки — его
        action_pmk_create_lead привязывает и к этому письму. Лид, который
        человеку не виден (чужой при правиле «только свои»), не берём — как
        до шага 41."""
        lead = super()._pmk_find_lead()
        return lead or self._pmk_thread_lead()

    def action_pmk_create_lead(self):
        """Кнопка «Лид» — плюс значок для строки списка. from_thread — лид
        не создан, а взят у переписки (подпись уведомления в окне)."""
        self.ensure_one()
        from_thread = not super()._pmk_find_lead() and bool(self._pmk_thread_lead())
        result = super().action_pmk_create_lead()
        badge = self._pmk_thread_leads().get(self.id, False)
        result.update({
            "lead": badge,
            "thread_key": self.thread_key or False,
            "from_thread": bool(from_thread and not result.get("created")),
        })
        return result

    # ------------------------------------------------------------------
    # строка списка: имена и лид
    # ------------------------------------------------------------------
    def _to_list_payload(self):
        rows = super()._to_list_payload()
        leads = self._pmk_thread_leads()
        for message, row in zip(self, rows):
            names = message._pmk_name_list()
            row["attachment_names"] = names[:ROW_NAMES]
            row["attachment_count"] = len(names)
            row["pmk_lead"] = leads.get(message.id, False)
        return rows

    @api.model
    def _decorate_thread_rows(self, payload, members):
        """Строка-переписка: имена вложений со всех её писем, новые первыми,
        без повторов. Лид — уже в _to_list_payload (по всей переписке)."""
        payload = super()._decorate_thread_rows(payload, members)
        names_by_key = {}
        for message in members:  # новые первыми
            names = names_by_key.setdefault(message.thread_key, [])
            for name in message._pmk_name_list():
                if name not in names:
                    names.append(name)
        for row in payload:
            names = names_by_key.get(row.get("thread_key"))
            if names is not None:
                row["attachment_names"] = names[:ROW_NAMES]
                row["attachment_count"] = len(names)
        return payload

    # ------------------------------------------------------------------
    # звезда переписки (А5, значки при наведении)
    # ------------------------------------------------------------------
    @api.model
    def pmk_set_threads_flagged(self, message_ids, value=False, unified=False):
        """Звезда у строки-переписки.

        Строка отмечена, если отмечено ЛЮБОЕ письмо переписки (_threaded_page).
        Поставить — отмечаем письмо строки. Снять — со ВСЕХ отмеченных писем
        переписки (ящики — как у прочитанности, _pmk_thread_scope): сними
        только со строки, звезда переписки осталась бы. Штатным
        set_flagged_bulk — права на запись и очередь отметок (для ящика с
        общими отметками — и на mail.ru). Письма «только смотреть»
        (_filtered_access) пропускаем.
        """
        anchors = self._checked_many(message_ids)
        scope = self._pmk_thread_scope(anchors, unified)
        if value:
            changed = anchors.filtered(lambda m: not m.flag_flagged)
        else:
            changed = anchors.filtered("flag_flagged")
            if scope:
                found = self.search(
                    Domain.OR([self._pmk_thread_domain(key, accounts)
                               for key, accounts in scope.items()])
                    & Domain([("flag_flagged", "=", True)]))
                changed |= found._filtered_access("write")
        if changed:
            self.set_flagged_bulk(changed.ids, value)
        threads = []
        for key, accounts in sorted(scope.items()):
            still = self.search_count(
                self._pmk_thread_domain(key, accounts) & Domain([("flag_flagged", "=", True)]),
                limit=1)
            threads.append({"thread_key": key, "flagged": bool(still)})
        return {"ids": changed.ids, "flag_flagged": bool(value), "threads": threads}

    # ------------------------------------------------------------------
    # фильтр «С лидом» (А7)
    # ------------------------------------------------------------------
    @api.model
    def _pmk_lead_domain(self, account_ids):
        """Письма переписок этих ящиков, где хотя бы у одного письма есть лид."""
        if not account_ids:
            return [("id", "in", [])]
        keys = sorted({key for key in self.search([
            ("account_id", "in", list(account_ids)),
            ("pmk_lead_id", "!=", False),
        ]).mapped("thread_key") if key})
        return ["|", ("pmk_lead_id", "!=", False),
                "&", ("thread_key", "in", keys), ("account_id", "in", list(account_ids))]

    # ------------------------------------------------------------------
    # миграция 19.0.1.0.7: имена у писем, полученных раньше
    # ------------------------------------------------------------------
    @api.model
    def _pmk_names_from_rows(self):
        """Имена из уже заведённых строк вложений (письма, которые
        открывали): без захода на почтовый сервер. Возвращает, скольким
        письмам записаны имена."""
        Attachment = self.env["mail.client.attachment"].sudo()
        rows = Attachment.search([("pmk_inline", "=", False)], order="message_id, sequence, id")
        names = {}
        for row in rows:
            name = " ".join((row.name or "").split())[:NAME_MAX]
            if name and not _UNNAMED_PART.match(name):
                bucket = names.setdefault(row.message_id.id, [])
                if name not in bucket:
                    bucket.append(name)
        done = 0
        for message in self.sudo().browse(list(names)).exists():
            if not message.pmk_attachment_names:
                message.pmk_attachment_names = self._pmk_join_names(names[message.id])
                done += 1
        return done

    @api.model
    def _pmk_queue_name_backfill(self):
        """Письма с вложениями без имён — дочитать их описание (только
        BODYSTRUCTURE, без файлов и без отметки «прочитано»): состав
        «не прочитан», и штатный крон «Describe Older Messages» прочитает его
        заново (200 писем на папку раз в 15 минут) — имена запишет крючок
        _structure_values. Спам и Корзину не трогаем. Возвращает, сколько
        писем поставлено в дочитку."""
        messages = self.sudo().search([
            ("has_attachment", "=", True),
            ("pmk_attachment_names", "=", False),
            ("structure_state", "=", "parsed"),
            ("folder_id.role", "not in", BACKFILL_SKIP_ROLES),
            ("folder_id.subscribed", "=", True),
        ])
        if messages:
            messages.write({"structure_state": "unknown"})
        return len(messages)


class MailClientFolder(models.Model):
    _inherit = "mail.client.folder"

    def _structure_values(self, structures, uid):
        """Синхронизация и дочитка: к описанию письма — имена вложений.
        У модуля почты метод статический; здесь — обычный, вызывают его
        только от папки (self._structure_values)."""
        values = super()._structure_values(structures, uid)
        parts = structures.get(uid)
        if parts is not None:
            Message = self.env["mail.client.message"]
            values["pmk_attachment_names"] = Message._pmk_join_names(
                Message._pmk_names_from_parts(parts))
        return values

    @api.model
    def _filter_domain(self, message_filter):
        if message_filter == LEAD_FILTER:
            return []
        return super()._filter_domain(message_filter)

    @api.model
    def _message_domain(self, folder_id=None, account_ids=None, search=None, before=None,
                        message_filter=None, **kwargs):
        domain = super()._message_domain(
            folder_id=folder_id, account_ids=account_ids, search=search, before=before,
            message_filter=message_filter, **kwargs)
        if message_filter == LEAD_FILTER:
            scope = (self.browse(folder_id).account_id.ids if folder_id
                     else list(account_ids or []))
            domain += self.env["mail.client.message"]._pmk_lead_domain(scope)
        return domain


class MailClientAccount(models.Model):
    _inherit = "mail.client.account"

    @api.model
    def pmk_mail_unread_count(self):
        """Счётчик новых (Г12): непрочитанные во «Входящих» ящиков, доступных
        человеку, за FLAG_WINDOW_DAYS дней. Без права на почту — 0, без
        ошибки: число приходит со страницей (ir_http.session_info)."""
        if not (self.env.user._is_internal()
                and self.has_access("read")
                and self.env["mail.client.message"].has_access("read")):
            return 0
        accounts = self._accessible_accounts()
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
