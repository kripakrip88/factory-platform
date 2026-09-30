# -*- coding: utf-8 -*-
"""Настройки без галочек платных модулей IAP (шаг 23).

Разметка — как её получает браузер (get_views: все наследники применены,
узлы с чужими группами вырезаны сервером). Если галочки нет в разметке, её
поле не уходит при сохранении, и модуль не ставится.

Что ловим: вид с упавшим xpath (Odoo выключает его при загрузке), галочку,
вернувшуюся в разметку, и лишнее скрытие соседних настроек CRM и «Контактов».
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

GROUP = "pmk_theme.group_pmk_dangerous_actions"

PAID_FIELDS = (
    "module_crm_iap_enrich",          # CRM → Обогащение лидов
    "module_crm_iap_mine",            # CRM → Поиск лидов
    "module_website_crm_iap_reveal",  # CRM → Посещения → лиды
    "module_partner_autocomplete",    # Общие → Контакты → Автозаполнение
)


@tagged("post_install", "-at_install")
class TestSettingsPaidHidden(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        # Раздел CRM в Настройках виден только менеджеру продаж.
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("base.group_system").id),
            Command.link(cls.env.ref("sales_team.group_sale_manager").id),
        ]})

    def _arch(self):
        views = self.env["res.config.settings"].with_user(self.admin).get_views([(False, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_our_views_are_active(self):
        for xmlid in (
            "pmk_theme.view_res_config_settings_crm_no_paid",
            "pmk_theme.view_res_config_settings_base_no_paid",
        ):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_paid_checkboxes_gone(self):
        arch = self._arch()
        for name in PAID_FIELDS:
            with self.subTest(field=name):
                self.assertFalse(arch.xpath("//field[@name='%s']" % name))
        self.assertFalse(arch.xpath("//block[@name='convert_visitor_setting_container']"),
                         "Блок «Генерация лидов» без строк не нужен — скрыт целиком.")
        self.assertFalse(arch.xpath("//block[@name='generate_lead_setting_container']"))
        self.assertFalse(arch.xpath("//setting[@id='partner_autocomplete']"))

    def test_neighbours_stay(self):
        arch = self._arch()
        # CRM: «Лиды» и автоназначение на месте.
        for name in ("group_use_lead", "crm_use_auto_assignment"):
            with self.subTest(field=name):
                self.assertTrue(arch.xpath("//field[@name='%s']" % name))
        # «Контакты»: блок и «Отправка СМС» (ссылка на кредиты) на месте.
        self.assertTrue(arch.xpath("//block[@name='contacts_setting_container']"))
        self.assertTrue(arch.xpath("//setting[@id='sms']"))

    def test_reversible_by_group(self):
        self.admin.write({"group_ids": [Command.link(self.env.ref(GROUP).id)]})
        arch = self._arch()
        for name in PAID_FIELDS:
            with self.subTest(field=name):
                self.assertTrue(arch.xpath("//field[@name='%s']" % name))
