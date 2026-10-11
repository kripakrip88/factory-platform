# -*- coding: utf-8 -*-
"""Лид из письма: своя часть письма и телефон из подписи (шаг З-14) —
правила без базы.

Обычный unittest, как test_lead_text_rules.py:

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_signature_rules.py

Письма — по образцу боевых (mail_client_message 58968 Кытмановой, 58468
Метпрома), адреса и тексты сокращены. Прогон по 74 письмам боевой базы с
загруженным текстом 10.10.2026: телефон найден в 47.
"""

import os
import sys
import unittest

try:
    from ..tools import signature
except (ImportError, ValueError):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import signature

KYTMANOVA = (
    "<div>Добрый день! подскажите сможете ли изготовить данные позиции.</div>"
    "<div>&nbsp;</div><div>С уважением,</div><div>Кытманова Мария</div>"
    "<div>ООО ПО «Трубное Решение-Хабаровск»</div>"
    "<div>Тел.: +7&nbsp;(924) 916-84-62</div>"
    "<div>E-mail: <a href=\"mailto:6574@truboproduct.ru\">6574@truboproduct.ru</a></div>"
    "<div>Сайт: https://hab.truboproduct.ru/</div>"
)

# Ответ клиента Mail.ru-шапкой без двоеточия: ниже — наша подпись с нашим
# телефоном, она клиенту не принадлежит.
METPROM = (
    "<div>Добрый день, надо 48шт без гаек.</div><div>С уважением</div>"
    "<div>ООО «Метпром»</div><div>8(4162)42-26-20, 42-22-59</div>"
    "<div>24.09.2026, 15:00, Владимир Голубенко &lt;pmkpark@mail.ru&gt;</div>"
    "<div>Добрый день</div><div>Голубенко Владимир</div>"
    "<div>тел.: +7-933-086-80-70</div>"
)

GMAIL_REPLY = (
    "<div>Цену получили, спасибо.</div><div>Иван, 8-924-111-22-33</div>"
    "<div class=\"gmail_quote\"><div>пн, 5 окт. 2026 г. в 10:00, Завод "
    "&lt;zakaz@pmkpark.ru&gt;:</div><blockquote>Наш тел. +7 (914) 205-50-65"
    "</blockquote></div>"
)

REQUISITES = (
    "<p>Прошу счёт.</p><p>ООО «Ромашка»</p><p>ИНН 7707083893 КПП 770701001</p>"
    "<p>р/с 40702810900000000001 БИК 8 044525225 12-34</p>"
    "<p>Бесплатно: 8-800-555-35-35</p><p>Офис: +7 (4212) 41-00-00</p>"
)


class TestSignature(unittest.TestCase):

    def test_kytmanova(self):
        lines = signature.own_lines(KYTMANOVA, "ПО Трубное решение")
        self.assertEqual(signature.signature_phone(lines), "+7 (924) 916-84-62")
        self.assertIn("Тел.: +7 (924) 916-84-62", lines, "Неразрывный пробел — обычный.")

    def test_own_signature_in_quote_ignored(self):
        lines = signature.own_lines(METPROM, "Re: Заявка на анкерные болты")
        self.assertNotIn("тел.: +7-933-086-80-70", lines)
        self.assertEqual(signature.signature_phone(lines), "8(4162)42-26-20")

    def test_folded_quote_dropped(self):
        lines = signature.own_lines(GMAIL_REPLY, "Re: цена")
        self.assertEqual(signature.signature_phone(lines), "8-924-111-22-33")
        self.assertFalse(any("205-50-65" in line for line in lines))

    def test_own_phone_skipped(self):
        lines = ["Иван", "тел. +7 914 205-50-65"]
        self.assertEqual(signature.signature_phone(lines, ["+7 (914) 205-50-65"]), "")
        self.assertEqual(signature.signature_phone(lines), "+7 914 205-50-65")

    def test_requisites_and_free_numbers(self):
        lines = signature.own_lines(REQUISITES)
        self.assertEqual(signature.signature_phone(lines), "+7 (4212) 41-00-00",
                         "Реквизиты и 8-800 — не телефон подписи.")

    def test_formats(self):
        cases = [
            ("Тел.: +7 (924) 916-84-62", "+7 (924) 916-84-62"),
            ("8-924-916-84-62", "8-924-916-84-62"),
            ("моб. 89249168462", "89249168462"),
            ("+79249168462", "+79249168462"),
            ("8 (914) 162 – 66 – 37", "8 (914) 162 – 66 – 37"),
            ("+7 (914) 7213593", "+7 (914) 7213593"),
            ("т. +7  (924)   001-6621", "+7 (924) 001-6621"),
            ("8 (8422) 44-62-28", "8 (8422) 44-62-28"),
            ("заказ 12345678901", ""),
            ("дата 8.10.2026", ""),
            ("+7 (924) 916-84-6", ""),
        ]
        for line, phone in cases:
            with self.subTest(line=line):
                self.assertEqual(signature.signature_phone([line]), phone)

    def test_mobile_preferred(self):
        lines = ["Офис: +7 (4212) 52-93-57", "Моб.: +7 (924) 916-84-62"]
        self.assertEqual(signature.signature_phone(lines), "+7 (924) 916-84-62")

    def test_only_tail_lines(self):
        lines = ["+7 (924) 916-84-62"] + ["строка %s" % n for n in range(signature.TAIL_LINES)]
        self.assertEqual(signature.signature_phone(lines), "",
                         "Номер в начале длинного письма — не подпись.")

    def test_digits(self):
        self.assertEqual(signature.phone_digits("+7 (924) 916-84-62"), "9249168462")
        self.assertEqual(signature.phone_digits("8-924-916-84-62"), "9249168462")
        self.assertEqual(signature.phone_digits(""), "")

    def test_empty_and_broken(self):
        self.assertEqual(signature.own_lines(""), [])
        self.assertEqual(signature.own_lines(None), [])
        self.assertEqual(signature.signature_phone([]), "")
        self.assertEqual(signature.own_lines("просто текст\n+7 924 916 84 62"),
                         ["просто текст", "+7 924 916 84 62"])

    def test_address_and_date_in_own_text(self):
        """Адрес с датой или часами в своей части письма — не шапка цитаты:
        подпись ниже не отрезается (находка проверки З-14)."""
        body = ("<div>Ответ просим до 15.10.2026 на snab@client-z14.ru</div>"
                "<div>С уважением, Иван</div>"
                "<div>E-mail: 6574@client-z14.ru, пн–пт 9:00–18:00</div>"
                "<div>Тел.: +7 (924) 916-84-62</div><div>ИНН 7707083893</div>")
        lines = signature.own_lines(body, "Заявка")
        self.assertIn("ИНН 7707083893", lines)
        self.assertEqual(signature.signature_phone(lines), "+7 (924) 916-84-62")
        for line in ("Ответ просим до 15.10.2026 на snab@client-z14.ru",
                     "E-mail: 6574@client-z14.ru, пн–пт 9:00–18:00",
                     "Почта snab@client-z14.ru, звонить до 17:00 15.10.2026"):
            with self.subTest(line=line):
                self.assertFalse(signature._is_quote_start(line))

    def test_quote_headers(self):
        for line in ("24.09.2026, 15:00, Владимир Голубенко <pmkpark@mail.ru>",
                     "24.09.2026 15:00, Всеволод Телегин <pmkpark@mail.ru>",
                     "пн, 5 окт. 2026 г. в 10:00, Завод <zakaz@pmkpark.ru>:",
                     "From: Завод <zakaz@pmkpark.ru>",
                     "Кытманова Мария пишет:"):
            with self.subTest(line=line):
                self.assertTrue(signature._is_quote_start(line))

    def test_forward_kept_whole(self):
        body = ("<div>Посмотри</div><div>-------- Пересылаемое сообщение --------</div>"
                "<div>Клиент, +7 (924) 916-84-62</div>")
        lines = signature.own_lines(body, "Fwd: заявка")
        # Строка «Пересылаемое сообщение» — граница своей части: подпись
        # пересылающего коллеги выше неё, клиента — ниже. Пересылку с нашего
        # ящика модель телефоном не разбирает вовсе (_pmk_letter_phone).
        self.assertEqual(lines, ["Посмотри"])


if __name__ == "__main__":
    unittest.main()
