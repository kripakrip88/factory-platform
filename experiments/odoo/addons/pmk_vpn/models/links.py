# -*- coding: utf-8 -*-
"""Ссылка-ключ VLESS + Reality — без Odoo, чтобы проверялась и вне его.

Параметры сервера (адрес, порты, публичный ключ Reality, маскировочный домен)
присылает сам VPN-сервер при каждой синхронизации (experiments/vpn/vpn_sync.py)
— Odoo их не выдумывает и не хранит в репозитории.
"""
import re
from urllib.parse import quote

EMAIL_RE = re.compile(r"^u(\d+)$")

# Поля, без которых ссылку не собрать.
REQUIRED = ("host", "sni", "pbk", "sid", "port_tcp")


def email_of(user_id):
    """Имя ключа на VPN-сервере. Без ФИО: на сервере за границей лежит только
    номер пользователя Odoo."""
    return "u%d" % user_id


def user_id_of(email):
    m = EMAIL_RE.match(email or "")
    return int(m.group(1)) if m else None


def server_ready(server):
    return all(server.get(k) for k in REQUIRED)


def vless_main(uuid, server, name):
    """Основной ключ: TCP + Vision, порт 443."""
    return ("vless://%s@%s:%s?encryption=none&flow=xtls-rprx-vision&security=reality"
            "&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp#%s") % (
        uuid, server["host"], server["port_tcp"], server["sni"], server["pbk"],
        server["sid"], quote(name))


def vless_reserve(uuid, server, name):
    """Запасной ключ: XHTTP (много коротких запросов, как обычный сайт). None —
    запасного входа на сервере нет."""
    if not (server.get("port_xhttp") and server.get("xhttp_path")):
        return None
    return ("vless://%s@%s:%s?encryption=none&security=reality&sni=%s&fp=chrome"
            "&pbk=%s&sid=%s&type=xhttp&path=%s&mode=auto#%s") % (
        uuid, server["host"], server["port_xhttp"], server["sni"], server["pbk"],
        server["sid"], quote(server["xhttp_path"], safe=""), quote(name))


def human_bytes(n):
    """1536 → «1,5 КБ». Для списков и сообщений бота."""
    n = float(n or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            text = ("%d" % n) if unit == "Б" else ("%.1f" % n)
            return "%s %s" % (text.replace(".", ","), unit)
        n /= 1024
    return ""
