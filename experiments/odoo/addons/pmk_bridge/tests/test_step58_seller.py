# -*- coding: utf-8 -*-
"""Реквизиты продавца и строка налога в КП (разбор UX, шаг 58) — без базы.

Обычный unittest: tools/seller.py — чистые функции, тест гоняется голым
питоном до всякого деплоя:

    python3 experiments/odoo/addons/pmk_bridge/tests/test_step58_seller.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags) — печать
КП с организацией проверяет pmk_org/tests/test_step58_org.py.
"""

import unittest

try:
    from ..tools import seller
except (ImportError, ValueError):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import seller


class TestSeller(unittest.TestCase):

    def test_reg_label_by_type(self):
        self.assertEqual(seller.reg_label("ip"), "ОГРНИП")
        self.assertEqual(seller.reg_label("ooo"), "ОГРН")
        self.assertEqual(seller.reg_label(None), "ОГРН", "Без типа — организация.")

    def test_type_by_inn(self):
        self.assertEqual(seller.org_type_by_inn("272107382162"), "ip", "ИНН ИП Чулкова — 12 цифр.")
        self.assertEqual(seller.org_type_by_inn("2721234567"), "ooo")
        self.assertEqual(seller.org_type_by_inn(""), "ooo")
        self.assertEqual(seller.org_type_by_inn(None), "ooo")

    def test_vat_22_included(self):
        label, amount = seller.tax_line(22, 12200.0)
        self.assertEqual(label, "в том числе НДС 22%:")
        self.assertAlmostEqual(amount, 2200.0, places=6,
                               msg="«В том числе»: 12 200 × 22 / 122, а не сверху.")

    def test_reduced_rates(self):
        self.assertEqual(seller.tax_line(5, 105.0)[0], "в том числе НДС 5%:")
        self.assertAlmostEqual(seller.tax_line(5, 105.0)[1], 5.0)
        self.assertEqual(seller.tax_line(7.0, 107.0)[0], "в том числе НДС 7%:")
        self.assertEqual(seller.tax_line(5.5, 0)[0], "в том числе НДС 5,5%:")

    def test_no_vat(self):
        self.assertEqual(seller.tax_line(0, 1000.0, usn=True), ("Без НДС (УСН)", None))
        self.assertEqual(seller.tax_line(0, 1000.0), ("Без НДС", None))
        self.assertEqual(seller.tax_line(None, None), ("Без НДС", None))

    def test_short_fio(self):
        self.assertEqual(seller.short_fio("Чулков Владислав Витальевич"), "Чулков В. В.")
        self.assertEqual(seller.short_fio("Иванов Пётр"), "Иванов П.")
        self.assertEqual(seller.short_fio("Иванов"), "Иванов")
        self.assertEqual(seller.short_fio(""), "")

    def test_address(self):
        self.assertEqual(seller.address_line(False, "Хабаровск", "ул. Калинина, д. 80"),
                         "Хабаровск, ул. Калинина, д. 80")
        self.assertEqual(seller.address_line("680000, г Хабаровск,\n ул Ленина", "X", "Y"),
                         "680000, г Хабаровск, ул Ленина", "Юридический — первым, одной строкой.")
        self.assertEqual(seller.address_line(None, None, None), "")

    def test_seller_info_sign(self):
        info = seller.seller_info("ООО «Ромашка»", inn="2721234567",
                                  signer_position="Директор", signer_name="Петров Пётр Петрович")
        self.assertEqual(info["reg_label"], "ОГРН")
        self.assertEqual(info["sign_position"], "Директор")
        self.assertEqual(info["sign_name"], "Петров П. П.")
        self.assertIsNone(info["bank"])
        plain = seller.seller_info("ИП Чулков В. В.", inn="272107382162")
        self.assertEqual(plain["reg_label"], "ОГРНИП")
        self.assertEqual(plain["sign_position"], "ИП Чулков В. В.",
                         "Без подписанта — название организации, как до шага 58.")
        self.assertEqual(plain["sign_name"], "")


if __name__ == "__main__":
    unittest.main()
