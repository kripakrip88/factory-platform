# -*- coding: utf-8 -*-
"""Настройки колонок — вместе со страницей (шаг 55).

Браузер получает свои и общие настройки списков в session_info (ключ
pmk_list_prefs) до первой отрисовки: список сразу рисуется как надо, без
мигания и лишнего запроса, и на другом компьютере после входа — то же.
Тем же путём тема у человека шага 40 (pmk_theme/models/color_scheme.py).

Только внутренним пользователям: портал и публичные списков основного окна
не видят, прав на модель у них нет.
"""
from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        if request and request.session.uid and not self.env.user.share:
            info["pmk_list_prefs"] = self.env["pmk.list.prefs"]._pmk_session_prefs()
        return info
