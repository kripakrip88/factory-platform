# -*- coding: utf-8 -*-
"""«Связи» у раскроя сортамента (Антон 15.10.2026: «смотрю раскрой — нет вкладки связи»)."""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCutPlanTab(TransactionCase):

    def test_cut_plan_has_flow_tab(self):
        arch = etree.fromstring(self.env["pmk.cut.plan"].get_view(view_type="form")["arch"])
        pages = arch.xpath("/form/sheet/notebook/page[@name='pmk_flow']")
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].xpath(".//widget[@name='pmk_flow_map']"))
