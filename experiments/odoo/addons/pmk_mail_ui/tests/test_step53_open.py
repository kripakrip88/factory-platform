# -*- coding: utf-8 -*-
"""Мелочи после приёмки 22–34 — разбор UX, шаг 53, почта.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Ловим:
  • «Закупки → Почта» видна обычному закупщику, своё действие открывает ящик
    закупок (zakaz@), «Продажи → Почта» — заявки (pmkpark@) и с кнопкой
    «Лид»; у Закупок кнопки нет;
  • папка письма (pmk_folder_of) — владельцу ящика; чужому, несуществующему
    письму, мусору вместо номера и письму в неподписанной папке — False;
  • счётчик у каждого пункта «Почта» — свой ящик: письмо на zakaz@ не
    поднимает число у «Продажи → Почта» (pmk_mail_unread_counts);
  • адрес info@ → лиды выключен: имя снято, адрес не совпадает ни с одним
    письмом; повтор ничего не делает; приёмники счетов (sales@ /
    purchases@) не тронуты; на новой базе выключен установкой.
Правила выбора ящика и папки в браузере — node
static/tests/step53_open_rules.test.mjs. Глазами (Закупки → Почта открывает
zakaz@, письмо со «Связей» открыто в почте; светлая и тёмная тема) —
основной агент на копии.
"""
from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestMailStep53(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer = new_test_user(
            cls.env, login="pmk53_mail_buyer",
            groups="base.group_user,purchase.group_purchase_user,mail_client.group_mail_client_user")
        cls.other = new_test_user(
            cls.env, login="pmk53_mail_other",
            groups="base.group_user,mail_client.group_mail_client_user")
        server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        account = cls.env["mail.client.account"].create({
            "name": "Закупки (тест 53)", "email": "zakaz53@example.org",
            "server_id": server.id, "user_id": cls.buyer.id,
        })
        cls.folder = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": account.id, "imap_path": "INBOX", "role": "inbox",
        })
        cls.letter = cls.env["mail.client.message"].create({
            "account_id": account.id, "folder_id": cls.folder.id, "imap_uid": 53,
            "subject": "Прайс (тест 53)", "email_from": "Металлторг <price@metall.example.org>",
            "date": fields.Datetime.now(),
        })

    # ─── Меню и ящики ───────────────────────────────────────────────────
    def test_purchase_mail_visible_to_buyer(self):
        menu = self.env.ref("pmk_mail_ui.menu_mail_purchase")
        menus = self.env["ir.ui.menu"].with_user(self.buyer).load_web_menus(False)
        self.assertIn(menu.id, menus, "«Закупки → Почта» видна закупщику.")
        self.assertFalse(menu.group_ids, "Без группы «Убранное (показать)».")
        self.assertEqual(menu.parent_id, self.env.ref("pmk_theme.menu_pmk_purchase"))
        self.assertEqual(menus[menu.id]["name"], "Почта")

    def test_each_section_opens_its_mailbox(self):
        purchase = self.env["ir.actions.actions"]._for_xml_id("pmk_mail_ui.action_mail_purchase")
        sale = self.env["ir.actions.actions"]._for_xml_id("pmk_mail_ui.action_mail_sale")
        self.assertEqual(purchase["tag"], "mail_client.inbox")
        self.assertEqual(sale["tag"], "mail_client.inbox")
        self.assertEqual(purchase["params"].get("pmk_mailbox"), "zakaz@pmkpark.ru")
        self.assertEqual(sale["params"].get("pmk_mailbox"), "pmkpark@mail.ru")
        self.assertFalse(purchase["params"].get("pmk_crm"), "В Закупках кнопки «Лид» нет.")
        self.assertTrue(sale["params"].get("pmk_crm"), "В Продажах — есть.")
        self.assertEqual(self.env.ref("pmk_mail_ui.menu_mail_purchase").action,
                         self.env.ref("pmk_mail_ui.action_mail_purchase"))

    def test_assets(self):
        paths = [p[0].lstrip("/") for p in
                 self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        for name in ("step53_open.js", "step53_open_rules.js"):
            with self.subTest(name=name):
                self.assertIn("pmk_mail_ui/static/src/js/" + name, paths)

    # ─── Папка письма для «Связей» ──────────────────────────────────────
    def test_folder_of_for_owner(self):
        Message = self.env["mail.client.message"]
        self.assertEqual(Message.with_user(self.buyer).pmk_folder_of(self.letter.id), self.folder.id)

    def test_folder_of_refused(self):
        Message = self.env["mail.client.message"]
        self.assertFalse(Message.with_user(self.other).pmk_folder_of(self.letter.id),
                         "Чужое письмо — без папки, почта откроется как обычно.")
        self.assertFalse(Message.with_user(self.buyer).pmk_folder_of(10 ** 9))
        self.assertFalse(Message.with_user(self.buyer).pmk_folder_of("мусор"))
        self.assertFalse(Message.with_user(self.buyer).pmk_folder_of(None))

    def test_folder_of_outside_tree(self):
        """Доводка шага 53: папка не подписана — в дереве почты её нет, и
        почта открылась бы на «Входящих» без письма. Папки нет — False."""
        hidden = self.env["mail.client.folder"].create({
            "name": "Клиенты", "account_id": self.folder.account_id.id,
            "imap_path": "Clients", "role": "other", "subscribed": False,
        })
        letter = self.env["mail.client.message"].create({
            "account_id": self.folder.account_id.id, "folder_id": hidden.id,
            "imap_uid": 54, "subject": "Перенесённое", "email_from": "a@example.org",
            "date": fields.Datetime.now(),
        })
        Message = self.env["mail.client.message"].with_user(self.buyer)
        self.assertFalse(Message.pmk_folder_of(letter.id))
        hidden.subscribed = True
        self.assertEqual(Message.pmk_folder_of(letter.id), hidden.id)

    # ─── Счётчик у каждого пункта «Почта» ───────────────────────────────
    def _inbox_of(self, email, user):
        account = self.env["mail.client.account"].create({
            "name": email, "email": email, "server_id": self.folder.account_id.server_id.id,
            "user_id": user.id,
        })
        return self.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": account.id, "imap_path": "INBOX", "role": "inbox",
        })

    def _unread(self, folder, uid):
        return self.env["mail.client.message"].create({
            "account_id": folder.account_id.id, "folder_id": folder.id, "imap_uid": uid,
            "subject": "Новое", "email_from": "a@example.org", "flag_seen": False,
            "date": fields.Datetime.now(),
        })

    def test_counter_per_menu(self):
        """Прайс на zakaz@ — число у «Закупки → Почта», не у Продаж."""
        sale = self._inbox_of("PMKpark@mail.ru", self.other)
        purchase = self._inbox_of("zakaz@pmkpark.ru", self.other)
        self._unread(sale, 1)
        self._unread(purchase, 2)
        self._unread(purchase, 3)
        counts = self.env["mail.client.account"].with_user(self.other).pmk_mail_unread_counts()
        self.assertEqual(counts["total"], 3, "Вкладка браузера — все «Входящие».")
        self.assertEqual(counts["menus"], {
            "pmk_mail_ui.menu_mail_sale": 1,
            "pmk_mail_ui.menu_mail_purchase": 2,
        })

    def test_counter_menu_without_its_mailbox(self):
        """Ящика с адресом пункта у человека нет — число ящика, который
        почта откроет вместо него (первый по порядку), как браузер."""
        own = self.folder  # единственный ящик закупщика — zakaz53@example.org
        # письмо из setUpClass создано непрочитанным — прочитать, чтобы в ящике
        # было ровно одно новое (иначе число зависит от порядка тестов)
        self.letter.flag_seen = True
        self._unread(own, 4)
        counts = self.env["mail.client.account"].with_user(self.buyer).pmk_mail_unread_counts()
        self.assertEqual(counts["menus"]["pmk_mail_ui.menu_mail_sale"], 1)
        self.assertEqual(counts["menus"]["pmk_mail_ui.menu_mail_purchase"], 1)
        clerk = new_test_user(self.env, login="pmk53_mail_clerk", groups="base.group_user")
        self.assertEqual(
            self.env["mail.client.account"].with_user(clerk).pmk_mail_unread_counts(),
            {"total": 0, "menus": {"pmk_mail_ui.menu_mail_sale": 0,
                                   "pmk_mail_ui.menu_mail_purchase": 0}},
            "Без почты — нули, без ошибки.")

    # ─── info@ → лиды выключен ──────────────────────────────────────────
    def _lead_alias(self, name):
        return self.env["mail.alias"].create({
            "alias_name": name,
            "alias_model_id": self.env["ir.model"]._get("crm.lead").id,
            "alias_contact": "everyone",
        })

    def test_info_alias_off(self):
        Alias = self.env["mail.alias"]
        # Состояние после установки: post_init_hook уже снял имя у info@.
        self.assertFalse(Alias.search([("alias_name", "=", "info"),
                                       ("alias_model_id.model", "=", "crm.lead")]),
                         "На новой базе info@ → лиды выключен установкой.")
        alias = self._lead_alias("info")
        self.assertTrue(alias.alias_full_name)
        off = Alias._pmk_switch_off_lead_aliases()
        self.assertEqual(len(off), 1)
        self.assertFalse(alias.alias_name)
        self.assertFalse(alias.alias_full_name, "Полный адрес пуст — маршрут его не найдёт.")
        self.assertEqual(Alias._pmk_switch_off_lead_aliases(), [], "Повтор ничего не делает.")

    def test_other_aliases_untouched(self):
        lead_other = self._lead_alias("zayavki53")
        invoices = self.env["mail.alias"].create({
            "alias_name": "info53bills",
            "alias_model_id": self.env["ir.model"]._get("res.partner").id,
        })
        self.env["mail.alias"]._pmk_switch_off_lead_aliases()
        self.assertEqual(lead_other.alias_name, "zayavki53", "Только имена из списка.")
        self.assertEqual(invoices.alias_name, "info53bills")
        for alias in self.env["mail.alias"].search([("alias_name", "in", ["sales", "purchases"])]):
            with self.subTest(alias=alias.alias_name):
                self.assertEqual(alias.alias_model_id.model, "account.move")

    def test_team_alias_stays_off(self):
        """Команда продаж: пересчёт приёмника (запись use_leads, как делают
        Настройки CRM) имя не возвращает."""
        team = self.env.ref("sales_team.team_sales_department", raise_if_not_found=False)
        if not team or "use_leads" not in team._fields:
            self.skipTest("crm не установлен")
        self.assertFalse(team.alias_name)
        team.write({"use_leads": not team.use_leads})
        team.write({"use_leads": not team.use_leads})
        self.assertFalse(team.alias_name)
