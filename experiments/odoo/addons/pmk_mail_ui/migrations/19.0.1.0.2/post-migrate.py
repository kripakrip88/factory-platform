# -*- coding: utf-8 -*-
"""Применить новые правила почты к уже загруженному (разбор UX, шаг 12).

• Названия и роли папок: иначе русские имена появились бы только на
  следующем проходе синхронизации (крон раз в 10 минут).
• Превью писем, собранные прежним правилом с текстом стилей: пересчитываем
  по сохранённому телу письма. Тело хранится очищенным, <style> в нём уже
  нет, так что новое превью — начало видимого текста.
"""
from odoo import api
from odoo.orm.utils import SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for folder in env["mail.client.folder"].with_context(active_test=False).search([]):
        account = folder.account_id
        name = account._folder_display_name(folder.imap_path, folder.delimiter)
        role = account._detect_folder_role(folder.imap_path, [])
        values = {}
        if name != folder.name:
            values["name"] = name
        # Роль по флагам сервера здесь неизвестна — трогаем только «прочие»,
        # которым русское имя дало роль (Спам).
        if folder.role == "other" and role != "other":
            values["role"] = role
        if values:
            folder.write(values)

    Message = env["mail.client.message"]
    bad = Message.search([
        "|", ("preview", "=like", ".%"), ("preview", "=like", "%{%"),
    ])
    for message in bad:
        if message.body_html:
            message.preview = Message._build_preview(str(message.body_html))
