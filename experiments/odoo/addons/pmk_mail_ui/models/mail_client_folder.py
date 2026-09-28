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
"""

from odoo import models

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

    def _role_rank(self):
        rank = super()._role_rank()
        if self.role == "other" and _leaf(self.imap_path or "", self.delimiter).strip().lower() in LOW_PRIORITY_LEAVES:
            return LOW_PRIORITY_RANK
        return rank
