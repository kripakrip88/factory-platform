# -*- coding: utf-8 -*-
"""Короткие названия организаций (Антон 14.10.2026)."""
from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_dadata.tools.legal_name import ip_full_print_name, short_name


@tagged("post_install", "-at_install")
class TestShortNames(TransactionCase):

    def test_rules(self):
        cases = {
            'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ПРОЦЕСС"': "ООО «ПРОЦЕСС»",
            "Общество с ограниченной ответственностью «Арестак-Строй»": "ООО «Арестак-Строй»",
            "ИП Чулков Владислав Витальевич": "ИП Чулков В.В.",
            "Индивидуальный предприниматель Данилов Кирилл Анатольевич": "ИП Данилов К.А.",
            "ИП ЧУЛКОВ ВЛАДИСЛАВ ВИТАЛЬЕВИЧ": "ИП Чулков В.В.",
            'ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО "СБЕРБАНК РОССИИ"': "ПАО «СБЕРБАНК РОССИИ»",
            'АКЦИОНЕРНОЕ ОБЩЕСТВО "ДВ"': "АО «ДВ»",
            # Не трогаем: уже коротко, человек, слово «общество» не в начале формы.
            "ИП Карнеев А.В.": "ИП Карнеев А.В.",
            "ООО «Арестак-Строй»": "ООО «Арестак-Строй»",
            "Цыганов Михаил Анатольевич": "Цыганов Михаил Анатольевич",
            "Общественная организация": "Общественная организация",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(short_name(name), expected)
        self.assertEqual(ip_full_print_name("Индивидуальный предприниматель Данилов Кирилл Анатольевич"),
                         "ИП Данилов Кирилл Анатольевич")
        self.assertIsNone(ip_full_print_name("ООО «Х»"))

    def test_partner_create_write(self):
        Partner = self.env["res.partner"]
        p = Partner.create({"name": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТЕСТ-КОРОТКО"', "is_company": True})
        self.assertEqual(p.name, "ООО «ТЕСТ-КОРОТКО»")
        self.assertEqual(p.pmk_legal_name, 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТЕСТ-КОРОТКО"')
        # Полное наименование уже есть — не затираем.
        p.write({"name": "Общество с ограниченной ответственностью «Тест-2»"})
        self.assertEqual(p.name, "ООО «Тест-2»")
        self.assertEqual(p.pmk_legal_name, 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТЕСТ-КОРОТКО"')
        ip = Partner.create({"name": "ИП Тестов Иван Петрович", "is_company": True})
        self.assertEqual(ip.name, "ИП Тестов И.П.")
        self.assertEqual(ip.pmk_legal_name, "ИП Тестов Иван Петрович")
        # Человек — как есть; флаг — не сокращать.
        self.assertEqual(Partner.create({"name": "Тестов Иван Петрович"}).name, "Тестов Иван Петрович")
        keep = Partner.with_context(pmk_keep_full_name=True).create({"name": "ИП Тестов Иван Петрович"})
        self.assertEqual(keep.name, "ИП Тестов Иван Петрович")
