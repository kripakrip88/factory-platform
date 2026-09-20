# -*- coding: utf-8 -*-
"""Операции над PDF: собрать новый файл из страниц имеющихся вложений.

Вся правка сводится к ОДНОЙ операции — «собери документ из вот этих страниц
в таком порядке и с такими поворотами». Через неё выражается всё, что нужно:
повернуть — поворот у страницы, удалить — страницы нет в списке, переставить
— другой порядок, склеить — страницы из разных вложений, разрезать — несколько
документов на выходе. Одна операция вместо пяти отдельных: меньше кода и
нечему разойтись между собой.

Права НЕ обходим: ни одного sudo(). Читаем исходные вложения и создаём новые
от имени пользователя, поэтому проверки доступа Odoo к вложениям и к записи,
к которой они привязаны, работают как обычно.
"""

import base64
import io
import logging

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# Пределы против случайного и намеренного перебора: план приходит из браузера,
# то есть данным доверять нельзя. Числа с запасом под заводские документы —
# альбом чертежей на сотню листов проходит свободно.
MAX_DOCUMENTS = 20
MAX_PAGES_PER_DOC = 500
MAX_TOTAL_PAGES = 2000


class PmkPdfJob(models.TransientModel):
    _name = "pmk.pdf.job"
    _description = "Правка PDF"

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    @api.model
    def pmk_sources(self, res_model, res_id):
        """PDF-вложения записи: чем их правит редактор.

        Возвращаем и число страниц: без него редактор не сможет показать,
        из чего выбирать, пока не скачает каждый файл целиком.
        """
        if not res_model or not res_id:
            return []
        attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", res_model),
                ("res_id", "=", int(res_id)),
                ("mimetype", "=", "application/pdf"),
            ],
            order="id",
        )
        result = []
        for att in attachments:
            pages, error = self._pmk_page_count(att)
            result.append({
                "id": att.id,
                "name": att.name,
                "pages": pages,
                "error": error,
            })
        return result

    def _pmk_page_count(self, attachment):
        """Число страниц. Битый или закрытый паролем файл — не повод падать."""
        try:
            reader = self._pmk_reader(attachment)
        except UserError as exc:
            return 0, str(exc)
        return len(reader.pages), False

    def _pmk_reader(self, attachment):
        from PyPDF2 import PdfReader

        raw = attachment.raw
        if not raw:
            raise UserError(_("Файл «%s» пуст.", attachment.name))
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception as exc:  # noqa: BLE001 — причин у битого PDF много
            raise UserError(_("Не удалось прочитать «%s»: %s", attachment.name, exc))
        if reader.is_encrypted:
            # Пустой пароль открывает часть «защищённых» файлов — пробуем его,
            # прежде чем отказывать.
            try:
                if not reader.decrypt(""):
                    raise UserError(
                        _("Файл «%s» защищён паролем.", attachment.name))
            except UserError:
                raise
            except Exception:  # noqa: BLE001
                raise UserError(_("Файл «%s» защищён паролем.", attachment.name))
        return reader

    # ------------------------------------------------------------------
    # Сборка
    # ------------------------------------------------------------------

    @api.model
    def pmk_build(self, documents, res_model, res_id):
        """Собрать новые PDF по плану и приложить их к записи.

        documents: [{"name": "...", "pages": [{"src": id, "page": 0, "rotate": 90}]}]
        rotate — поворот ОТНОСИТЕЛЬНО того, как страница выглядит сейчас:
        пользователь крутит то, что видит, а не абстрактное исходное значение.
        """
        self._pmk_check_plan(documents)
        record = self._pmk_check_target(res_model, res_id)

        # Каждый исходник читаем ОДИН раз, даже если из него берут сто страниц.
        readers = {}
        for doc in documents:
            for page in doc["pages"]:
                src = int(page["src"])
                if src not in readers:
                    readers[src] = self._pmk_reader(self._pmk_source(src))

        created = self.env["ir.attachment"]
        for doc in documents:
            data = self._pmk_assemble(doc["pages"], readers)
            created |= self.env["ir.attachment"].create({
                "name": self._pmk_filename(doc.get("name")),
                "datas": base64.b64encode(data),
                "mimetype": "application/pdf",
                "res_model": record._name,
                "res_id": record.id,
            })

        _logger.info(
            "pmk_pdf: собрано %s файл(ов) для %s,%s пользователем %s",
            len(created), record._name, record.id, self.env.user.login,
        )
        return [{"id": att.id, "name": att.name} for att in created]

    def _pmk_assemble(self, pages, readers):
        from PyPDF2 import PdfWriter

        writer = PdfWriter()
        for item in pages:
            reader = readers[int(item["src"])]
            index = int(item["page"])
            if not 0 <= index < len(reader.pages):
                raise UserError(_("В файле нет страницы %s.", index + 1))
            page = reader.pages[index]
            rotate = int(item.get("rotate") or 0) % 360
            if rotate:
                # rotate() поворачивает ОТНОСИТЕЛЬНО текущего значения —
                # ровно то, что нужно: пользователь крутит видимое.
                page.rotate(rotate)
            writer.add_page(page)

        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    # ------------------------------------------------------------------
    # Проверки
    # ------------------------------------------------------------------

    def _pmk_check_plan(self, documents):
        """План приходит из браузера — проверяем всё, не доверяя ничему."""
        if not isinstance(documents, list) or not documents:
            raise UserError(_("Нечего собирать: не выбрано ни одной страницы."))
        if len(documents) > MAX_DOCUMENTS:
            raise UserError(
                _("За один раз можно собрать не больше %s файлов.", MAX_DOCUMENTS))

        total = 0
        for doc in documents:
            if not isinstance(doc, dict):
                raise UserError(_("Неверный план сборки."))
            pages = doc.get("pages")
            if not isinstance(pages, list) or not pages:
                raise UserError(_("В одном из файлов не выбрано ни одной страницы."))
            if len(pages) > MAX_PAGES_PER_DOC:
                raise UserError(
                    _("В одном файле не больше %s страниц.", MAX_PAGES_PER_DOC))
            total += len(pages)
            for page in pages:
                if not isinstance(page, dict) or "src" not in page or "page" not in page:
                    raise UserError(_("Неверный план сборки."))
                rotate = int(page.get("rotate") or 0)
                if rotate % 90:
                    raise UserError(_("Поворот возможен только на 90 градусов."))
        if total > MAX_TOTAL_PAGES:
            raise UserError(
                _("За один раз можно обработать не больше %s страниц.", MAX_TOTAL_PAGES))

    def _pmk_source(self, attachment_id):
        """Исходное вложение — с проверкой прав и того, что это вообще PDF."""
        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if not attachment:
            raise UserError(_("Исходный файл не найден."))
        # read() поднимет AccessError, если пользователю файл не положен.
        attachment.check("read")
        if attachment.mimetype != "application/pdf":
            raise UserError(_("«%s» — не PDF.", attachment.name))
        return attachment

    def _pmk_check_target(self, res_model, res_id):
        """Результат кладём только туда, где пользователю можно писать."""
        if not res_model or not res_id:
            raise UserError(_("Не указан документ, к которому приложить результат."))
        if res_model not in self.env:
            raise UserError(_("Неизвестная модель «%s».", res_model))
        record = self.env[res_model].browse(int(res_id)).exists()
        if not record:
            raise UserError(_("Документ не найден."))
        try:
            record.check_access("write")
        except AccessError:
            raise AccessError(
                _("Нет прав изменять этот документ, поэтому и приложить файл нельзя."))
        return record

    def _pmk_filename(self, name):
        name = (name or "").strip() or _("Документ")
        if not name.lower().endswith(".pdf"):
            name = "%s.pdf" % name
        return name
