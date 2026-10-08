# -*- coding: utf-8 -*-
"""Проект на «Связях» не раскрывает чужие задачи (задача доски 247, 08.10).

Схема счёта СЧ-00020 шла: счёт → своя строка «Заказов в работе» → проект
«Заказы в работе» → ВСЕ его строки (импорт из таблицы — около 185). Теперь
проект — конечный узел, если до него дошли от другого документа.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectHub(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if "project.project" not in cls.env:
            cls.skipTest(cls, "нет модуля project")
        cls.project = cls.env["project.project"].create({"name": "Котёл"})
        cls.tasks = cls.env["project.task"].create([
            {"name": f"Заказ {i}", "project_id": cls.project.id} for i in range(5)
        ])

    def _ids(self, model, rec):
        graph = self.env["pmk.flow.builder"].get_flow_graph(model, rec.id)
        return {n["id"] for n in graph["nodes"]}

    def _nid(self, rec):
        return self.env["pmk.flow.builder"]._node_id(rec)

    def test_from_task_project_is_leaf(self):
        ids = self._ids("project.task", self.tasks[0])
        self.assertIn(self._nid(self.project), ids)
        for other in self.tasks[1:]:
            self.assertNotIn(self._nid(other), ids)

    def test_from_project_tasks_shown(self):
        ids = self._ids("project.project", self.project)
        for task in self.tasks:
            self.assertIn(self._nid(task), ids)
