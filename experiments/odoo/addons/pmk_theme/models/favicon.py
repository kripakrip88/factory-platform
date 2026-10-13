# -*- coding: utf-8 -*-
"""Значок страницы входа — звёздочка ПМК Парк (13.10.2026).

Вход в систему на боевом рисует модуль «Сайт» (web.login_layout → website.layout), а там
значок вкладки берётся из поля «Значок» сайта, не из шаблона. Ставим тот же файл, что и
в самой системе (views/webclient_favicon.xml). Модуля «Сайт» нет — делать нечего.
"""
import base64

from odoo import api, models
from odoo.tools.misc import file_open

FAVICON = "pmk_theme/static/src/img/favicon.png"


class ResCompanyFavicon(models.Model):
    _inherit = "res.company"

    @api.model
    def _pmk_set_site_favicon(self):
        if "website" not in self.env:
            return False
        with file_open(FAVICON, "rb") as f:
            data = base64.b64encode(f.read())
        websites = self.env["website"].sudo().search([])
        websites.write({"favicon": data})
        return True
