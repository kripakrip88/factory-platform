# -*- coding: utf-8 -*-
"""Вкладка «Связи» у задания лазеру — разбор UX, шаг 36 (02.10.2026).

У задания вкладки не было, хотя на схеме расчёта и сделки задание есть
(узел «Лазер»). Теперь — так же, как у расчёта: последней вкладкой, виджет
pmk_flow_map. Подписи состояния узла — те же слова, что у значков в списке
заданий: «нет норматива», а не «норматива нет».

Гонять ТОЛЬКО на одноразовой базе (см. tests/__init__.py).
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged

from ..models.flow_builder import _LASER_PLAN


@tagged("post_install", "-at_install")
class TestLaserTabStep36(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context, tracking_disable=True,
            mail_create_nolog=True, mail_create_nosubscribe=True))
        cls.machine = cls.env["pmk.laser.machine"].create({"name": "Станок-проба связи 36"})
        cls.spec = cls.env["pmk.metal.spec"].create({})
        cls.job = cls.env["pmk.laser.job"].create({
            "machine_id": cls.machine.id, "spec_id": cls.spec.id})

    def test_tab_last_with_widget(self):
        view = self.env.ref("pmk_laser.view_laser_job_form")
        arch = etree.fromstring(
            self.env["pmk.laser.job"].get_views([(view.id, "form")])["views"]["form"]["arch"])
        pages = arch.xpath("/form/sheet/notebook/page")
        self.assertEqual(pages[-1].get("name"), "pmk_flow", "«Связи» — последней вкладкой.")
        self.assertEqual(pages[-1].get("string"), "Связи")
        self.assertTrue(pages[-1].xpath("widget[@name='pmk_flow_map']"))
        self.assertTrue(self.env.ref("pmk_flow.view_laser_job_form_pmk_flow").active)

    def test_job_graph(self):
        graph = self.env["pmk.flow.builder"].get_flow_graph("pmk.laser.job", self.job.id)
        nodes = {node["id"]: node for node in graph["nodes"]}
        key = "pmk.laser.job,%s" % self.job.id
        self.assertIn(key, nodes)
        self.assertIn("pmk.metal.spec,%s" % self.spec.id, nodes, "Задание ведёт к расчёту.")
        self.assertEqual(nodes[key]["kind"], "Лазер")
        # Чертежей нет — «рез не разобран» серым.
        self.assertEqual((nodes[key]["state"], nodes[key]["color"]), ("рез не разобран", "grey"))

    def test_same_words_as_list_badges(self):
        selection = dict(self.env["pmk.laser.job"].fields_get(["plan_state"])["plan_state"]["selection"])
        for key, (label, _color) in _LASER_PLAN.items():
            with self.subTest(state=key):
                self.assertEqual(label, selection[key].lower(), "Одно понятие — одно слово.")
