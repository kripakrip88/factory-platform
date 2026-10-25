# -*- coding: utf-8 -*-
"""Файлы закладных: все чертежи одним PDF, DXF zip, ведомость Excel — с правами пользователя."""
from urllib.parse import quote

from odoo import http
from odoo.http import request


def _send(data, name, mimetype, inline=False):
    disposition = "%s; filename*=UTF-8''%s" % ("inline" if inline else "attachment", quote(name))
    return request.make_response(data, headers=[("Content-Type", mimetype), ("Content-Disposition", disposition),
                                                ("Content-Length", str(len(data)))])


class ZakladnyeFiles(http.Controller):
    def _calc(self, calc_id):
        calc = request.env["pmk.zk.calc"].browse(calc_id).exists()
        if not calc:
            raise request.not_found()
        calc.check_access("read")
        return calc

    @http.route("/pmk_zakladnye/calc/<int:calc_id>/drawings.pdf", type="http", auth="user")
    def drawings(self, calc_id):
        calc = self._calc(calc_id)
        return _send(calc._zk_drawings_pdf(), "%s чертежи.pdf" % calc.name, "application/pdf", inline=True)

    @http.route("/pmk_zakladnye/calc/<int:calc_id>/dxf.zip", type="http", auth="user")
    def dxf_zip(self, calc_id):
        calc = self._calc(calc_id)
        return _send(calc._zk_dxf_zip(), "%s DXF.zip" % calc.name, "application/zip")

    @http.route("/pmk_zakladnye/calc/<int:calc_id>/metal.xlsx", type="http", auth="user")
    def metal_xlsx(self, calc_id):
        calc = self._calc(calc_id)
        return _send(calc._zk_metal_xlsx(), "%s ведомость металла.xlsx" % calc.name,
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @http.route("/pmk_zakladnye/line/<int:line_id>/dxf.zip", type="http", auth="user")
    def line_dxf(self, line_id):
        line = request.env["pmk.zk.line"].browse(line_id).exists()
        if not line:
            raise request.not_found()
        line.check_access("read")
        return _send(line.calc_id._zk_dxf_zip(line), "%s DXF.zip" % (line.full_mark or line.mark), "application/zip")
