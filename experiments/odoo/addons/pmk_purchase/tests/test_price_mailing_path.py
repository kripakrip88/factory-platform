# -*- coding: utf-8 -*-
"""«Рассылка прайсов» — адрес-слово price-mailing (разбор UX, шаг 23).

Серверное действие возвращает окно без номера, поэтому без path в адресе
не было действия вовсе (/odoo/pmk.price.mailing/1): пункт не подсвечивался
в строке разделов, строка пути не восстанавливалась. С path ядро передаёт
его окну, а пункт меню получает actionPath — по нему и горит подсветка
(pmk_theme/static/src/js/active_section_keys.js).
"""
from odoo import Command
from odoo.tests import TransactionCase, tagged

PATH = "price-mailing"


@tagged("post_install", "-at_install")
class TestPriceMailingPath(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.action = cls.env.ref("pmk_purchase.action_price_mailing")
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("purchase.group_purchase_manager").id),
        ]})

    def test_action_has_unique_path(self):
        self.assertEqual(self.action.path, PATH)
        found = self.env["ir.actions.actions"].search([("path", "=", PATH)])
        self.assertEqual(found.ids, [self.action.id])

    def test_menu_carries_action_path(self):
        menu = self.env.ref("pmk_purchase.menu_price_mailing")
        menus = self.env["ir.ui.menu"].with_user(self.admin).load_web_menus(False)
        self.assertIn(menu.id, menus, "Пункт «Рассылка прайсов» должен быть виден.")
        self.assertEqual(menus[menu.id]["actionPath"], PATH)
        self.assertEqual(menus[menu.id]["actionID"], self.action.id)

    def test_window_has_no_id_path_is_needed(self):
        """Окно без номера — поэтому подсветке и адресу нужен path действия."""
        result = self.action.with_user(self.admin).run()
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "pmk.price.mailing")
        self.assertEqual(result["view_mode"], "form")
        self.assertTrue(result["res_id"])
        self.assertNotIn("id", result)
