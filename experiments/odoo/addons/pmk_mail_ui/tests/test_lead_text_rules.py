# -*- coding: utf-8 -*-
"""Лид из письма: название и адрес (разбор UX, шаг 27) — правила без базы.

Обычный unittest, как test_quote_rules.py: tools/lead_text.py — чистые
функции, тесты гоняются голым питоном до всякого деплоя:

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_lead_text_rules.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags), поэтому
те же таблицы через модель и миграцию прогоняет test_lead_from_letter.py.

LIVE_LEADS — все 13 лидов боевой базы на 02.10.2026 (SELECT по crm_lead,
type = 'lead'; архивные тоже): название, «Эл. почта», «Имя контакта» — и что
с ними сделает миграция 19.0.1.0.6.
"""

import os
import sys
import unittest

try:
    # Внутри Odoo — как odoo.addons.pmk_mail_ui.tools.lead_text.
    from ..tools import lead_text
except (ImportError, ValueError):
    # Голым питоном — как соседний пакет.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import lead_text

OWN = {"pmkpark@mail.ru", "zakaz@pmkpark.ru"}

# (тема письма, ожидаемое название лида)
SUBJECTS = [
    ("RE: запрос МЦ СИЗ и САС", "Запрос МЦ СИЗ и САС"),
    ("Re: Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
     "Запрос актуального прайс-листа — ПМК Парк, Хабаровск"),
    ("FW: Заявка на закладные детали фундаментов стоек изм2",
     "Заявка на закладные детали фундаментов стоек изм2"),
    ("Fwd: Re: Cчет Сч-0015114 от 16.06.26", "Cчет Сч-0015114 от 16.06.26"),
    # Сокращение строчными (короче четырёх букв) и имя со смешанным
    # регистром — как написаны: ММК, СПК, КП не превращаются в «Ммк», «Спк»,
    # «Кп», а «iPhone» — в «IPhone».
    ("Fwd: RE: ммк", "ммк"),
    ("RE: спк трубы", "спк трубы"),
    ("Fwd: кп на лист 4 мм", "кп на лист 4 мм"),
    ("re: iPhone", "iPhone"),
    ("Re: eBay заказ", "eBay заказ"),
    ("RE: ММК", "ММК"),
    # Короткое обычное слово тоже как написано — не искажение, а цена правила.
    ("Re: акт сверки", "акт сверки"),
    # Обычное слово — с заглавной, в том числе через дефис и с запятой.
    ("Re: прайс-лист", "Прайс-лист"),
    ("Fwd: заказ, срочно", "Заказ, срочно"),
    (": заказ", "Заказ"),
    ("Re[2]: прайс на лист", "Прайс на лист"),
    ("Re(3): прайс", "Прайс"),
    ("Отв: Пересл.: прайс", "Прайс"),
    ("ОТВЕТ: счёт", "Счёт"),
    ("AW: WG: Angebot", "Angebot"),
    ("TR: devis", "Devis"),
    ("Fwd : лист 4 мм", "Лист 4 мм"),
    ("re:прайс", "Прайс"),
    (": RE: заказ", "Заказ"),
    ("— заказ", "Заказ"),
    ("  Re:   Заявка  ", "Заявка"),
    # Ничего не осталось — решает вызывающий («Без темы»).
    ("RE:", ""),
    ("Re: Fwd:", ""),
    ("", ""),
    (None, ""),
    # Не приставки — без изменений.
    ("Трубы: прайс", "Трубы: прайс"),
    ("Заявка: лист", "Заявка: лист"),
    ("Ответ по запросу на почту contact@mc.ru", "Ответ по запросу на почту contact@mc.ru"),
    ("прайс листы СПК", "прайс листы СПК"),
    ("Retail: склад", "Retail: склад"),
    ("Резка: лист", "Резка: лист"),
    ("-10% на лист", "-10% на лист"),
    ("Заявка Листы гладкие окрашенные", "Заявка Листы гладкие окрашенные"),
]

# (отправитель письма, ожидаемые имя и адрес)
SENDERS = [
    ('"Владимир Голубенко" <pmkpark@mail.ru>', ("Владимир Голубенко", "pmkpark@mail.ru")),
    ("Михаил Цыганов <tsyganovma@arestakstroy.ru>",
     ("Михаил Цыганов", "tsyganovma@arestakstroy.ru")),
    ("vld12@bvbmail.ru <vld12@bvbmail.ru>", ("", "vld12@bvbmail.ru")),
    ("u.pyankova@uess.ru", ("", "u.pyankova@uess.ru")),
    ('"Иванов, Иван" <ivan@x.ru>', ("Иванов, Иван", "ivan@x.ru")),
    ("Иванов, Иван <ivan@x.ru>", ("Иванов, Иван", "ivan@x.ru")),
    ("<a@b.ru>", ("", "a@b.ru")),
    ("'Оксана' <oksana@cks1.ru>", ("Оксана", "oksana@cks1.ru")),
    ("«МеталлСити» <555metal555@bk.ru>", ("МеталлСити", "555metal555@bk.ru")),
    ("A <a@x.ru>, B <b@y.ru>", ("A", "a@x.ru")),
    ('"123" <num@x.ru>', ("", "num@x.ru")),
    ("=?UTF-8?B?0JjQstCw0L0=?= <x@y.ru>", ("", "x@y.ru")),
    ("Name.With.Dots <Name.With.Dots@Example.RU>", ("Name.With.Dots", "Name.With.Dots@Example.RU")),
    ("без адреса", ("", "")),
    ("", ("", "")),
    (None, ("", "")),
]

# Боевая база, 02.10.2026: (id, активен, название, «Эл. почта», «Имя контакта»)
# → что поправит миграция 19.0.1.0.6. Контакта-человека нет ни у одного лида.
LIVE_LEADS = [
    (5, False, "Fwd: RE: ммк", '"Владимир Голубенко" <pmkpark@mail.ru>', "",
     {"name": "ммк", "email_from": "pmkpark@mail.ru"}),
    (6, False, "RE: Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
     '"Киселёв Николай Сергеев ич" <kiselev.ns@mmk.ru>', "",
     {"name": "Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
      "email_from": "kiselev.ns@mmk.ru", "contact_name": "Киселёв Николай Сергеев ич"}),
    (7, False, "прайс листы СПК", '"Александрова Анна Никол аевна" <minogina@spk.ru>', "",
     {"email_from": "minogina@spk.ru", "contact_name": "Александрова Анна Никол аевна"}),
    (8, False, "Re: Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
     '"МеталлСити" <555metal555@bk.ru>', "",
     {"name": "Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
      "email_from": "555metal555@bk.ru", "contact_name": "МеталлСити"}),
    (9, False, "Ответ по запросу на почту contact@mc.ru",
     '"Пронина Юлия Васильевна" <9251155.100@mc.ru>', "",
     {"email_from": "9251155.100@mc.ru", "contact_name": "Пронина Юлия Васильевна"}),
    (10, False, "Re: Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
     '"Кутилов Эдуард Андрееви ч" <kutilov.ea@mc.ru>', "",
     {"name": "Запрос актуального прайс-листа — ПМК Парк, Хабаровск",
      "email_from": "kutilov.ea@mc.ru", "contact_name": "Кутилов Эдуард Андрееви ч"}),
    (11, False, "Заполняем документы перевозки- правила, риски, ответственность.",
     '"Марта Тупорылова" <contact@pobedada.ru>', "",
     {"email_from": "contact@pobedada.ru", "contact_name": "Марта Тупорылова"}),
    (14, True, "Запрос МЦ СИЗ и САС", "kuznetsov.a@technoavia.ru",
     "Кузнецов Алексей Владимирович", {}),
    (15, True, ": заказ", "Оксана <oksana@cks1.ru>", "",
     {"name": "Заказ", "email_from": "oksana@cks1.ru", "contact_name": "Оксана"}),
    (16, True, "Заявка на стремянку", "Дмитрий Филиппов <filippovda@dyappe.ru>", "",
     {"email_from": "filippovda@dyappe.ru", "contact_name": "Дмитрий Филиппов"}),
    (17, True, "FW: Заявка на закладные детали фундаментов стоек изм2", "u.pyankova@uess.ru", "",
     {"name": "Заявка на закладные детали фундаментов стоек изм2"}),
    (18, True, "Расчет забор", "Александр Мичурин <sana.michurin@gmail.com>", "",
     {"email_from": "sana.michurin@gmail.com", "contact_name": "Александр Мичурин"}),
    (19, True, "Заявка Листы гладкие окрашенные", "vld12@bvbmail.ru <vld12@bvbmail.ru>", "",
     {"email_from": "vld12@bvbmail.ru"}),
]


class TestLeadTextRules(unittest.TestCase):

    def test_clean_subject(self):
        for subject, expected in SUBJECTS:
            with self.subTest(subject=subject):
                self.assertEqual(lead_text.clean_subject(subject), expected)

    def test_clean_subject_idempotent(self):
        for subject, expected in SUBJECTS:
            with self.subTest(subject=subject):
                self.assertEqual(lead_text.clean_subject(expected), expected)

    def test_split_sender(self):
        for text, expected in SENDERS:
            with self.subTest(sender=text):
                self.assertEqual(lead_text.split_sender(text), expected)

    def test_contact_name_not_from_own_mailbox(self):
        self.assertEqual(lead_text.contact_name("Владимир Голубенко", "pmkpark@mail.ru", OWN), "")
        self.assertEqual(lead_text.contact_name("Владимир Голубенко", "PMKPARK@mail.ru ", OWN), "")
        self.assertEqual(lead_text.contact_name("Оксана", "oksana@cks1.ru", OWN), "Оксана")
        self.assertEqual(lead_text.contact_name("", "oksana@cks1.ru", OWN), "")
        self.assertEqual(lead_text.contact_name("Оксана", "oksana@cks1.ru"), "Оксана")

    def test_live_leads_migration(self):
        for lead_id, _active, name, email, contact, expected in LIVE_LEADS:
            with self.subTest(lead=lead_id):
                values = lead_text.cleanup_values(name, email, contact, False, OWN)
                self.assertEqual(values, expected)
                # Повторный проход по исправленному — ничего.
                fixed = {"name": name, "email_from": email, "contact_name": contact}
                fixed.update(values)
                self.assertEqual(lead_text.cleanup_values(
                    fixed["name"], fixed["email_from"], fixed["contact_name"], False, OWN), {})

    def test_person_keeps_core_name(self):
        """Контакт-человек есть — имя ставит ядро из контакта, не мы."""
        values = lead_text.cleanup_values("Re: заявка", "Оксана <oksana@cks1.ru>", "", True, OWN)
        self.assertEqual(values, {"name": "Заявка", "email_from": "oksana@cks1.ru"})

    def test_filled_contact_kept(self):
        values = lead_text.cleanup_values("Заявка", "Оксана <oksana@cks1.ru>", "Оксана Петрова", False, OWN)
        self.assertEqual(values, {"email_from": "oksana@cks1.ru"})

    def test_better_spelling_from_letters(self):
        """Имя с лишним пробелом (алиас ядра) — написание из писем «Почты»;
        другое имя или имя с пробелами вместо слитного — не трогаем."""
        letters = ["Киселёв Николай Сергеевич"]
        self.assertEqual(lead_text.better_spelling("Киселёв Николай Сергеев ич", letters),
                         "Киселёв Николай Сергеевич")
        self.assertEqual(lead_text.better_spelling("Александрова Анна Никол аевна",
                                                   ["", "Александрова Анна Николаевна"]),
                         "Александрова Анна Николаевна")
        self.assertEqual(lead_text.better_spelling("МеталлСити", ["МеталлСити"]), "МеталлСити")
        self.assertEqual(lead_text.better_spelling("Киселёв Николай", ["Киселёв Н. С."]),
                         "Киселёв Николай")
        # Пробел перед заглавной — граница слов, а не изъян: слитное
        # написание из письма не берём.
        self.assertEqual(lead_text.better_spelling("Иван Петров", ["ИванПетров"]), "Иван Петров")
        self.assertEqual(lead_text.better_spelling("ИванПетров", ["Иван Петров"]), "ИванПетров",
                         "В письме пробелов больше — не берём.")
        # Два изъяна сразу и пробел в другом месте.
        self.assertEqual(lead_text.better_spelling("Кутилов Эдуард Андрееви ч",
                                                   ["Кутилов Эдуард Андреевич"]),
                         "Кутилов Эдуард Андреевич")
        self.assertEqual(lead_text.better_spelling("Ки селёв Ни колай", ["Киселёв Николай"]),
                         "Киселёв Николай")
        self.assertEqual(lead_text.better_spelling("Сергеев ич", ["Сер геевич"]), "Сергеев ич",
                         "Пробел письма не из наших — не то же написание.")
        self.assertEqual(lead_text.better_spelling("", letters), "")
        self.assertEqual(lead_text.better_spelling("Оксана", []), "Оксана")
        self.assertEqual(lead_text.better_spelling("Оксана", None), "Оксана")

    def test_empty_subject_kept(self):
        """«RE:» целиком — название не трогаем (новый лид из такого письма
        получит «Без темы»; здесь — уже живой лид)."""
        self.assertEqual(lead_text.cleanup_values("RE:", "a@b.ru", "", False, OWN), {})


if __name__ == "__main__":
    unittest.main()
