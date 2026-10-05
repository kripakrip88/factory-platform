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

ПРАВКА ПМК (шаг 45, 05.10.2026): файл ИЗ АРХИВА ZIP — маршрут
/mail_client/attachment/<id>/member/<номер>. Те же права (письмо видно
человеку), те же заголовки; байты — одного файла архива, распакованного в
память с пределами (tools/archive_reader.py). Только чтение: в базе ничего
не пишется, кроме штатного скачивания самого архива с IMAP, если он ещё не
скачан (EXAMINE и BODY.PEEK — отметки «прочитано» это не ставит).
?download=1 — отдать файл на сохранение под его именем без папок архива.
"""
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request

from ..models.mail_client_attachment_preview import (
    BROWSER_IMAGE_FORMATS, FORMAT_MIME, PreviewError, detect_format,
)
from ..tools.archive_reader import ArchiveError

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


def _text_response(message, status):
    return request.make_response(message, status=status, headers=[
        ('Content-Type', 'text/plain; charset=utf-8'),
        ('X-Content-Type-Options', 'nosniff'),
        ('Cache-Control', 'private, max-age=0, no-store'),
    ])


def _file_response(payload, filename, download=False):
    """Ответ с байтами файла: свой тип, nosniff, sandbox, без кэша.

    download — отдать на сохранение: тип application/octet-stream и
    attachment при любом содержимом (ПРАВКА ПМК, шаг 45).
    """
    if download:
        content_type, disposition = 'application/octet-stream', 'attachment'
    else:
        fmt, _kind, _note = detect_format(payload, filename)
        content_type = NAMED_TYPES.get(fmt, 'application/octet-stream')
        # Встроенным показом браузера пользуются только растровые картинки:
        # их он рисует и выполнить в них нечего. Всё остальное, включая PDF,
        # уходит «вложением», и прямой переход по ссылке обернётся
        # скачиванием, а не показом чужого файла на нашем домене.
        disposition = 'inline' if fmt in BROWSER_IMAGE_FORMATS else 'attachment'
    return request.make_response(payload, headers=[
        ('Content-Type', content_type),
        ('Content-Length', len(payload)),
        ('Content-Disposition', content_disposition(filename or 'file', disposition)),
        ('X-Content-Type-Options', 'nosniff'),
        ('Content-Security-Policy', "sandbox; default-src 'none'"),
        # Чужой файл в общем кэше не нужен: ящик общий, а доступ к письму
        # у разных людей разный.
        ('Cache-Control', 'private, max-age=0, no-store'),
    ])


class MailClientPreview(http.Controller):

    def _readable(self, attachment_id):
        """Вложение, если письмо видно человеку, иначе None (ответ — 404).

        Права проверяются на письме и от имени человека; sudo дальше — только
        на скачивание части с IMAP, как и в остальном модуле.
        """
        record = request.env['mail.client.attachment'].browse(attachment_id).exists()
        if not record:
            return None
        try:
            record.message_id.check_access('read')
        except AccessError:
            return None
        return record.sudo()

    @http.route('/mail_client/attachment/<int:attachment_id>/raw', type='http',
                auth='user', methods=['GET'])
    def attachment_raw(self, attachment_id, **kwargs):
        record = self._readable(attachment_id)
        if not record:
            return request.not_found()
        try:
            payload = record._preview_bytes()
        except PreviewError as exc:
            return _text_response(str(exc), 413)
        except UserError as exc:
            _logger.warning("Mail Client: вложение %s не получено: %s", attachment_id, exc)
            return _text_response(str(exc), 502)
        return _file_response(payload, record.name)

    @http.route('/mail_client/attachment/<int:attachment_id>/member/<int:index>',
                type='http', auth='user', methods=['GET'])
    def attachment_member(self, attachment_id, index, download=None, **kwargs):
        """Один файл из архива ZIP — для pdf.js, <img> и «Скачать».

        ПРАВКА ПМК (шаг 45). Номер — index строки списка архива (preview()
        отдаёт его в archive.entries). Отказы — текстом с кодом из
        ArchiveError: 404 нет такого файла, 413 предел, 422 пароль, порча,
        подделка.
        """
        record = self._readable(attachment_id)
        if not record:
            return request.not_found()
        try:
            blob = record._preview_bytes()
            payload, entry = record._archive_member(blob, index)
        except ArchiveError as exc:
            return _text_response(str(exc), exc.status)
        except PreviewError as exc:
            return _text_response(str(exc), 413)
        except UserError as exc:
            _logger.warning("Mail Client: архив %s не получен: %s", attachment_id, exc)
            return _text_response(str(exc), 502)
        # Имя — только сам файл, без папок архива: «../../Счёт.pdf» уходит
        # как «Счёт.pdf». Русские буквы content_disposition кодирует сам.
        return _file_response(payload, entry['name'],
                              download=(download or '') not in ('', '0', 'false'))
