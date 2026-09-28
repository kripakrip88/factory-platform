# -*- coding: utf-8 -*-
"""Создание лида CRM из письма.

Главное требование к этому коду — лид из кнопки не должен отличаться от лида,
который создаёт почтовый алиас `zakaz@`. Иначе в воронке заведутся два сорта
лидов с разным заполнением, и любой отчёт по ним начнёт врать.

Поэтому здесь повторён путь ядра (`crm.lead.message_new` + `message_post`), а
не написан свой: те же три поля при создании, то же письмо в чате тем же
подтипом, те же вложения парами (имя, байты).
"""

import base64
import html
import logging
import mimetypes
import re
from urllib.parse import unquote

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.mail_client.tools.imap_client import ImapError

_logger = logging.getLogger(__name__)


# Превью письма — только видимый текст. Разбор UX, шаг 12 (ML-04): модуль
# mail_client вырезал теги, но оставлял содержимое <style> и <head>, и у
# писем B2B-Center вместо начала текста показывалось
# «.ExternalClass { width: 100%; } img { border: 0 none;…». А по превью писем
# торговых площадок решают, открывать ли письмо.
_PREVIEW_INVISIBLE = re.compile(
    r"<(style|script|head|title)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_PREVIEW_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_PREVIEW_TAGS = re.compile(r"<[^>]+>")

# Письма из Word и Outlook размечают картинки «условными комментариями»:
# <![if !vml]><img …><![endif]>. Браузер их молча пропускает, а санитайзер
# Odoo при синхронизации превращает в текст, и в окне письма читалось
# «<![if !vml]>» прямо перед логотипом (письмо ИЛИС, 28.09). Картинку между
# ними оставляем — вырезаем только сами метки, в любом из двух видов.
# Условие внутри метки короткое и без кавычек, угловых скобок и «&»: иначе
# выражение могло бы захватить кусок разметки до следующей «]&gt;» и,
# вырезав кавычку, собрать из текста живой атрибут src.
_WORD_CONDITIONAL = re.compile(
    r"(?:<|&lt;)!\[(?:if\b[^\]<>\"'&]{0,100}|endif)\](?:>|&gt;)", re.IGNORECASE)

# Картинки в тексте письма: <img src="cid:image001.png@01DD…">.
_CID_SRC = re.compile(r"""(\bsrc\s*=\s*)(["'])cid:([^"']+)\2""", re.IGNORECASE)
_IMAGE_MIME = re.compile(r"^image/[a-z0-9.+-]+$")
# Встроенная картинка едет в окно письма целиком, внутри ответа сервера.
# Ссылкой на наш сервер нельзя: окно письма — изолированная рамка (sandbox
# без allow-same-origin), и браузер шлёт из неё запрос без сессии. Замер
# 29.09.2026: /web/image/1941 из рамки — серая заглушка 6078 байт, та же
# ссылка со страницы — настоящая картинка 7360 байт. Отсюда потолки: подпись
# и логотип весят десятки килобайт, а мегабайтные фото остаются вложением.
_INLINE_MAX_BYTES = 1536 * 1024
_INLINE_TOTAL_BYTES = 6 * 1024 * 1024


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    @staticmethod
    def _build_preview(raw):
        """Первые 255 знаков видимого текста письма: без стилей, скриптов,
        заголовка документа и HTML-комментариев (в них Outlook прячет свои
        условные стили); сущности вроде &nbsp; — в символы."""
        if not raw:
            return False
        text = _PREVIEW_COMMENTS.sub(" ", raw)
        text = _PREVIEW_INVISIBLE.sub(" ", text)
        text = _PREVIEW_TAGS.sub(" ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:255] or False

    # ondelete='set null', а не cascade и не restrict: удалённый лид не должен
    # ни утаскивать за собой письмо, ни мешать его удалить. После удаления лида
    # кнопка честно создаст новый.
    pmk_lead_id = fields.Many2one(
        "crm.lead",
        string="Лид",
        readonly=True,
        copy=False,
        ondelete="set null",
        index="btree_not_null",
    )
    # Состав письма для картинок в тексте прочитан с сервера. Ставится один
    # раз: по письму без таких картинок сервер не спрашиваем вовсе, а по
    # прочитанному — повторно, только если картинка не скачалась.
    pmk_cid_checked = fields.Boolean(readonly=True, copy=False)

    # ------------------------------------------------------------------
    # показ письма
    # ------------------------------------------------------------------
    def _display_body(self):
        body = super()._display_body()
        if body and ("[if" in body or "[endif]" in body):
            body = _WORD_CONDITIONAL.sub("", body)
            # Метки вырезаны уже после того, как модуль почты заглушил
            # удалённые картинки. Глушим ещё раз: повтор безвреден
            # (заглушённый атрибут второй раз не совпадает), а если вырезка
            # что-то склеила — это не станет следящим пикселем.
            if not self.images_allowed:
                body = self._block_remote_assets(body)
        return body

    @api.model
    def get_message_detail(self, message_id):
        """Письмо для окна чтения — с картинками из подписи на своих местах.

        Картинка подставляется прямо в текст (data:), потому что окно письма —
        изолированная рамка: ссылку на наш сервер она откроет без входа в
        систему и получит заглушку. Вложение, которое уже показано в тексте,
        из списка вложений убираем — иначе один логотип висит дважды.
        """
        result = super().get_message_detail(message_id)
        body = result.get("body") or ""
        if "cid:" not in body:
            return result

        # Доступ к письму уже проверен в super(); дальше — как сам модуль
        # почты — под sudo: у читателя ящика нет прав писать в части письма.
        message = self.browse(message_id).sudo()
        parts = message._pmk_inline_parts()
        if not parts:
            return result

        shown, cache = set(), {}
        budget = [_INLINE_TOTAL_BYTES]

        def embed(match):
            cid = match.group(3)
            part = parts.get(cid)
            if not part:
                return match.group(0)
            if cid not in cache:
                cache[cid] = message._pmk_data_uri(part, budget)
            uri = cache[cid]
            if not uri:
                return match.group(0)
            shown.add(part.id)
            return "%s%s%s%s" % (match.group(1), match.group(2), uri, match.group(2))

        result["body"] = _CID_SRC.sub(embed, body)
        # Список вложений собираем заново, а не только фильтруем: части,
        # заведённые только что (картинка больше потолка, не картинка,
        # не скачалась), иначе не попали бы ни в текст, ни в список — до
        # следующего открытия письма.
        listed = {a["id"]: a for a in result.get("attachments", [])}
        result["attachments"] = [
            listed.get(part.id) or {
                "id": part.id,
                "name": part.name,
                "content_type": part.content_type or "",
                "size": part.file_size,
                "state": part.state,
            }
            for part in message.client_attachment_ids if part.id not in shown
        ]
        return result

    @staticmethod
    def _pmk_cids_in(html_text):
        """Номера картинок, на которые ссылается текст, в порядке появления."""
        seen = []
        for match in _CID_SRC.finditer(html_text or ""):
            cid = match.group(3)
            if cid not in seen:
                seen.append(cid)
        return seen

    def _pmk_body_cids(self):
        self.ensure_one()
        return self._pmk_cids_in(self.body_html)

    def _pmk_cid_map(self, cids):
        by_cid = {p.pmk_content_id: p for p in self.client_attachment_ids
                  if p.pmk_content_id}
        # В ссылке cid: номер может стоять в процентной записи (RFC 2392),
        # а в заголовке части — как есть.
        return {cid: by_cid.get(cid) or by_cid.get(unquote(cid)) for cid in cids}

    def _pmk_inline_parts(self):
        """{cid из текста: часть письма}; при нужде — один заход на сервер.

        Модуль почты заводит строки только для «настоящих» вложений и
        Content-ID не хранит, поэтому для старых писем состав читается
        заново — один раз. Сбой связи письмо не ломает: оно откроется без
        картинок, как раньше, и попытка повторится при следующем открытии.
        """
        self.ensure_one()
        cids = self._pmk_body_cids()
        if not cids:
            return {}
        parts = self._pmk_cid_map(cids)
        need_structure = not self.pmk_cid_checked and not all(parts.values())
        # «failed» сюда не входит: сломанную часть не дёргаем при каждом
        # открытии. Её по-прежнему можно скачать кнопкой или забрать в лид.
        need_bytes = any(p and self._pmk_embeddable(p) and p.state == "remote"
                         for p in parts.values())
        if (need_structure or need_bytes) and self.imap_uid:
            self._pmk_download_inline(cids, need_structure)
            self.invalidate_recordset(["client_attachment_ids"])
            parts = self._pmk_cid_map(cids)
        return {cid: part for cid, part in parts.items() if part}

    @staticmethod
    def _pmk_decoded_size(part):
        size = part.file_size or 0
        if (part.encoding or "").lower() == "base64":
            size = size * 3 // 4
        return size

    @staticmethod
    def _pmk_image_mime(part):
        """Тип картинки или None. Часть почтовых программ шлёт картинку как
        application/octet-stream — тогда тип узнаём по имени файла."""
        mimetype = (part.content_type or "").lower()
        if not _IMAGE_MIME.match(mimetype):
            mimetype = (mimetypes.guess_type(part.name or "")[0] or "").lower()
        return mimetype if _IMAGE_MIME.match(mimetype) else None

    def _pmk_embeddable(self, part):
        return bool(self._pmk_image_mime(part)
                    and self._pmk_decoded_size(part) <= _INLINE_MAX_BYTES)

    def _pmk_lock_message(self):
        """Два открытия одного письма разом (двойной щелчок, два менеджера в
        общем ящике) завели бы одну и ту же часть дважды и упёрлись бы в
        UNIQUE(message_id, part_number) — письмо не открылось бы вовсе.
        Второй запрос ждать не заставляем: NOWAIT даёт ошибку блокировки,
        Odoo сам повторяет такой запрос чуть позже, и к тому времени всё уже
        записано первым."""
        self.env.cr.execute(
            "SELECT id FROM mail_client_message WHERE id = %s FOR NO KEY UPDATE NOWAIT",
            [self.id])

    def _pmk_record_inline_parts(self, parts, cids):
        """Завести строки частей, на которые ссылается текст, с их Content-ID.

        `parts` — состав письма, как его разбирает модуль почты (BODYSTRUCTURE).
        Часть, которую модуль почты считает вложением, но ещё не завёл, заводим
        его же значениями — тогда его `_sync_attachment_records` её пропустит.
        Картинку, которую он вложением не считает, помечаем «в тексте».
        """
        self.ensure_one()
        wanted = set(cids) | {unquote(c) for c in cids}
        existing = {p.part_number: p for p in self.client_attachment_ids}
        attachment_numbers = [info["part_number"] for info in parts
                              if info.get("is_attachment")]
        new_vals = []
        for index, info in enumerate(parts):
            cid = (info.get("content_id") or "").strip()
            if not cid or cid not in wanted:
                continue
            record = existing.get(info["part_number"])
            if record:
                if record.pmk_content_id != cid:
                    record.pmk_content_id = cid
                continue
            is_attachment = bool(info.get("is_attachment"))
            new_vals.append({
                "message_id": self.id,
                # Порядок в списке вложений — как у модуля почты: он нумерует
                # только вложения, начиная с 10. Картинки из текста — после.
                "sequence": (10 + attachment_numbers.index(info["part_number"])
                             if is_attachment else 100 + index),
                "name": (info["filename"] or (_("part %s", info["part_number"])
                                              if is_attachment else cid.split("@")[0])),
                "part_number": info["part_number"],
                "content_type": info["content_type"],
                "encoding": info["encoding"],
                "file_size": info["size"],
                "pmk_content_id": cid,
                "pmk_inline": not is_attachment,
            })
        if new_vals:
            self.env["mail.client.attachment"].sudo().create(new_vals)
        self.pmk_cid_checked = True

    def _pmk_fetch_inline_bytes(self, connection, cids):
        """Скачать картинки из текста уже открытым подключением."""
        self.ensure_one()
        for part in self._pmk_cid_map(cids).values():
            if not part or part.state != "remote" or not self._pmk_embeddable(part):
                continue
            try:
                payload = connection.fetch_part(
                    self.imap_uid, part.part_number, part.encoding)
            except ImapError as exc:
                # Одна битая картинка не должна мешать остальным.
                part.write({"state": "failed", "error_message": str(exc)[:255]})
                continue
            attachment = self.env["ir.attachment"].sudo().create({
                "name": part.name,
                "datas": base64.b64encode(payload),
                "mimetype": (self._pmk_image_mime(part) or part.content_type
                             or "application/octet-stream"),
                "res_model": "mail.client.message",
                "res_id": self.id,
            })
            part.write({"attachment_id": attachment.id, "state": "fetched",
                        "error_message": False})
        self.env["mail.client.audit"].sudo().log_access(
            server=self.account_id.server_id, account=self.account_id,
            action="body_fetch", detail=_("Картинки в тексте письма"))

    def _fetch_text_parts(self, connection, parts):
        """Письмо читается с сервера впервые — картинки из текста забираем
        тем же подключением. Иначе первое открытие письма с подписью
        заходило бы в ящик дважды: за текстом и отдельно за картинками.

        Сбой здесь не должен сорвать чтение самого письма: модуль почты
        пометил бы его «не удалось», поэтому ошибки связи только в журнал —
        при открытии картинки дозаберёт `_pmk_inline_parts`.
        """
        html_text, text = super()._fetch_text_parts(connection, parts)
        cids = self._pmk_cids_in(html_text) if html_text and "cid:" in html_text else []
        if cids and self.imap_uid:
            self._pmk_lock_message()
            try:
                self._pmk_record_inline_parts(parts, cids)
                self._pmk_fetch_inline_bytes(connection, cids)
            except (ImapError, UserError, OSError) as exc:
                _logger.warning("Письмо %s: картинки в тексте не забрать — %s",
                                self.id, exc)
        return html_text, text

    def _pmk_download_inline(self, cids, need_structure):
        """Отдельный заход на сервер — для писем, прочитанных до этой правки
        (у них состав есть, а Content-ID не записан), и для докачки."""
        self.ensure_one()
        self._pmk_lock_message()
        connection = None
        try:
            connection = self.account_id._open_connection()
            connection.select(self.folder_id.imap_path, readonly=True)
            if need_structure:
                self._pmk_record_inline_parts(
                    connection.fetch_structure(self.imap_uid), cids)
                self.invalidate_recordset(["client_attachment_ids"])
            self._pmk_fetch_inline_bytes(connection, cids)
        except (ImapError, UserError, OSError) as exc:
            _logger.warning("Письмо %s: картинки в тексте не забрать — %s",
                            self.id, exc)
        finally:
            if connection:
                connection.close()

    def _pmk_data_uri(self, part, budget):
        """Картинка как data: для подстановки в текст, или None."""
        mimetype = self._pmk_image_mime(part)
        if part.state != "fetched" or not part.attachment_id or not mimetype:
            return None
        raw = part.attachment_id.raw or b""
        if not raw or len(raw) > _INLINE_MAX_BYTES or len(raw) > budget[0]:
            return None
        budget[0] -= len(raw)
        return "data:%s;base64,%s" % (mimetype, base64.b64encode(raw).decode())

    # ------------------------------------------------------------------
    # кнопка
    # ------------------------------------------------------------------
    def action_pmk_create_lead(self):
        """Создать лид из письма либо открыть уже созданный."""
        self.ensure_one()
        self.check_access("read")

        lead = self._pmk_find_lead()
        created = not lead
        if created:
            lead = self._pmk_create_lead()

        # sudo точечно на одно наше поле: у зрителя общего ящика прав на запись
        # в письмо нет, а проверки на чтение письма и на создание лида уже
        # прошли выше. Тем же приёмом пользуется и сам почтовый модуль.
        if self.pmk_lead_id != lead:
            self.sudo().pmk_lead_id = lead.id

        return {
            "created": created,
            "action": {
                "type": "ir.actions.act_window",
                "name": _("Лид"),
                "res_model": "crm.lead",
                "res_id": lead.id,
                "views": [[False, "form"]],
                # Диалог, а не переход: у почтового модуля нет сохранения
                # состояния, и возврат по хлебным крошкам пересоздал бы его —
                # человек вернулся бы в первую папку и потерял открытое письмо.
                "target": "new",
            },
        }

    # ------------------------------------------------------------------
    # внутреннее
    # ------------------------------------------------------------------
    def _pmk_find_lead(self):
        """Лид, уже сделанный из этого письма — кнопкой или алиасом."""
        self.ensure_one()
        if self.pmk_lead_id:
            return self.pmk_lead_id
        if not self.message_id:
            return self.env["crm.lead"]

        # Алиас кладёт письмо в чат лида с тем же заголовком Message-ID, что
        # хранит почтовый модуль. Это единственный способ не сделать второй лид
        # к письму, которое уже приехало на zakaz@ и лид себе уже завело.
        posted = self.env["mail.message"].sudo().search(
            [
                ("message_id", "=", self.message_id),
                ("model", "=", "crm.lead"),
                ("res_id", "!=", False),
            ],
            limit=1,
        )
        if not posted:
            return self.env["crm.lead"]
        return self.env["crm.lead"].browse(posted.res_id).exists()

    def _pmk_create_lead(self):
        self.ensure_one()
        attachments, failed = self._pmk_letter_attachments()

        # `type` не передаём намеренно: у crm.lead он вычисляется от того,
        # включён ли в настройках CRM отдельный этап «Лиды». Жёсткое значение
        # разошлось бы с лидами из алиаса и сломалось бы в день, когда Антон
        # этот этап включит.
        #
        # `partner_id` берём готовый: почтовый модуль ищет контакт по адресу и
        # НЕ создаёт его, если не нашёл. Так же ведёт себя и почтовый шлюз
        # ядра. Автосоздание контакта здесь было бы вредно: ящик собирает
        # рассылки, и каждый промах кнопки оседал бы мусором в базе клиентов.
        # МЕНЕДЖЕР — ТОТ, КТО НАЖАЛ «ЛИД» (решение Антона 28.09.2026, разбор UX).
        # Раньше заявка рождалась без менеджера, а воронка открывается с
        # фильтром «Моя воронка» — и новая заявка в ней не показывалась, пока
        # кто-то не впишет себя руками. Правило завода: менеджер сам переводит
        # письмо в заявку, значит, он её и ведёт.
        #
        # Системного пользователя (OdooBot, запуск из крона или shell) не
        # ставим: для такого случая остаётся штатное распределение на
        # руководителя команды ниже.
        user = self.env.user
        assignee = user if user._is_internal() and not user._is_superuser() else False
        lead = (
            self.env["crm.lead"]
            .with_context(
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                default_user_id=assignee.id if assignee else False,
            )
            .create(
                {
                    "name": self.subject or _("Без темы"),
                    "email_from": self.email_from,
                    "partner_id": self.partner_id.id or False,
                    "user_id": assignee.id if assignee else False,
                }
            )
        )
        # Срабатывает только для заявки без менеджера, то есть при системном
        # запуске.
        lead._assign_userless_lead_in_team(_("письмо из почты"))

        lead.message_post(
            # Именно _display_body(), а не body_html: поле хранит письмо без
            # санитизации атрибутов, а вырезание удалённых картинок и
            # трекинг-пикселей модуль делает на отдаче. Иначе мы бы протащили
            # в CRM ровно то, от чего почта защищается.
            body=Markup(self._display_body() or ""),
            subject=self.subject,
            message_type="email",
            subtype_id=self.env.ref("crm.mt_lead_create").id,
            # False, а не None: при None ядро подставит текущего пользователя,
            # и письмо в чате будет выглядеть написанным менеджером.
            author_id=self.partner_id.id or False,
            email_from=self.email_from,
            date=self.date,
            # Без Message-ID ломается единственный надёжный способ связать это
            # письмо с лидом, который мог создать алиас.
            message_id=self.message_id,
            attachments=attachments,
            # Пустой список намеренно: получатели здесь означали бы рассылку
            # уведомлений — кнопка не должна писать отправителю.
            partner_ids=[],
        )

        if failed:
            items = Markup("").join(Markup("<li>%s</li>") % name for name, _err in failed)
            lead.message_post(
                body=Markup("<p>Не удалось забрать из почты:</p><ul>%s</ul>") % items,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )
        return lead

    def _pmk_letter_attachments(self):
        """Пары (имя, байты) по каждой части письма; у картинки из текста
        письма третьим элементом — её номер cid.

        Возвращает ещё и список несработавших: одна недоступная часть не повод
        потерять лид целиком.
        """
        self.ensure_one()
        payload, failed = [], []

        # Строки частей появляются только при разборе тела. Синхронизация папки
        # выставляет has_attachment, но частей не создаёт — на непрочитанном
        # письме без этого вызова лид молча вышел бы без вложений.
        try:
            self.sudo()._fetch_body()
        except (UserError, OSError) as exc:
            _logger.warning("Письмо %s: тело не забрать — %s", self.id, exc)
            failed.append((_("тело письма"), str(exc)))

        # Картинки из текста письма (подпись, логотип, скриншот). Их части
        # модуль почты сам не заводит, и без этого вызова лид получил бы
        # письмо с пустыми рамками. Номер cid отдаём ядру третьим элементом —
        # message_post сам заменит ссылку в тексте на сохранённую картинку,
        # ровно как делает почтовый шлюз с входящим письмом.
        cid_of = {}
        for cid, part in self.sudo()._pmk_inline_parts().items():
            cid_of.setdefault(part.id, cid)

        for part in self.client_attachment_ids:
            try:
                # sudo обязателен: у пользователя почты на модель вложений
                # право только на чтение, а _fetch пишет результат скачивания.
                # Так же делает сам модуль в своём download().
                attachment = part.sudo()._fetch()
            except (UserError, OSError) as exc:
                # Ловим поштучно и не даём исключению всплыть: иначе Odoo
                # откатит транзакцию вместе с уже созданным лидом, а отметка
                # о неудаче на части не сохранится.
                failed.append((part.name, str(exc)))
                continue
            item = (part.name, base64.b64decode(attachment.datas))
            if part.id in cid_of:
                item += ({"cid": cid_of[part.id]},)
            payload.append(item)

        return payload, failed
