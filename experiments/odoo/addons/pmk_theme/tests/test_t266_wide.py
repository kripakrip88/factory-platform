# -*- coding: utf-8 -*-
"""Задача 266 (шаг 68, 12.10.2026): лист во всю ширину большого экрана.

У форм без ленты (o_pmk_chatter_out, шаг 65) потолка листа 1800 px нет.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

FORMS_SCSS = "pmk_theme/static/src/scss/forms_nexus.scss"
MARK = "// ═══ Шаг 68"


@tagged("post_install", "-at_install")
class TestT266Wide(TransactionCase):

    def _section(self):
        with file_open(FORMS_SCSS) as f:
            source = f.read()
        self.assertEqual(source.count(MARK), 1)
        start = source.index(MARK)
        self.assertLess(source.index("// ═══ Шаг 67"), start)
        end = source.find("// ═══", start + 1)
        return source[start:end if end != -1 else None]

    def test_no_cap_without_chatter(self):
        import sass
        css = re.sub(r"\s+", " ", sass.compile(string=self._section()))
        self.assertRegex(css, r"\.o_form_view\.o_pmk_chatter_out [^{]*> \.o_form_sheet_bg \{ max-width: none")
        self.assertIn(":not(:has(> .o_attachment_preview))", css)
        self.assertIn("@media screen", css)
