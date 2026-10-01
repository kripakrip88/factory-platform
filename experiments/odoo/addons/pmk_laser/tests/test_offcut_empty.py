# -*- coding: utf-8 -*-
"""Пустой список обрезков — разбор UX, шаг 26.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).

Без подсказки пустой список был одной шапкой на белом — «сломалось»
(пустые строки-распорки снял шаг 24). По умолчанию включён фильтр «На
стеллаже», а обрезки рождаются предложенными: подсказка говорит, откуда
они берутся и где искать неподтверждённые. Видна подсказка, только когда
под фильтр не подошло ни одной записи — это проверяет глаз основного агента.
"""
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLaserOffcutEmptyStep26(TransactionCase):

    def test_offcut_help(self):
        self.env["res.lang"]._activate_lang("ru_RU")
        for lang in ("en_US", "ru_RU"):
            with self.subTest(lang=lang):
                action = self.env["ir.actions.act_window"].with_context(
                    lang=lang)._for_xml_id("pmk_laser.action_laser_offcut")
                help_html = action["help"] or ""
                self.assertIn("Предложить обрезки", help_html)
                self.assertIn("Ждут подтверждения", help_html)
                self.assertFalse(re.search(r"[A-Za-z]", re.sub(r"<[^>]+>", "", help_html)))
                self.assertNotIn("o_view_nocontent_", help_html, "Без картинки.")

    def test_help_names_real_filter_and_button(self):
        """Подсказка называет то, что есть на экране: фильтр в поиске
        обрезков и кнопку в шапке задания."""
        search = self.env.ref("pmk_laser.view_laser_offcut_search")
        arch = etree.fromstring(self.env["pmk.laser.offcut"].get_view(search.id, "search")["arch"])
        self.assertEqual(arch.xpath("//filter[@name='proposal']/@string"), ["Ждут подтверждения"])
        form = self.env.ref("pmk_laser.view_laser_job_form", raise_if_not_found=False)
        if form:
            arch = etree.fromstring(self.env["pmk.laser.job"].get_view(form.id, "form")["arch"])
            self.assertEqual(arch.xpath("//button[@name='action_propose_offcuts']/@string"),
                             ["Предложить обрезки"])
