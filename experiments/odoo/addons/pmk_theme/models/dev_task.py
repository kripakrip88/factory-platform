# -*- coding: utf-8 -*-
"""Задача доски «Доработка системы»: дата создания без времени (20.10.2026).

Карточка доски и шапка задачи — «№307 · Автор · 19 окт.». Время в такой
строке — шум, а виджет даты у поля «дата-время» время всё равно показывал.
Не хранится: считается из create_date в часовом поясе того, кто смотрит.
"""
from odoo import api, fields, models


class ProjectTaskCreatedOn(models.Model):
    _inherit = "project.task"

    pmk_created_on = fields.Date("Создана", compute="_compute_pmk_created_on")

    @api.depends("create_date")
    def _compute_pmk_created_on(self):
        for task in self:
            task.pmk_created_on = (fields.Datetime.context_timestamp(task, task.create_date).date()
                                   if task.create_date else False)
