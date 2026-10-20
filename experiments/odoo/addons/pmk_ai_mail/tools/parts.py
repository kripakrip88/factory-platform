# -*- coding: utf-8 -*-
"""Вложения письма → блоки сообщения Claude (20.10.2026).

PDF — документом целиком (Claude видит и текст, и чертежи), сканы и фото —
картинкой (уменьшенной), Excel — таблицей в тексте, Word — текстом. Архивы,
DWG и прочее — только именем: содержимое не читаем. Мелкие картинки (логотипы
подписи, «image001.png» по 5–15 КБ) пропускаем — они только тратят деньги.

Пределы — чтобы одно письмо не стоило как десять: файлов на письмо, размер
файла, страниц PDF (больше — текст первых страниц вместо документа).
"""
import base64
import io
import logging

_logger = logging.getLogger(__name__)

MAX_FILES = 5                 # вложений читаем на письмо
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 25            # больше — текст первых страниц, не документ
MIN_IMAGE_BYTES = 20 * 1024   # меньше — логотип подписи
MAX_IMAGE_SIDE = 1600
MAX_SHEET_ROWS = 120
MAX_SHEET_COLS = 20
MAX_TEXT_CHARS = 12000

IMAGE_TYPES = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp",
               "bmp": "image/jpeg", "tiff": "image/jpeg"}


def _fmt(blob, name):
    try:
        from odoo.addons.mail_client.models.mail_client_attachment_preview import detect_format
        return detect_format(blob, name)[0] or ""
    except Exception:  # noqa: BLE001 — неизвестный формат — значит «не читаем»
        return ""


def _pdf_pages(blob):
    try:
        from odoo.addons.mail_client.models.mail_client_attachment_preview import pdf_info
        info = pdf_info(blob)
        return info.get("pages"), bool(info.get("encrypted"))
    except Exception:  # noqa: BLE001
        return None, False


def _image_block(blob):
    """Картинка ≤ MAX_IMAGE_SIDE по большей стороне, JPEG — дешевле по токенам."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(blob))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.size) > MAX_IMAGE_SIDE:
            img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=82)
        data = out.getvalue()
    except Exception:  # noqa: BLE001 — битая картинка: пропускаем
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(data).decode()}}


def _sheet_text(blob, fmt):
    from odoo.addons.mail_client.models.mail_client_attachment_preview import read_sheets
    sheets = read_sheets(blob, fmt)
    lines = []
    for sheet in sheets[:5]:
        lines.append("Лист «%s» (%s строк)" % (sheet.get("name") or "", sheet.get("nrows") or 0))
        for row in (sheet.get("rows") or [])[:MAX_SHEET_ROWS]:
            cells = [str(c if c is not None else "").strip() for c in row[:MAX_SHEET_COLS]]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _plain_text(name, blob):
    from odoo.addons.pmk_mail_ui.tools import requisites
    return requisites.attachment_text(name, "", blob) or ""


def build(files):
    """files: [(имя, байты)] → (блоки сообщения, [что сделали с каждым файлом]).

    «Что сделали» — строки для журнала и для промпта: «ТЗ.pdf — документ, 3 стр.»,
    «logo.png — пропущен (логотип)», «чертёж.dwg — только имя».
    """
    blocks, notes, used = [], [], 0
    for name, blob in files:
        if not blob:
            continue
        size = len(blob)
        fmt = _fmt(blob, name)
        if used >= MAX_FILES:
            notes.append("%s — не читали (больше %s вложений)" % (name, MAX_FILES))
            continue
        if size > MAX_FILE_BYTES:
            notes.append("%s — только имя (файл больше 8 МБ)" % name)
            continue
        try:
            if fmt == "pdf":
                pages, encrypted = _pdf_pages(blob)
                if encrypted:
                    notes.append("%s — PDF под паролем, не прочитан" % name)
                    continue
                if pages and pages > MAX_PDF_PAGES:
                    text = _plain_text(name, blob)[:MAX_TEXT_CHARS]
                    blocks.append({"type": "text", "text": "Вложение «%s» (PDF, %s стр., текст первых страниц):\n%s"
                                   % (name, pages, text or "(текста нет — скан)")})
                    notes.append("%s — PDF %s стр., прочитан текст" % (name, pages))
                else:
                    blocks.append({"type": "text", "text": "Вложение «%s»:" % name})
                    blocks.append({"type": "document", "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(blob).decode()}})
                    notes.append("%s — PDF%s, прочитан" % (name, " %s стр." % pages if pages else ""))
                used += 1
            elif fmt in IMAGE_TYPES:
                if size < MIN_IMAGE_BYTES:
                    notes.append("%s — пропущен (мелкая картинка, логотип)" % name)
                    continue
                block = _image_block(blob)
                if not block:
                    notes.append("%s — картинка не открылась" % name)
                    continue
                blocks += [{"type": "text", "text": "Вложение «%s» (картинка):" % name}, block]
                notes.append("%s — картинка, прочитана" % name)
                used += 1
            elif fmt in ("xlsx", "xls", "ods", "csv"):
                text = _sheet_text(blob, fmt)[:MAX_TEXT_CHARS]
                blocks.append({"type": "text", "text": "Вложение «%s» (таблица):\n%s" % (name, text)})
                notes.append("%s — таблица, прочитана" % name)
                used += 1
            elif fmt in ("docx", "txt") or name.lower().endswith((".docx", ".txt")):
                text = _plain_text(name, blob)[:MAX_TEXT_CHARS]
                if not text.strip():
                    notes.append("%s — текста нет" % name)
                    continue
                blocks.append({"type": "text", "text": "Вложение «%s» (текст):\n%s" % (name, text)})
                notes.append("%s — текст, прочитан" % name)
                used += 1
            else:
                notes.append("%s — только имя (%s не читаем)" % (name, fmt or "формат"))
        except Exception as exc:  # noqa: BLE001 — один файл не валит разбор письма
            _logger.warning("pmk_ai_mail: вложение %s не прочитано: %s", name, exc)
            notes.append("%s — не прочитан (%s)" % (name, exc.__class__.__name__))
    return blocks, notes
