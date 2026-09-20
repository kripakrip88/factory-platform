# -*- coding: utf-8 -*-
# Правка ПМК Парк к вендорскому модулю mail_client.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Байты вложения для просмотра в системе — так, чтобы показать их мог только наш просмотрщик.

Просмотр PDF устроен так: страницу рисует pdf.js, а сюда он ходит за байтами
обычным запросом. Значит отдавать файл надо тем способом, при котором браузер
сам его показать не возьмётся, даже если ссылку открыть в новой вкладке:

  * тип ставим свой, а не тот, что написал отправитель, и запрещаем
    угадывание (nosniff) — иначе «счёт.pdf» с HTML внутри выполнится как
    страница нашего домена со всеми правами сессии;
  * всё, кроме картинок, уходит как вложение (attachment): PDF получает
    pdf.js запросом, а прямой переход по ссылке обернётся скачиванием, а не
    показом встроенным просмотрщиком браузера;
  * SVG картинкой НЕ считаем: внутри него бывает скрипт, и это единственный
    формат изображения, который выполняется;
  * заголовок CSP sandbox гасит скрипты и плагины, если такую ссылку всё же
    откроют в отдельной вкладке.

Штатный /web/content для этого не годится: он отдаёт файл под тем типом,
который стоит в ir.attachment, то есть под тем, который сообщил отправитель.
"""
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request

from ..models.mail_client_attachment_preview import (
    BROWSER_IMAGE_FORMATS, FORMAT_MIME, PreviewError, detect_format,
)

_logger = logging.getLogger(__name__)

# Форматы, которые уходят под своим настоящим типом.
#
# Список картинок берём из модели, а не заводим свой: там же решается, какой
# вид файла объявить окну просмотра. Разойдись два списка — и окно поставит
# <img> на файл, который контроллер отдаёт «скачиванием», а человек увидит
# битый значок вместо картинки.
#
# PDF отдаём с настоящим типом: pdf.js его проверяет, а показать файл сам
# браузер всё равно не сможет — мешает disposition=attachment.
NAMED_TYPES = {fmt: FORMAT_MIME[fmt] for fmt in BROWSER_IMAGE_FORMATS + ('pdf',)}


class MailClientPreview(http.Controller):

    @http.route('/mail_client/attachment/<int:attachment_id>/raw', type='http',
                auth='user', methods=['GET'])
    def attachment_raw(self, attachment_id, **kwargs):
        record = request.env['mail.client.attachment'].browse(attachment_id).exists()
        if not record:
            return request.not_found()
        try:
            # Права проверяются на письме и от имени человека; sudo дальше —
            # только на скачивание части с IMAP, как и в остальном модуле.
            record.message_id.check_access('read')
        except AccessError:
            return request.not_found()

        record = record.sudo()
        try:
            payload = record._preview_bytes()
        except PreviewError as exc:
            return request.make_response(str(exc), status=413, headers=[
                ('Content-Type', 'text/plain; charset=utf-8')])
        except UserError as exc:
            _logger.warning("Mail Client: вложение %s не получено: %s", attachment_id, exc)
            return request.make_response(str(exc), status=502, headers=[
                ('Content-Type', 'text/plain; charset=utf-8')])

        fmt, _kind, _note = detect_format(payload, record.name)
        content_type = NAMED_TYPES.get(fmt, 'application/octet-stream')
        # Встроенным показом браузера пользуются только растровые картинки:
        # их он рисует и выполнить в них нечего. Всё остальное, включая PDF,
        # уходит «вложением», и прямой переход по ссылке обернётся
        # скачиванием, а не показом чужого файла на нашем домене.
        disposition = 'inline' if fmt in BROWSER_IMAGE_FORMATS else 'attachment'

        return request.make_response(payload, headers=[
            ('Content-Type', content_type),
            ('Content-Length', len(payload)),
            ('Content-Disposition', content_disposition(record.name or 'file',
                                                        disposition)),
            ('X-Content-Type-Options', 'nosniff'),
            ('Content-Security-Policy', "sandbox; default-src 'none'"),
            # Чужой файл в общем кэше не нужен: ящик общий, а доступ к письму
            # у разных людей разный.
            ('Cache-Control', 'private, max-age=0, no-store'),
        ])
