# -*- coding: utf-8 -*-
"""Скачивание «Расчёт (Excel)» — права обычные: кто видит расчёт, тот и скачает."""
from odoo import http
from odoo.http import content_disposition, request

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class PmkSpecXlsx(http.Controller):

    @http.route("/pmk_orders/spec/<int:spec_id>/xlsx", type="http", auth="user", methods=["GET"])
    def spec_xlsx(self, spec_id, client=None, **kw):
        spec = request.env["pmk.metal.spec"].browse(spec_id).exists()
        if not spec:
            raise request.not_found()
        spec.check_access("read")
        is_client = client in ("1", "true")
        data = spec._pmk_xlsx(client=is_client)
        return request.make_response(data, headers=[
            ("Content-Type", XLSX),
            ("Content-Disposition", content_disposition(spec._pmk_xlsx_filename(is_client))),
        ])
