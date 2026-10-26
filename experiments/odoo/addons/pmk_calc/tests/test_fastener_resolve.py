# -*- coding: utf-8 -*-
"""Метиз по записи инженера — класс и покрытие (26.10.2026)."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFastenerResolve(TransactionCase):

    def _r(self, text):
        return self.env["pmk.metal.fastener"]._pmk_resolve(text)

    def ref(self, xmlid):
        return self.env.ref("pmk_calc.%s" % xmlid)

    def test_bolt_class_and_coating(self):
        self.assertEqual(self._r("Болт М20×60 кл. 8.8"), self.ref("fast2_bolt_20_60_88_black"))
        self.assertEqual(self._r("болт м20х60 8.8 цинк"), self.ref("fast2_bolt_20_60_88_zinc"))
        self.assertEqual(self._r("Болт М20×60 полная резьба кл. 5.8 цинк"), self.ref("fast2_bolt_20_60_58_zinc_full"))
        self.assertFalse(self._r("Болт М20×60"), "класс не указан — цену 5.8 за 10.9 не выдаём")
        self.assertFalse(self._r("болт М16х1,5х50 8.8"), "мелкого шага в справочнике нет")

    def test_nut_washer_screw(self):
        self.assertEqual(self._r("Гайка М20"), self.ref("fast2_nut_20_black"), "без класса — обычная ГОСТ 5915")
        self.assertEqual(self._r("Гайка М20 кл. 10 цинк"), self.ref("fast2_nut_20_10_zinc"))
        self.assertEqual(self._r("Шайба М20"), self.ref("fast2_washer_20_black"))
        self.assertEqual(self._r("Шайба М20 гровер оц"), self.ref("fast2_washer_spring_20_zinc"))
        self.assertEqual(self._r("Саморез кровельный 5,5х19 RAL 8017"), self.ref("fast2_screw_5_5_19_painted"))
        self.assertEqual(self._r("саморез 5,5х19"), self.ref("fast2_screw_5_5_19_zinc"))

    def test_old_positions_archived(self):
        old = self.ref("fast_bolt_m20_60")
        self.assertFalse(old.active, "старые без класса — в архиве, строки расчётов на них остаются")
        self.assertTrue(self.ref("fast_anchor_m10_100").active)
        self.assertEqual(self._r("Анкер клиновой М10×100"), self.ref("fast_anchor_m10_100"))
