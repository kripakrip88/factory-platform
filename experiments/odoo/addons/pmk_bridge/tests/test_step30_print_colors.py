# -*- coding: utf-8 -*-
"""Цвет печати и писем: фиолетовый Odoo → чёрный (разбор UX, шаг 30).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py, test_kp_send.py):
    odoo -d pmk30_test -i pmk_bridge --test-enable \\
         --test-tags /pmk_bridge --stop-after-init --http-port 8099

Печать глазами (PDF «Запроса КП» — заголовок и итог чёрные, PDF КП без
изменений) смотрит основной агент на копии. Здесь:
  • перекрашивается только фиолетовое, цвет, выбранный руками, — нет;
    второй цвет макета и текст кнопки не трогаются; повтор ничего не меняет;
  • стили отчётов компании пересобраны (write через ORM, не SQL);
  • КП собрано не на внешнем макете — цвета компании его не касаются;
  • миграция 19.0.0.4.0 зовёт то же правило.
"""
import base64
import importlib.util

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

from odoo.addons.pmk_bridge.tools.print_colors import BLACK, make_black


@tagged("post_install", "-at_install")
class TestPrintColorsStep30(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        # Как на боевой базе 02.10.2026 (SELECT res_company).
        self.company.write({
            "primary_color": "#5e4766", "secondary_color": "#010101",
            "email_primary_color": "#FFFFFF", "email_secondary_color": "#875A7B",
        })

    def test_purple_to_black(self):
        changed = make_black(self.env)
        self.assertEqual(changed[self.company.id],
                         {"primary_color": "#5e4766", "email_secondary_color": "#875A7B"})
        self.assertEqual(self.company.primary_color, BLACK)
        self.assertEqual(self.company.email_secondary_color, BLACK)
        self.assertEqual(self.company.secondary_color, "#010101", "второй цвет уже чёрный")
        self.assertEqual(self.company.email_primary_color, "#FFFFFF", "текст кнопки — белый")
        self.assertNotIn(self.company.id, make_black(self.env), "повтор ничего не меняет")

    def test_own_colour_kept(self):
        self.company.write({"primary_color": "#123456", "email_secondary_color": "#654321"})
        self.assertNotIn(self.company.id, make_black(self.env))
        self.assertEqual(self.company.primary_color, "#123456")
        self.assertEqual(self.company.email_secondary_color, "#654321")

    def test_empty_button_colour(self):
        """Пустой цвет кнопки шаблоны писем заменяют на тот же #875A7B."""
        self.company.email_secondary_color = False
        make_black(self.env)
        self.assertEqual(self.company.email_secondary_color, BLACK)

    def test_report_styles_rebuilt(self):
        make_black(self.env)
        css = str(self.env["ir.qweb"]._render("web.styles_company_report",
                                              {"company_ids": self.company}))
        self.assertIn(BLACK, css)
        self.assertNotIn("#5e4766", css.lower())
        attachment = self.env.ref("web.asset_styles_company_report", raise_if_not_found=False)
        if attachment:
            self.assertIn(BLACK, base64.b64decode(attachment.datas).decode(),
                          "write через ORM пересобрал стили отчётов компании")

    def test_kp_not_on_company_layout(self):
        """КП (pmk_bridge/report/quotation_report.xml) собрано на
        web.basic_layout: класса o_company_<id>_layout в нём нет, цвета компании
        его не касаются. Внешний макет — касаются."""
        # Клиент с языком базы: КП печатается на языке клиента (иначе
        # ru_RU — в свежей тестовой базе его может не быть).
        client = self.env["res.partner"].create({"name": "ООО «Тест печати»", "is_company": True})
        spec = self.env["pmk.metal.spec"].with_context(mail_create_nolog=True).create({
            "partner_id": client.id,
            "note": "Каркас навеса",
            "product_ids": [Command.create({"name": "Каркас", "qty": 1, "price_customer_unit": 5000.0})],
        })
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "pmk_bridge.action_report_metal_spec_quotation", spec.ids)
        self.assertIn("Каркас", html.decode())
        self.assertNotIn("o_company_", html.decode())
        self.assertIn("o_company_", self.env.ref("web.external_layout_standard").arch)

    def test_migration_calls_rule(self):
        path = file_path("pmk_bridge/migrations/19.0.0.4.0/post-migrate.py")
        spec = importlib.util.spec_from_file_location("pmk_bridge_migration_19_0_0_4_0", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, "19.0.0.3.0")
        self.company.invalidate_recordset()
        self.assertEqual(self.company.primary_color, BLACK)
        self.assertEqual(self.company.email_secondary_color, BLACK)
