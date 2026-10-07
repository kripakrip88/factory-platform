# -*- coding: utf-8 -*-
"""Шаг 59 (07.10.2026): раздел «Задачи» — доработка системы карточками,
«Список дел», проекты. Штатные корни «Проект» и «Список дел» скрыты."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStep59Tasks(TransactionCase):

    def test_dev_project_and_stages(self):
        project = self.env.ref("pmk_theme.project_dev")
        self.assertEqual(project.name, "Доработка системы")
        stages = self.env["project.task.type"].search(
            [("project_ids", "in", project.id)], order="sequence")
        self.assertEqual(stages.mapped("name"), [
            "Новые", "В очереди", "В работе", "Выложено — проверить",
            "Принято с замечаниями", "Принято", "Отложено"])

    def test_menu_section(self):
        root = self.env.ref("pmk_theme.menu_pmk_tasks")
        self.assertFalse(root.parent_id)
        self.assertEqual(root.name, "Проекты", "шаг 61: раздел называется «Проекты»")
        self.assertEqual(root.child_id.sorted("sequence").mapped("name"),
                         ["Доработка системы", "Список дел", "Все проекты"])
        # штатные корни по-прежнему скрыты — дублей в шапке нет
        self.assertFalse(self.env.ref("project.menu_main_pm").active)
        self.assertFalse(self.env.ref("project_todo.menu_todo_todos").active)

    def test_action_opens_dev_tasks(self):
        action = self.env.ref("pmk_theme.action_dev_tasks")
        project = self.env.ref("pmk_theme.project_dev")
        task = self.env["project.task"].with_context(
            default_project_id=project.id).create({"name": "Проверка шага 59"})
        self.assertEqual(task.stage_id.name, "Новые", "новая задача — в «Новые»")
        from odoo.tools.safe_eval import safe_eval
        found = self.env["project.task"].search(safe_eval(action.domain))
        self.assertIn(task, found)

    def test_notebook_wraps_everywhere(self):
        """Перенос текста во вкладках — во всех формах, не только .pmk-form."""
        from odoo.tools.misc import file_open
        src = file_open("pmk_theme/static/src/scss/forms_nexus.scss").read()
        start = src.index("// ═══ Шаг 59")
        nxt = src.find("// ═══ Шаг", start + 1)
        section = src[start:nxt if nxt != -1 else None]
        self.assertIn(".o_form_view .o_notebook.horizontal > .o_notebook_content", section)
        self.assertIn("white-space: normal", section)
