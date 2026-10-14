# -*- coding: utf-8 -*-
"""Новые файлы в папке Облака Mail.ru → одно сообщение в группу Телеграма.

Раз в 5 минут — свежие папки дат (последние RECENT_DAYS дней) и файлы в корне папки,
раз в сутки — вся папка. Первый проход — «точка отсчёта»: всё, что уже лежит, только
запоминается, в группу не идёт. Перенос файла в другую папку (то же имя, размер и время)
— не новый файл. Тот же путь с другим размером или временем — «обновлён».
"""
import html
import logging
from collections import OrderedDict
from odoo import api, fields, models

from ..tools.webdav import WebDav, WebDavError, folder_date, is_recent, norm

_logger = logging.getLogger(__name__)

P = "pmk_cloud."
DEFAULT_LOGIN = "pmkpark@mail.ru"
DEFAULT_EXTS = "dxf,lxds,zx"
RECENT_DAYS = 7
# Свыше — одно сообщение «и ещё N файлов» вместо простыни (перенесли архив целиком).
MAX_LINES = 40
TG_LIMIT = 3900


def _size(n):
    if n >= 1024 * 1024:
        return ("%.1f МБ" % (n / 1048576.0)).replace(".", ",")
    return "%d КБ" % max(1, round(n / 1024.0))


class CloudFile(models.Model):
    _name = "pmk.cloud.file"
    _description = "Облако Mail.ru — увиденный файл"
    _order = "id desc"

    path = fields.Char("Путь", required=True, index=True)
    name = fields.Char("Файл", required=True, index=True)
    size = fields.Integer("Размер, байт")
    mtime = fields.Datetime("Изменён в Облаке")
    first_seen = fields.Datetime("Замечен", default=fields.Datetime.now)
    notified = fields.Boolean("Сообщено в группу")

    _path_uniq = models.Constraint("unique(path)", "Файл с этим путём уже записан.")

    # ------------------------------------------------------------ настройки
    @api.model
    def _cfg(self):
        icp = self.env["ir.config_parameter"].sudo()
        exts = icp.get_param(P + "exts") or DEFAULT_EXTS
        return {
            "login": (icp.get_param(P + "login") or DEFAULT_LOGIN).strip(),
            "password": icp.get_param(P + "password") or "",
            "root": norm(icp.get_param(P + "root") or ""),
            "exts": {"." + e.strip().lower().lstrip(".") for e in exts.split(",") if e.strip()},
        }

    @api.model
    def _dav(self, cfg):
        return WebDav(cfg["login"], cfg["password"])

    def _status(self, text):
        self.env["ir.config_parameter"].sudo().set_param(P + "last_status", text)

    # ------------------------------------------------------------ обход
    @api.model
    def _collect(self, dav, root, full, today):
        """Файлы для сверки: вся папка (full) или корень + свежие папки дат."""
        if full:
            return dav.walk(root)
        files = []
        for item in dav.list(root):
            if not item["dir"]:
                files.append(item)
            elif is_recent(item["name"], today, RECENT_DAYS):
                files.extend(dav.walk(item["path"]))
        return files

    @api.model
    def _cron_scan(self, full=False):
        cfg = self._cfg()
        if not cfg["password"] or cfg["root"] == "/":
            return  # не подключено — молчим
        icp = self.env["ir.config_parameter"].sudo()
        baseline = icp.get_param(P + "baseline_root") != cfg["root"]
        today = fields.Date.context_today(self)
        try:
            files = self._collect(self._dav(cfg), cfg["root"], full or baseline, today)
        except WebDavError as e:
            _logger.warning("облако: %s", e)
            self._status("Ошибка %s: %s" % (fields.Datetime.now().strftime("%d.%m %H:%M"), e))
            return
        files = [f for f in files if "." + f["name"].rsplit(".", 1)[-1].lower() in cfg["exts"]
                 and "." in f["name"]]
        fresh = self._remember(files, notify=not baseline)
        if baseline:
            icp.set_param(P + "baseline_root", cfg["root"])
        elif fresh:
            self._notify(cfg["root"], fresh)
        self._status("Проверено %s: %s файлов, новых %d%s" % (
            fields.Datetime.now().strftime("%d.%m %H:%M"), len(files), len(fresh),
            " (точка отсчёта — в группу не слали)" if baseline else ""))

    @api.model
    def _remember(self, files, notify=True):
        """Записать увиденное; вернуть [(файл, «новый»|«обновлён»)] для сообщения."""
        known = {r.path: r for r in self.search([("path", "in", [f["path"] for f in files])])}
        fresh = []
        for f in sorted(files, key=lambda x: x["path"]):
            rec = known.get(f["path"])
            vals = {"size": f["size"], "mtime": f["mtime"]}
            if rec:
                changed = rec.size != f["size"] or (f["mtime"] and rec.mtime != f["mtime"])
                if changed:
                    rec.write(dict(vals, notified=notify))
                    if notify:
                        fresh.append((f, "обновлён"))
                continue
            moved = self.search([("name", "=", f["name"]), ("size", "=", f["size"]),
                                 ("mtime", "=", f["mtime"]), ("path", "not in", [x["path"] for x in files])],
                                limit=1) if f["mtime"] else self.browse()
            if moved:
                moved.path = f["path"]  # перенесли или переименовали папку — не новый
                continue
            self.create(dict(vals, path=f["path"], name=f["name"], notified=notify))
            if notify:
                fresh.append((f, "новый"))
        return fresh

    # ------------------------------------------------------------ сообщение
    @api.model
    def _message(self, root, fresh):
        groups = OrderedDict()
        for f, how in fresh:
            folder = f["path"][len(root):].rsplit("/", 1)[0].strip("/")
            groups.setdefault(folder, []).append((f, how))
        title = root.strip("/").rsplit("/", 1)[-1] or "Облако"
        lines = ["☁️ <b>Облако · %s</b> — %s" % (html.escape(title), (
            "новый файл" if len(fresh) == 1 else "новых файлов: %d" % len(fresh)))]
        shown = 0
        for folder, items in groups.items():
            lines.append("")
            lines.append("📁 %s" % html.escape(" / ".join([title] + [p for p in folder.split("/") if p])))
            for f, how in items:
                if shown >= MAX_LINES:
                    break
                lines.append("• %s (%s)%s" % (html.escape(f["name"]), _size(f["size"]),
                                               " — обновлён" if how == "обновлён" else ""))
                shown += 1
        if shown < len(fresh):
            lines.append("")
            lines.append("…и ещё %d" % (len(fresh) - shown))
        text = "\n".join(lines)
        return text if len(text) <= TG_LIMIT else text[:TG_LIMIT] + "…"

    @api.model
    def _notify(self, root, fresh):
        """В общую группу (без темы); своя тема — параметр pmk_telegram.thread.cloud."""
        icp = self.env["ir.config_parameter"].sudo()
        bot = self.env["pmk.telegram.bot"].sudo()
        chat = icp.get_param("pmk_telegram.group_chat_id")
        api_ = bot._pmk_api()
        if not chat or not api_:
            _logger.info("облако: группа Телеграма не подключена — %d файлов без сообщения", len(fresh))
            return False
        return bool(api_.send(chat, self._message(root, fresh),
                              thread_id=icp.get_param("pmk_telegram.thread.cloud") or None))

    # ------------------------------------------------------------ проверка из настроек
    @api.model
    def _check_connection(self):
        """«Проверить»: список папки (или корня Облака — чтобы найти нужную)."""
        cfg = self._cfg()
        if not cfg["password"]:
            return False, "Впишите пароль для внешнего приложения."
        try:
            items = self._dav(cfg).list(cfg["root"])
        except WebDavError as e:
            return False, str(e)
        dirs = [i["name"] for i in items if i["dir"]]
        files = [i for i in items if not i["dir"]]
        if cfg["root"] == "/":
            return True, "Подключено. Папки в корне Облака: %s. Укажите нужную в поле «Папка»." % (
                ", ".join(dirs[:30]) or "нет")
        dated = sorted((d for d in dirs if folder_date(d)), key=folder_date)
        return True, "Подключено: «%s» — папок %d (последняя по дате %s), файлов в корне %d." % (
            cfg["root"], len(dirs), dated[-1] if dated else "—", len(files))
