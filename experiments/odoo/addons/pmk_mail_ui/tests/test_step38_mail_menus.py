# -*- coding: utf-8 -*-
"""Почта в меню — разбор UX, шаг 38. Гонять ТОЛЬКО на одноразовой базе.

  • почта одна — в Продажах; пункт в Закупках не удалён, виден только с
    «Убранным»;
  • «Почтовые ящики» в Настройках — только администратору
    («Администрирование: Настройки»), не «Почтовому клиенту: Администратор»;
  • доводка: «Лид» — только тому, кто может завести лид. Снабженец без прав
    на продажи читает «Продажи → Почта», кнопки у него нет (браузер
    спрашивает то же право — has_access('create') у crm.lead), а вызов
    кнопки в обход — понятный отказ, лида нет.

Глазами (кнопки «Лид» нет у пользователя без прав на продажи, у
администратора есть) — основной агент на копии.
"""
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

REMOVED = "pmk_theme.group_pmk_removed"


@tagged("post_install", "-at_install")
class TestMailMenusStep38(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [Command.unlink(cls.env.ref(REMOVED).id)]})
        cls.buyer = new_test_user(
            cls.env, login="pmk38_mail_buyer",
            groups="base.group_user,purchase.group_purchase_user,mail_client.group_mail_client_user")
        cls.sale_mail = cls.env.ref("pmk_mail_ui.menu_mail_sale")
        cls.purchase_mail = cls.env.ref("pmk_mail_ui.menu_mail_purchase")
        cls.settings_mail = cls.env.ref("mail_client.menu_mail_client_configuration")

    def _menus(self, user):
        return self.env["ir.ui.menu"].with_user(user).load_web_menus(False)

    def test_mail_only_in_sales(self):
        menus = self._menus(self.buyer)
        self.assertIn(self.sale_mail.id, menus)
        self.assertNotIn(self.purchase_mail.id, menus)
        self.assertNotIn(self.purchase_mail.id, self._menus(self.admin))
        self.assertEqual(self.purchase_mail.group_ids, self.env.ref(REMOVED))
        self.assertFalse(self.sale_mail.group_ids, "Почта в Продажах — всем.")
        self.admin.write({"group_ids": [Command.link(self.env.ref(REMOVED).id)]})
        self.assertIn(self.purchase_mail.id, self._menus(self.admin), "Не удалён — спрятан.")

    def test_mailbox_settings_admin_only(self):
        self.assertEqual(self.settings_mail.group_ids, self.env.ref("base.group_system"))
        self.assertEqual(self.settings_mail.parent_id, self.env.ref("base.menu_administration"))
        # «Права доступа» (видит «Настройки») и почтовый администратор, но не
        # «Администрирование: Настройки» — ящиков не видит.
        rights = new_test_user(
            self.env, login="pmk38_rights",
            groups="base.group_user,base.group_erp_manager,mail_client.group_mail_client_admin")
        menus = self._menus(rights)
        self.assertIn(self.env.ref("base.menu_administration").id, menus)
        self.assertNotIn(self.settings_mail.id, menus)
        for child in self.settings_mail.child_id:
            with self.subTest(item=child.name):
                self.assertNotIn(child.id, menus, "Пункт без своей группы — тоже не виден.")
        self.assertIn(self.settings_mail.id, self._menus(self.admin))

    # ─── Доводка: «Лид» — только тому, кто может завести лид ────────────
    def _letter_for(self, user):
        server = self.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        # Ящик снабженца: правило доступа к письмам — владелец ящика.
        account = self.env["mail.client.account"].create({
            "name": "Снабжение", "email": "snab38@example.org",
            "server_id": server.id, "user_id": user.id,
        })
        folder = self.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": account.id,
            "imap_path": "INBOX", "role": "inbox",
        })
        return self.env["mail.client.message"].create({
            "account_id": account.id, "folder_id": folder.id,
            "imap_uid": 38, "subject": "Прайс на арматуру",
            "email_from": "Металлторг <zakaz@metalltorg.example.org>",
            "date": fields.Datetime.now(),
            "body_html": "<div>Прайс во вложении</div>", "body_state": "fetched",
            "structure_state": "parsed", "pmk_cid_checked": True,
        })

    def test_lead_button_right(self):
        """Право, по которому браузер показывает кнопку: у снабженца без
        продаж его нет, у администратора есть."""
        Lead = self.env["crm.lead"]
        self.assertFalse(Lead.with_user(self.buyer).has_access("create"))
        self.assertTrue(Lead.with_user(self.admin).has_access("create"))

    def test_lead_refused_without_sales_rights(self):
        letter = self._letter_for(self.buyer)
        leads = self.env["crm.lead"].with_context(active_test=False).search_count([])
        with self.assertRaises(UserError) as caught:
            letter.with_user(self.buyer).action_pmk_create_lead()
        self.assertIn("нет прав на лиды", str(caught.exception))
        self.assertEqual(self.env["crm.lead"].with_context(active_test=False).search_count([]),
                         leads, "Лида нет.")
        self.assertFalse(letter.pmk_lead_id)
