# -*- coding: utf-8 -*-
"""Адрес, на который VPN-сервер приходит раз в минуту.

Он сам отдаёт трафик и адреса, сам забирает список ключей — Odoo никуда не
ходит и не ждёт сеть (правило 11: доработка не тормозит систему). Чужой
запрос отсекается секретом в заголовке X-Pmk-Vpn-Token (системный параметр
pmk_vpn.sync_token, тот же — в /etc/vpn-sync/env на VPN-сервере).
"""
import hmac
import json
import logging

from odoo import http
from odoo.http import Response, request, route

from ..models.vpn_key import PARAM_TOKEN

_logger = logging.getLogger(__name__)

SYNC_PATH = "/pmk_vpn/sync"
MAX_BODY = 512 * 1024


class PmkVpnController(http.Controller):

    @route(SYNC_PATH, type="http", auth="public", methods=["POST"],
           csrf=False, save_session=False)
    def pmk_vpn_sync(self, **_kw):
        env = request.env
        token = env["ir.config_parameter"].sudo().get_param(PARAM_TOKEN) or ""
        got = request.httprequest.headers.get("X-Pmk-Vpn-Token", "")
        if not token or not hmac.compare_digest(token, got):
            return Response("forbidden", status=403)
        raw = request.httprequest.get_data()
        if len(raw) > MAX_BODY:
            return Response("too large", status=413)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return Response("bad json", status=400)
        if not isinstance(payload, dict):
            return Response("bad json", status=400)
        result = env["pmk.vpn.key"].sudo().pmk_sync(payload)
        return Response(json.dumps(result), content_type="application/json")
