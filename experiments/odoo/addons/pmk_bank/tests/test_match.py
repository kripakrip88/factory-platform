# -*- coding: utf-8 -*-
"""Разбор назначения и выбор счёта — на живых платежах Модульбанка (08–13.10.2026)."""
from datetime import date

from odoo.tests import BaseCase, tagged

from ..tools import match
from ..tools import message


@tagged("post_install", "-at_install")
class TestMatch(BaseCase):

    def test_invoice_numbers_live_purposes(self):
        cases = {
            "ОПЛАТА ПО СЧЕТУ 01183 ОТ 09.10.2026 ЗА СНЕГОЗАДЕРЖАТЕЛЬ НА СУММУ 11500": ["1183"],
            "МСП Оплата 70% поставки габтонных констр. по счету№01155 от 06.10.2026": ["1155"],
            "Оплата по счету № 01166 от 07.10.2026 за грнутый швеллер": ["1166"],
            "ОПЛАТА ПО СЧ 987 ОТ 24.08.2026Г. ЗА ДОБОРНЫЙ ЭЛ.": ["987"],
            "Оплата счета № 01113 от 24.09.2026 г. за лазерную резку": ["1113"],
            "Оплата по сч. 1200 и сч.1201": ["1200", "1201"],
            # ловушки: «расчёт» содержит «счёт», сумма без «счёт» — не номер
            "Оплата по расчету 555 за металл": [],
            "Перевод между счетами. Без НДС": [],
        }
        for purpose, expected in cases.items():
            self.assertEqual(match.invoice_numbers(purpose), expected, purpose)

    def test_invoice_date(self):
        self.assertEqual(match.invoice_date("по счету № 01166 от 07.10.2026 за"), date(2026, 10, 7))
        self.assertIsNone(match.invoice_date("без даты"))

    def test_choose_by_inn_then_amount(self):
        # «01183» этого года и «001183» прошлого — у разных клиентов
        c = [{"id": 1, "inn": "2502075437", "amount": 11500, "date": date(2026, 10, 8)},
             {"id": 2, "inn": "2700000000", "amount": 1320, "date": date(2025, 3, 1)}]
        self.assertEqual(match.choose_invoice(c, "2502075437", 11500)["id"], 1)
        self.assertIsNone(match.choose_invoice(c, "9999999999", 11500))   # чужой ИНН — не подставляем

    def test_partial_prepayment_still_matches(self):
        c = [{"id": 7, "inn": "2724132118", "amount": 7580951.64, "date": date(2026, 10, 6)}]
        self.assertEqual(match.choose_invoice(c, "2724132118", 5306666.14)["id"], 7)
        self.assertIn("70%", match.paid_status(7580951.64, 5306666.14))

    def test_money(self):
        self.assertEqual(match.money(11500), "11\u00a0500\u00a0₽")
        self.assertEqual(match.money(29509.6), "29\u00a0509,60\u00a0₽")

    def test_what_for_live_purposes(self):
        cases = {
            "ОПЛАТА ПО СЧЕТУ 01183 ОТ 09.10.2026 ЗА СНЕГОЗАДЕРЖАТЕЛЬ НА СУММУ 11500, В Т.Ч. НДС": "снегозадержатель",
            "Оплата по счету № 01166 от 07.10.2026 за грнутый швеллер 28*85*28*2 - 40800-00, в т.ч. НДС":
                "грнутый швеллер 28*85*28*2",
            "Оплата по счету № 01177 от 08.10.2026 за ТМЦ 29509-60 руб. В т.ч. НДС 22%": "ТМЦ",
            "Оплата счета № 01113 от 24.09.2026 г. за лазерную резку. В том числе НДС": "лазерную резку",
            "МСП Оплата 70% поставки по счету№01155 от 06.10.2026": "",
        }
        for purpose, expected in cases.items():
            self.assertEqual(message.what_for(purpose), expected, purpose)

    def test_org_short(self):
        self.assertEqual(message.org_short("ИП Бутов Игорь Евгеньевич"), "ИП Бутов")
        self.assertEqual(message.org_short("ООО «Ромашка»"), "ООО «Ромашка»")
