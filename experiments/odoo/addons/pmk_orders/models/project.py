# -*- coding: utf-8 -*-
"""Проект «Заказы в работе» и смысл его этапов (шаг З-2).

Планировщик — таблица Excel Антона на штатных Проектах: строка = заказ
(задача), этапы Очередь / Разработка чертежей / Ждём металл / В работе /
Пауза / Готово к отгрузке / Отгружено. Проект и этапы — данные модуля
(data/orders_project.xml, noupdate: названия этапов Антон может менять сам).

pmk_is_orders — признак проекта на случай, если xml-id потеряется; по нему
код находит проект. pmk_order_stage — смысл этапа: цвет плашки, «просрочена»
(не у «Отгружено»), будущие карточки 4/5 («Ждём металл» ← заявка на
металл). Переименование этапа смысл не меняет.
"""
from odoo import fields, models

ORDER_STAGES = [
    ("queue", "Очередь"),
    ("drawings", "Разработка чертежей"),
    ("metal", "Ждём металл"),
    ("work", "В работе"),
    ("pause", "Пауза"),
    ("ready", "Готово к отгрузке"),
    ("shipped", "Отгружено"),
]


class ProjectProject(models.Model):
    _inherit = "project.project"

    pmk_is_orders = fields.Boolean(
        "Заказы в работе", copy=False,
        help="Проект-планировщик «Заказы в работе»: строки появляются сами, когда "
             "сделку переводят в «Выиграно».")

    def action_view_tasks(self):
        """Карточка проекта «Заказы в работе» в «Проектах» открывает
        планировщик (наши список, канбан и форма), а не штатный канбан задач."""
        if len(self) == 1 and self.pmk_is_orders:
            action = self.env["ir.actions.act_window"]._for_xml_id("pmk_orders.action_orders")
            action["display_name"] = self.name
            return action
        return super().action_view_tasks()


class ProjectTaskType(models.Model):
    _inherit = "project.task.type"

    pmk_order_stage = fields.Selection(
        ORDER_STAGES, "Смысл этапа заказа", copy=False,
        help="Что значит этап планировщика «Заказы в работе»: цвет плашки, "
             "«просрочена» и будущая автоматика. Переименование этапа его не меняет.")
