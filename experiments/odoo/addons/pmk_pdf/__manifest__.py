# -*- coding: utf-8 -*-
{
    "name": "ПМК Парк — Работа с PDF",
    "summary": "Страницы PDF прямо в документе: повернуть, удалить, переставить, склеить, разрезать",
    "description": """
Правка PDF без выхода из системы и БЕЗ отдельного сервиса.

Почему свой модуль, а не Stirling-PDF или PDFCraft. PDFCraft встроить нельзя
технически: он отдаёт X-Frame-Options SAMEORIGIN, не имеет программного
интерфейса и требует cross-origin isolation, которая внутри iframe теряется.
Stirling встроить можно, но это Java-сервис: 1,07 ГБ образ и 2-4 ГБ памяти
по документации, причём лёгкий вариант образа не содержит ни OCR, ни
LibreOffice — то есть ровно того, ради чего его ставят.

Всё нужное уже есть в Odoo:
  pdf.js  — web/static/lib/pdfjs, рисует страницы в браузере;
  PyPDF2  — 2.12.1, собирает новый файл на сервере;
  pdfminer, reportlab, PIL — на будущее.

Распознавание сканов (tesseract) добавится отдельно: страницу в картинку
превращает тот же pdf.js в браузере, поэтому ни poppler, ни ghostscript
не понадобятся.
""",
    "version": "19.0.1.0.0",
    "category": "Productivity/Documents",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/pmk_pdf_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_pdf/static/src/scss/pdf_editor.scss",
            "pmk_pdf/static/src/js/pdf_editor.js",
            "pmk_pdf/static/src/xml/pdf_editor.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
