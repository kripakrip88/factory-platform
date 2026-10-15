# -*- coding: utf-8 -*-
"""Чтение папок Облака Mail.ru по WebDAV — без Odoo (проверяется отдельно).

Только PROPFIND (список). Скачивания, записи и удаления здесь нет и не будет.
"""
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlparse

BASE_URL = "https://webdav.cloud.mail.ru"
NS = {"d": "DAV:"}
BODY = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop>'
        '<d:resourcetype/><d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>')
DATE_DIR = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$")


class WebDavError(Exception):
    """Облако не ответило как надо: text — для настроек и журнала, без пароля."""


def norm(path):
    """«/ПРОИЗВОДСТВО/» → «/ПРОИЗВОДСТВО»; корень — «/»."""
    path = "/" + "/".join(p for p in (path or "").split("/") if p)
    return path


def parse_multistatus(xml_bytes):
    """[{path, name, dir, size, mtime}] — первым идёт сама папка."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise WebDavError("Облако ответило не списком файлов: %s" % e)
    out = []
    for resp in root.findall("d:response", NS):
        href = resp.findtext("d:href", default="", namespaces=NS)
        path = norm(unquote(urlparse(href).path))
        prop = resp.find("d:propstat/d:prop", NS)
        is_dir = prop is not None and prop.find("d:resourcetype/d:collection", NS) is not None
        size = prop.findtext("d:getcontentlength", default="", namespaces=NS) if prop is not None else ""
        mod = prop.findtext("d:getlastmodified", default="", namespaces=NS) if prop is not None else ""
        try:
            mtime = parsedate_to_datetime(mod).replace(tzinfo=None) if mod else None
        except (TypeError, ValueError):
            mtime = None
        out.append({"path": path, "name": path.rsplit("/", 1)[-1], "dir": is_dir,
                    "size": int(size) if size.isdigit() else 0, "mtime": mtime})
    return out


def folder_date(name):
    """«09.10.26» → date(2026, 10, 9); не дата — None."""
    m = DATE_DIR.match(name.strip())
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def is_recent(name, today, days):
    d = folder_date(name)
    return d is not None and today - timedelta(days=days) <= d <= today + timedelta(days=1)


class WebDav:
    # Облако бывает медленным: первый обход «ПРОИЗВОДСТВА» (85+ папок) 15.10 упал на ReadTimeout
    # одной папки при 30 с. Ждём ответа до 40 с и повторяем сетевой сбой дважды (худший запрос ~2 мин).
    RETRY_PAUSES = (3, 10)

    def __init__(self, login, password, base_url=BASE_URL, timeout=(15, 40), session=None, sleep=None):
        import requests
        import time
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.sleep = sleep or time.sleep
        self.http = session or requests.Session()
        self.http.auth = (login, password)

    def list(self, path):
        """Содержимое папки (без неё самой)."""
        path = norm(path)
        url = self.base + quote(path if path.endswith("/") else path + "/")
        for attempt, pause in enumerate(self.RETRY_PAUSES + (None,)):
            try:
                r = self.http.request("PROPFIND", url, data=BODY.encode(), timeout=self.timeout,
                                      headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
            except Exception as e:  # noqa: BLE001 — сеть: текст без пароля
                if pause is None:
                    raise WebDavError("Облако недоступно: %s (папка «%s», попыток %d)"
                                      % (type(e).__name__, path, attempt + 1))
                self.sleep(pause)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and pause is not None:
                self.sleep(pause)
                continue
            break
        if r.status_code == 401:
            raise WebDavError("Облако не пускает: неверная почта или пароль для внешнего приложения "
                              "(нужен доступ «Облако (WebDAV)»).")
        if r.status_code == 404:
            raise WebDavError("В Облаке нет папки «%s»." % path)
        if r.status_code not in (200, 207):
            raise WebDavError("Облако ответило %s на папку «%s»." % (r.status_code, path))
        items = parse_multistatus(r.content)
        return [i for i in items if i["path"] != path]

    def walk(self, path, max_depth=6, max_dirs=2000):
        """Все файлы под папкой (с вложенными) — [{path, name, size, mtime}]."""
        files, stack, seen = [], [(norm(path), 0)], 0
        while stack:
            cur, depth = stack.pop()
            seen += 1
            if seen > max_dirs:
                raise WebDavError("В папке больше %d вложенных папок — обход остановлен." % max_dirs)
            for item in self.list(cur):
                if item["dir"]:
                    if depth < max_depth:
                        stack.append((item["path"], depth + 1))
                else:
                    files.append(item)
        return files
