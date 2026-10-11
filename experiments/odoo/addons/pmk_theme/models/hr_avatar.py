# -*- coding: utf-8 -*-
"""Фото сотрудника — аватар его пользователя (задача 262, 12.10.2026).

Антон: «Аватарка сотрудника почему-то установлена, но в документах не
применилась» — в «Ответственном» у Голубенко буква «В». Документы (сделки,
строки заказов, задачи) показывают аватар ПОЛЬЗОВАТЕЛЯ — картинку его
контрагента, а фото загружали в карточку СОТРУДНИКА. Штатно Odoo переносит
только обратно: пользователь сменил аватар — фото сотрудника обновилось
(hr, res.users._get_employee_fields_to_sync).

Теперь и вперёд: фото сотрудника записывается в аватар его пользователя —
при создании, смене фото и привязке пользователя. Пишем в контрагента
пользователя (не в res.users): запись пользователя вернула бы фото в
сотрудника тем же штатным переносом — круг. Разовый перенос уже загруженных
фото — migrations/19.0.2.16.0/post-migrate.py.
"""
from odoo import api, models


class HrEmployeeAvatar(models.Model):
    _inherit = "hr.employee"

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._pmk_push_avatar()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if "image_1920" in vals or "user_id" in vals:
            self._pmk_push_avatar()
        return res

    def _pmk_push_avatar(self):
        for employee in self.sudo():
            partner = employee.user_id.partner_id
            if partner and employee.image_1920 and partner.image_1920 != employee.image_1920:
                partner.image_1920 = employee.image_1920
