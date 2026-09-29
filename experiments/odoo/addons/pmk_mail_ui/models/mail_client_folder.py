# -*- coding: utf-8 -*-
"""Папки почты по-русски и в разумном порядке.

Разбор UX, шаг 12 (ML-03; Антон, 28.09.2026: «можем переименовать папки в
русский язык?»). Ящик mail.ru отдаёт часть папок по-английски — INBOX,
Archive, News, Newsletters, Receipts, Social; ящик zakaz@ — INBOX, Drafts,
Sent, Junk, Trash. Весь интерфейс русский, а папки нет.

ТОЛЬКО ОТОБРАЖЕНИЕ. На сервере почты ничего не переименовывается: модуль
mail_client берёт название папки из её пути при КАЖДОЙ синхронизации
(_folder_display_name), поэтому переименовать руками бесполезно — следующий
проход вернёт английское. Меняем саму функцию; синхронизация по-прежнему
идёт по пути на сервере (imap_path).

ПОРЯДОК. Рассылки, чеки, новости и соцсети в продажах не читают — они
уходят в конец дерева, после папок завода. Прятать их нельзя: mail.ru может
ошибочно положить туда письмо клиента. И не через active — грабли 27.09:
неактивную папку синхронизация создаёт заново, и падает на дубле пути.

ТИХИЕ И ОДНОЙ СТРОКОЙ (шаг 18, 30.09.2026). Те же папки — «тихие» (крючок
модуля почты _is_quiet): счётчик серым, не в итоге свёрнутого ящика, в
«ждёт ответа» не участвуют. Во «Входящих» каждая непустая видна одной
строкой (крючок _list_digests), щелчок открывает папку.
"""

from odoo import api, fields, models
from odoo.tools.mail import email_split_tuples

# Имя папки на сервере (последний сегмент пути, без регистра) → по-русски.
FOLDER_NAMES_RU = {
    "inbox": "Входящие",
    "sent": "Отправленные", "sent items": "Отправленные", "sent messages": "Отправленные",
    "drafts": "Черновики", "draft": "Черновики",
    "trash": "Корзина", "deleted items": "Корзина", "deleted messages": "Корзина",
    "junk": "Спам", "spam": "Спам", "bulk mail": "Спам",
    "archive": "Архив", "archives": "Архив",
    "outbox": "Исходящие",
    "news": "Новости",
    "newsletters": "Рассылки",
    "receipts": "Чеки",
    "social": "Соцсети",
}

# Папки-сортировщики mail.ru — в конец дерева.
LOW_PRIORITY_LEAVES = {"news", "newsletters", "receipts", "social"}
LOW_PRIORITY_RANK = 8   # после прочих папок (6), до неизвестных ролей (9)

# Строка рассылок во «Входящих»: сколько имён отправителей показать и среди
# скольких последних писем их искать.
DIGEST_SENDERS = 3
DIGEST_SCAN = 20

# Русские имена служебных папок, которые сервер не помечает флагом роли:
# у mail.ru «Спам» приходит как обычная папка и стоял среди рабочих.
RU_NAME_ROLES = {"спам": "spam"}


def _leaf(path, delimiter):
    if delimiter and delimiter in path:
        return path.rsplit(delimiter, 1)[1]
    return path


class MailClientAccount(models.Model):
    _inherit = "mail.client.account"

    def _folder_display_name(self, path, delimiter):
        name = super()._folder_display_name(path, delimiter)
        return FOLDER_NAMES_RU.get(name.strip().lower(), name)

    def _detect_folder_role(self, path, flags):
        role = super()._detect_folder_role(path, flags)
        if role == "other":
            leaf = path.rsplit("/", 1)[-1].rsplit(".", 1)[-1].strip().lower()
            role = RU_NAME_ROLES.get(leaf, role)
        return role


class MailClientFolder(models.Model):
    _inherit = "mail.client.folder"

    def _pmk_is_sorter(self):
        """Папка-сортировщик mail.ru: Рассылки, Чеки, Новости, Соцсети."""
        self.ensure_one()
        return (self.role == "other"
                and _leaf(self.imap_path or "", self.delimiter).strip().lower()
                in LOW_PRIORITY_LEAVES)

    def _role_rank(self):
        rank = super()._role_rank()
        if self._pmk_is_sorter():
            return LOW_PRIORITY_RANK
        return rank

    def _is_quiet(self):
        """Сортировщики mail.ru — тихие, как Спам (шаг 18, 30.09.2026).

        Счётчик серым и не в итоге свёрнутого ящика (иначе у pmkpark@ в
        итоге сидели бы 46 непрочитанных рассылок и 22 чека), а письмо из
        такой папки не делает переписку «ждёт ответа»."""
        return super()._is_quiet() or self._pmk_is_sorter()

    # ------------------------------------------------------------------
    # рассылки одной строкой (шаг 18, 30.09.2026)
    # ------------------------------------------------------------------
    @api.model
    def _list_digests(self, inboxes):
        """Строка на каждую непустую папку-сортировщик ящиков этих «Входящих».

        mail.ru сам раскладывает рассылки и чеки по своим папкам; во
        «Входящих» они видны одной строкой «Рассылки · новых: 46», щелчок
        открывает папку. Заголовок List-Unsubscribe модуль почты не хранит —
        признак рассылки только папка (решение владельца 30.09.2026).

        Запросы: один на число и дату последнего письма, один на
        непрочитанные, и по одному на отправителей каждой папки (папок не
        больше четырёх на ящик, письма берутся по индексу папки и даты).
        """
        digests = super()._list_digests(inboxes)
        sorters = self.search([
            ("account_id", "in", inboxes.account_id.ids),
            ("subscribed", "=", True),
            ("role", "=", "other"),
        ]).filtered(lambda f: f._pmk_is_sorter())
        if not sorters:
            return digests
        Message = self.env["mail.client.message"]
        groups = Message._read_group(
            [("folder_id", "in", sorters.ids)], ["folder_id"], ["__count", "date:max"])
        unread = self._unread_by_folder(sorters.ids)
        for folder, total, last in groups:
            if not total:
                continue
            digests.append({
                "folder_id": folder.id,
                "name": folder.name,
                "account_id": folder.account_id.id,
                "unread": unread.get(folder.id, 0),
                "total": total,
                "date": last and fields.Datetime.to_string(last),
                "senders": self._pmk_digest_senders(folder),
            })
        digests.sort(key=lambda d: d["date"] or "", reverse=True)
        return digests

    @api.model
    def _pmk_digest_senders(self, folder, count=DIGEST_SENDERS):
        """До трёх разных отправителей последних писем папки — именем, а без
        имени адресом."""
        names = []
        rows = self.env["mail.client.message"].search_fetch(
            [("folder_id", "=", folder.id)], ["email_from"],
            order="date desc, id desc", limit=DIGEST_SCAN)
        for row in rows:
            pairs = email_split_tuples(row.email_from or "")
            if not pairs:
                continue
            name, address = pairs[0]
            label = (name or address or "").strip()
            if label and label not in names:
                names.append(label)
            if len(names) >= count:
                break
        return names
