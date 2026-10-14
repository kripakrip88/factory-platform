# -*- coding: utf-8 -*-
"""Реквизиты и контакт из письма (tools/requisites.py) — правила без базы.

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_requisites_rules.py

Данные выдуманы; ИНН собираются здесь же с верными контрольными цифрами.
"""
import io
import os
import sys
import unittest
import zipfile

try:
    from ..tools import requisites
except (ImportError, ValueError):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import requisites


def inn10(body):
    digits = [int(c) for c in body]
    check = sum(d * w for d, w in zip(digits, (2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10
    return body + str(check)


INN = inn10("270000123")
OWN = inn10("272100456")


class TestRequisites(unittest.TestCase):

    def test_requisites_in_text(self):
        text = ("Карточка предприятия\nИНН/КПП %s/270001001\nОГРН 1022700000001\n"
                "р/с 40702810400000001234 в банке\nк/с 30101810600000000608\n"
                "БИК 040813608\nИНН %s" % (INN, OWN))
        found = requisites.requisites(text, own_inns={OWN})
        self.assertEqual(found["inns"], [INN])
        self.assertEqual(found["kpp"], "270001001")
        self.assertEqual(found["ogrn"], "1022700000001")
        self.assertEqual(found["account"], "40702810400000001234")
        self.assertEqual(found["corr"], "30101810600000000608")
        self.assertEqual(found["bik"], "040813608")

    def test_wrong_check_digit_is_not_inn(self):
        bad = INN[:-1] + str((int(INN[-1]) + 1) % 10)
        self.assertEqual(requisites.requisites("ИНН: %s" % bad)["inns"], [])

    def test_separate_kpp_and_long_account_words(self):
        found = requisites.requisites(
            "ИНН %s КПП: 270101001\nРасчётный счёт № 40702810000000000001" % INN)
        self.assertEqual(found["kpp"], "270101001")
        self.assertEqual(found["account"], "40702810000000000001")

    def test_person_and_position(self):
        self.assertTrue(requisites.looks_like_person("Иванова Мария Петровна"))
        self.assertTrue(requisites.looks_like_person("Петров И.С."))
        self.assertFalse(requisites.looks_like_person("ООО Завод Тест"))
        self.assertFalse(requisites.looks_like_person("Отдел снабжения"))
        self.assertFalse(requisites.looks_like_person("info@example.org"))
        lines = ["С уважением,", "Менеджер отдела снабжения", "Иванова Мария Петровна",
                 "тел. +7 900 000-00-00", "г. Хабаровск, ул. Тестовая 1"]
        self.assertEqual(requisites.person_from_lines(lines), "Иванова Мария Петровна")
        self.assertEqual(requisites.position_from_lines(lines), "Менеджер отдела снабжения")

    def test_company_from_sender(self):
        self.assertEqual(requisites.company_from_sender("ООО Завод Тест"), "ООО Завод Тест")
        self.assertEqual(requisites.company_from_sender("Мария"), "")

    def test_docx_and_xlsx_text(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("word/document.xml",
                             "<w:document><w:p><w:r><w:t>ИНН %s</w:t></w:r></w:p></w:document>" % INN)
        self.assertIn(INN, requisites.attachment_text("Карточка.docx", "", buf.getvalue()))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("xl/sharedStrings.xml", "<sst><si><t>БИК 040813608</t></si></sst>")
        self.assertIn("040813608", requisites.attachment_text("r.xlsx", "", buf.getvalue()))
        self.assertEqual(requisites.attachment_text("scan.jpg", "image/jpeg", b"xx"), "")


if __name__ == "__main__":
    unittest.main()
