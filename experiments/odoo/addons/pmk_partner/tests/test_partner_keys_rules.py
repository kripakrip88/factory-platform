# -*- coding: utf-8 -*-
"""Клиент из письма: домен, ИНН, ключ названия, группы дублей (шаг З-14) —
правила без базы.

Обычный unittest, как в pmk_mail_ui: tools/partner_keys.py — чистые
функции, тесты гоняются голым питоном до всякой выкладки:

    python3 experiments/odoo/addons/pmk_partner/tests/test_partner_keys_rules.py

Через модель те же правила проверяет test_z14_client_match.py.
Названия и адреса — с боевой базы 10.10.2026 (SELECT по res_partner).
"""

import os
import sys
import unittest

try:
    from ..tools import partner_keys
except (ImportError, ValueError):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import partner_keys

# (название, ключ) — пары дублей из переноса таблицы заказов 08.10 и реестра.
NAMES = [
    ("ООО ПО «Трубное решение», филиал Хабаровск", "трубное решение"),
    ("ТРУБНОЕ РЕШЕНИЕ", "трубное решение"),
    ('ООО "МЕРИДИАН"', "меридиан"),
    ("МЕРИДИАН", "меридиан"),
    ('ООО "БСМ-МОСТ"', "бсм мост"),
    ("БСМ-МОСТ", "бсм мост"),
    ('ООО "ПК "ПРОФНАСТИЛ-ДВ"', "профнастил дв"),
    ("ПРОФНАСТИЛ-ДВ (дилерский центр, юрлицо на сайте не указано)", "профнастил дв"),
    ("АО «Металлсервис», филиал Хабаровск", "металлсервис"),
    ("АО «МЕТАЛЛСЕРВИС»", "металлсервис"),
    ("АНЭП-Металл (филиал Хабаровск)", "анэп металл"),
    ("АНЭП-Металл, Хабаровск", "анэп металл"),
    ("Общество с ограниченной ответственностью «Ёлка»", "елка"),
    ("ИП Чулков Владислав Витальевич", "чулков владислав витальевич"),
    ('"СБ-СИГМА"', "сб сигма"),
    ("КАРЬЕР - СЕРВИС", "карьер сервис"),
    ("ООО", ""),
    ("", ""),
]


class TestPartnerKeys(unittest.TestCase):

    def test_name_key(self):
        for name, key in NAMES:
            with self.subTest(name=name):
                self.assertEqual(partner_keys.name_key(name), key)

    def test_name_key_keeps_different_names(self):
        self.assertNotEqual(partner_keys.name_key("ООО ПО «Трубное Решение-Хабаровск»"),
                            partner_keys.name_key("ТРУБНОЕ РЕШЕНИЕ"),
                            "Другое название — другая компания: не склеиваем.")
        self.assertNotEqual(partner_keys.name_key("ООО «СПК»"),
                            partner_keys.name_key("ООО «СПК-Металл»"))

    def test_domains(self):
        self.assertEqual(partner_keys.email_domain("6574@truboproduct.ru"), "truboproduct.ru")
        self.assertEqual(partner_keys.email_domain("Кытманова <6574@TruboProduct.ru>"),
                         "truboproduct.ru")
        self.assertEqual(partner_keys.email_domain("dmk@mail.redcom.ru"), "redcom.ru")
        self.assertEqual(partner_keys.email_domain("a@shop.com.ru"), "shop.com.ru")
        self.assertEqual(partner_keys.email_domain("без адреса"), "")
        self.assertEqual(partner_keys.site_domain("https://hab.truboproduct.ru/"), "truboproduct.ru")
        self.assertEqual(partner_keys.site_domain("www.mc.ru/catalog?x=1"), "mc.ru")
        self.assertEqual(partner_keys.site_domain("http://user@mc.ru:8080/"), "mc.ru")
        self.assertEqual(partner_keys.site_domain("mc.ru, spk.ru"), "mc.ru")
        self.assertEqual(partner_keys.site_domain("нет сайта"), "")
        self.assertEqual(partner_keys.site_domain(""), "")
        self.assertEqual(partner_keys.email_domains("a@x.ru; b@sub.y.ru"), {"x.ru", "y.ru"})

    def test_public_domains(self):
        public = partner_keys.public_domains()
        for domain in ("mail.ru", "gmail.com", "yandex.ru", "bk.ru", "list.ru", "inbox.ru",
                       "rambler.ru", "icloud.com", "ya.ru", "redcom.ru"):
            with self.subTest(domain=domain):
                self.assertIn(domain, public)
        self.assertNotIn("truboproduct.ru", public)
        added = partner_keys.public_domains("Example.org, khv.example ;  ")
        self.assertIn("example.org", added)
        self.assertIn("khv.example", added)

    def test_inn(self):
        for inn in ("7717625418", "272107382162", "7707083893", "500100732259"):
            with self.subTest(inn=inn):
                self.assertTrue(partner_keys.inn_valid(inn))
        for bad in ("7717625419", "0000000000", "12345", "77176254180", "", None, "77176-25418"):
            with self.subTest(bad=bad):
                self.assertFalse(partner_keys.inn_valid(bad))
        self.assertEqual(partner_keys.inn_of("RU7717625418"), "7717625418")
        self.assertEqual(partner_keys.inn_of("7717 625 418"), "7717625418")
        self.assertEqual(partner_keys.inn_of("DE123456789"), "")

    def test_inns_in_text(self):
        text = ("ООО «Ромашка»\nИНН/КПП 7717625418/771701001\nИНН: 7717625419 (опечатка)\n"
                "ИНН №272107382162; повтор ИНН 7717625418; без слова 7707083893")
        self.assertEqual(partner_keys.inns_in(text), ["7717625418", "272107382162"])
        self.assertEqual(partner_keys.inns_in(""), [])
        self.assertEqual(partner_keys.inns_in(None), [])

    def test_duplicate_groups(self):
        rows = [
            {"id": 18, "name": "трубное решение", "inn": "", "domains": {"truboproduct.ru"}},
            {"id": 159, "name": "трубное решение", "inn": "", "domains": set()},
            {"id": 6, "name": "металлсервис хабаровск", "inn": "", "domains": {"mc.ru"}},
            {"id": 19, "name": "металлсервис", "inn": "", "domains": {"mc.ru"}},
            {"id": 47, "name": "металлсервис", "inn": "", "domains": {"mc.ru"}},
            {"id": 200, "name": "альфа", "inn": "7717625418", "domains": set()},
            {"id": 201, "name": "бета", "inn": "7717625418", "domains": set()},
            {"id": 300, "name": "одиночка", "inn": "", "domains": {"alone.ru"}},
        ]
        groups = partner_keys.duplicate_groups(rows)
        self.assertEqual([label for label, _lines in groups],
                         ["металлсервис", "трубное решение", "ИНН 7717625418"])
        by_label = dict(groups)
        self.assertEqual(by_label["трубное решение"], [(18, "Название"), (159, "Название")])
        self.assertEqual(by_label["металлсервис"],
                         [(6, "Домен mc.ru"), (19, "Название, Домен mc.ru"),
                          (47, "Название, Домен mc.ru")],
                         "6 сцеплена с группой через домен — одна группа, не две.")
        self.assertEqual(by_label["ИНН 7717625418"], [(200, "ИНН 7717625418"),
                                                      (201, "ИНН 7717625418")])
        self.assertNotIn(300, [pid for _label, lines in groups for pid, _r in lines])


if __name__ == "__main__":
    unittest.main()
