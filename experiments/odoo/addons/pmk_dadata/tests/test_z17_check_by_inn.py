# -*- coding: utf-8 -*-
"""«Сверить по ИНН» — разбор UX, шаг З-17 (11.10.2026).

В DaData тест не ходит: _pmk_dadata_find подменён ответом справочника.
Ловим:
  • в строке ИНН видна ровно одна кнопка: «Заполнить» у пустой карточки,
    «Сверить» у заполненной;
  • «Сверить» ничего не пишет: открывает окно со строками различий
    (Название — без отметки «Заменить», пустое в выписке не предлагается к
    очистке; код ФИАС, индекс, город, улица — без строк, их на карточке нет);
  • свой КПП у карточки (филиал) — строка КПП не отмечена, подпись «у
    филиала свой»; пустой КПП — отмечен;
  • «Применить» пишет только отмеченное и оставляет заметку в ленте; с
    юридическим адресом молча — код ФИАС и пустые индекс, город, улица;
  • совпадает всё — уведомление, окна нет, карточка не тронута;
  • не действует по ЕГРЮЛ — плашка словами (красная / жёлтая);
  • «Заполнить по ИНН» после выноса разбора — как прежде.
"""
from unittest.mock import patch

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.pmk_dadata.models.res_partner import ResPartner

INN = "7717625418"


def answer(status="ACTIVE", kpp="771701001", city="Москва"):
    return {
        "name": {"short_with_opf": "ООО «А ГРУПП МАРКЕТ»",
                 "full_with_opf": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «А ГРУПП МАРКЕТ»"},
        "kpp": kpp, "ogrn": "1087746871513", "okpo": "",
        "address": {"value": "г Москва, ул Годовикова, д 9 стр 17",
                    "data": {"postal_code": "129085", "city": city,
                             "street_with_type": "ул Годовикова", "house_with_type": "д 9",
                             "fias_id": "f-z17"}},
        "state": {"status": status},
    }


@tagged("post_install", "-at_install")
class TestZ17CheckByInn(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].with_context(no_vat_validation=True).create({
            "name": "А ГРУПП", "is_company": True, "vat": INN,
            "kpp": "770101001", "okpo": "12345678", "city": "Хабаровск",
        })

    def _check(self, data=None):
        with patch.object(ResPartner, "_pmk_dadata_find", return_value=data or answer()):
            return self.partner.action_pmk_check_by_inn()

    def test_one_button_in_row(self):
        view = self.env.ref("base.view_partner_form")
        arch = self.env["res.partner"].get_views([(view.id, "form")])["views"]["form"]["arch"]
        root = etree.fromstring(arch)
        fill = root.xpath("//button[@name='action_pmk_fill_by_inn']")[0].get("invisible")
        check = root.xpath("//button[@name='action_pmk_check_by_inn']")[0].get("invisible")
        for values in ({"pmk_legal_name": False, "kpp": False, "ogrn": False},
                       {"pmk_legal_name": False, "kpp": "770101001", "ogrn": False},
                       {"pmk_legal_name": "ООО", "kpp": False, "ogrn": False}):
            with self.subTest(values=values):
                shown = [not safe_eval(fill, values), not safe_eval(check, values)]
                self.assertEqual(shown.count(True), 1, "Видна одна кнопка.")
        self.assertFalse(safe_eval(fill, {"pmk_legal_name": False, "kpp": False, "ogrn": False}),
                         "У пустой карточки — «Заполнить».")

    def test_check_shows_and_does_not_write(self):
        action = self._check()
        self.assertEqual(action["res_model"], "pmk.dadata.check")
        self.assertEqual(self.partner.kpp, "770101001", "До «Применить» ничего не меняется.")
        self.assertEqual(self.partner.name, "А ГРУПП")
        check = self.env["pmk.dadata.check"].browse(action["res_id"])
        lines = {line.field_name: line for line in check.line_ids}
        self.assertFalse(lines["name"].apply, "Название по умолчанию не заменяется.")
        self.assertFalse(lines["kpp"].apply,
                         "Свой КПП у карточки (филиал?) — по умолчанию не заменяется.")
        self.assertIn("филиала", lines["kpp"].label)
        self.assertEqual((lines["kpp"].current, lines["kpp"].new), ("770101001", "771701001"))
        self.assertTrue(lines["pmk_legal_address"].apply)
        self.assertNotIn("okpo", lines, "Пустое в выписке не предлагается к очистке.")
        for name in ("fias_id", "zip", "city", "street"):
            self.assertNotIn(name, lines, "Полей нет на карточке — строкой не показываем.")
        self.assertFalse(check.status_level, "Действующая — без плашки.")

    def test_empty_kpp_marked(self):
        self.partner.kpp = False
        check = self.env["pmk.dadata.check"].browse(self._check()["res_id"])
        line = check.line_ids.filtered(lambda item: item.field_name == "kpp")
        self.assertTrue(line.apply, "Пустой КПП — заполнить по выписке.")
        self.assertEqual(line.label, "КПП")

    def test_apply_only_marked(self):
        check = self.env["pmk.dadata.check"].browse(self._check()["res_id"])
        check.line_ids.filtered(lambda line: line.field_name == "ogrn").apply = False
        check.line_ids.filtered(lambda line: line.field_name == "kpp").apply = True
        before = len(self.partner.message_ids)
        result = check.action_apply()
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(self.partner.kpp, "771701001", "Отметили руками — заменён.")
        self.assertFalse(self.partner.ogrn, "Снятая отметка — поле не тронуто.")
        self.assertEqual(self.partner.name, "А ГРУПП", "Название не отмечено.")
        self.assertEqual(self.partner.pmk_legal_address, "г Москва, ул Годовикова, д 9 стр 17")
        self.assertEqual(self.partner.city, "Хабаровск", "Заполненный город не тронут.")
        self.assertEqual(self.partner.street, "ул Годовикова д 9",
                         "Пустая улица — молча вместе с юридическим адресом.")
        self.assertEqual(self.partner.zip, "129085")
        if "fias_id" in self.partner._fields:
            self.assertEqual(self.partner.fias_id, "f-z17")
        self.assertGreater(len(self.partner.message_ids), before)
        self.assertIn("Сверено по ИНН", self.partner.message_ids[0].body)
        self.assertIn("КПП", self.partner.message_ids[0].body)
        self.assertIn("улица", self.partner.message_ids[0].body)

    def test_address_parts_only_with_legal_address(self):
        check = self.env["pmk.dadata.check"].browse(self._check()["res_id"])
        check.line_ids.filtered(lambda line: line.field_name == "pmk_legal_address").apply = False
        check.action_apply()
        self.assertFalse(self.partner.street, "Адрес не отмечен — разложенный тоже не пишется.")

    def test_nothing_to_change(self):
        self.partner.write({
            "name": "ООО «А ГРУПП МАРКЕТ»",
            "pmk_legal_name": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «А ГРУПП МАРКЕТ»",
            "kpp": "771701001", "ogrn": "1087746871513",
            "pmk_legal_address": "г Москва, ул Годовикова, д 9 стр 17",
            "pmk_dadata_status": "Действующая", "zip": "129085", "street": "ул Годовикова д 9",
        })
        if "fias_id" in self.partner._fields:
            self.partner.fias_id = "f-z17"
        count = self.env["pmk.dadata.check"].search_count([])
        action = self._check()
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["title"], "Реквизиты совпадают с ЕГРЮЛ")
        self.assertEqual(self.env["pmk.dadata.check"].search_count([]), count, "Окна нет.")

    def test_status_plaque(self):
        check = self.env["pmk.dadata.check"].browse(self._check(answer(status="LIQUIDATED"))["res_id"])
        self.assertEqual(check.status_level, "danger")
        self.assertIn("Ликвидирована", check.status_warn, "Цвет повторён словом.")
        check = self.env["pmk.dadata.check"].browse(self._check(answer(status="REORGANIZING"))["res_id"])
        self.assertEqual(check.status_level, "warning")
        self.assertIn("реорганизации", check.status_warn)

    def test_fill_unchanged(self):
        empty = self.env["res.partner"].with_context(no_vat_validation=True).create({
            "name": INN, "is_company": True, "vat": INN})
        with patch.object(ResPartner, "_pmk_dadata_find", return_value=answer()):
            empty.action_pmk_fill_by_inn()
        self.assertEqual(empty.name, "ООО «А ГРУПП МАРКЕТ»", "Имя-ИНН заменено коротким.")
        self.assertEqual(empty.kpp, "771701001")
        self.assertEqual(empty.city, "Москва")
        self.assertEqual(empty.street, "ул Годовикова д 9")
        self.assertEqual(empty.pmk_dadata_status, "Действующая")
        self.assertFalse(empty.okpo, "Пустое в выписке — не пишется.")
