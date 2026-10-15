# -*- coding: utf-8 -*-
"""Новые файлы в папке Облака Mail.ru → одно сообщение в группу Телеграма.

Раз в 5 минут — свежие папки дат (последние RECENT_DAYS дней) и файлы в корне папки,
раз в сутки — вся папка. Первый проход — «точка отсчёта»: всё, что уже лежит, только
запоминается, в группу не идёт. Перенос файла в другую папку (то же имя, размер и время)
— не новый файл. Тот же путь с другим размером или временем — «обновлён».
"""
import html
import json
import logging
import time
from collections import OrderedDict
from odoo import api, fields, models

from ..tools.webdav import WebDav, WebDavError, folder_date, is_recent, norm

_logger = logging.getLogger(__name__)

P = "pmk_cloud."
DEFAULT_LOGIN = "pmkpark@mail.ru"
DEFAULT_EXTS = "dxf,lxds,zx"
# Папки без даты в названии смотрим раз в 5 минут, кроме этих — их только ночью
# (Антон 15.10.2026: «Архив» — 600+ папок, обход дольше предела задания).
DEFAULT_EXCLUDE = "Архив"
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
            "exclude": {e.strip().lower() for e in (icp.get_param(P + "exclude") or DEFAULT_EXCLUDE).split(",")
                        if e.strip()},
        }

    @api.model
    def _dav(self, cfg):
        return WebDav(cfg["login"], cfg["password"])

    def _status(self, text):
        self.env["ir.config_parameter"].sudo().set_param(P + "last_status", text)

    # ------------------------------------------------------------ обход
    # Полный обход «ПРОИЗВОДСТВА» у Облака дольше 4 минут, а задание крона Odoo снимается
    # на limit_time_real (15.10: два запуска подряд убиты посреди обхода). Поэтому обход —
    # частями: за запуск папок сколько успеется за WALK_BUDGET_S, очередь папок — в параметре
    # pmk_cloud.walk, следующий запуск продолжает. Худший запрос с повторами ~2 мин —
    # запас до 240 с остаётся.
    WALK_BUDGET_S = 90

    @api.model
    def _walk_state(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(P + "walk")
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    @api.model
    def _walk_save(self, walk):
        self.env["ir.config_parameter"].sudo().set_param(
            P + "walk", json.dumps(walk, ensure_ascii=False) if walk else False)

    @api.model
    def _recent_files(self, dav, root, today, exclude=()):
        """Корень папки, папки дат за RECENT_DAYS дней и папки без даты (кроме exclude) —
        с вложенными. Старые папки дат и исключённые — только ночным обходом."""
        files = []
        for item in dav.list(root):
            if not item["dir"]:
                files.append(item)
            elif is_recent(item["name"], today, RECENT_DAYS) or (
                    folder_date(item["name"]) is None and item["name"].strip().lower() not in exclude):
                files.extend(dav.walk(item["path"]))
        return files

    @api.model
    def _walk_step(self, dav, walk, deadline):
        """Пройти очередь папок до срока → (файлы, ошибка). Ошибка — папка обратно в очередь,
        а уже найденное этим запуском всё равно запоминается (иначе пройденные папки выпали бы
        из точки отсчёта и их файлы потом пришли бы как новые)."""
        files = []
        queue = walk["queue"]
        while queue and time.monotonic() < deadline:
            path, depth = queue.pop()
            try:
                items = dav.list(path)
            except WebDavError as e:
                queue.append([path, depth])
                return files, e
            for item in items:
                if item["dir"]:
                    if depth < 6:
                        queue.append([item["path"], depth + 1])
                else:
                    files.append(item)
        return files, None

    def _wanted(self, files, cfg):
        return [f for f in files if "." in f["name"]
                and "." + f["name"].rsplit(".", 1)[-1].lower() in cfg["exts"]]

    @api.model
    def _cron_scan(self, full=False):
        cfg = self._cfg()
        if not cfg["password"] or cfg["root"] == "/":
            return  # не подключено — молчим
        icp = self.env["ir.config_parameter"].sudo()
        now_txt = fields.Datetime.now().strftime("%d.%m %H:%M")
        baseline_done = icp.get_param(P + "baseline_root") == cfg["root"]
        walk = self._walk_state()
        if walk and walk.get("root") != cfg["root"]:
            walk = None  # папку сменили — прежний обход не нужен
        if not walk and (not baseline_done or full):
            walk = {"root": cfg["root"], "kind": "full" if baseline_done else "baseline",
                    "queue": [[cfg["root"], 0]], "files": 0, "new": 0, "runs": 0}
        deadline = time.monotonic() + self.WALK_BUDGET_S
        dav = self._dav(cfg)
        notes = []
        try:
            if baseline_done:
                files = self._wanted(self._recent_files(dav, cfg["root"], fields.Date.context_today(self),
                                                        cfg["exclude"]), cfg)
                fresh = self._remember(files, notify=True, detect_moves=True)
                if fresh:
                    self._notify(cfg["root"], fresh)
                notes.append("свежие папки: %d файлов, новых %d" % (len(files), len(fresh)))
            if walk:
                walk["runs"] += 1
                found, error = self._walk_step(dav, walk, deadline)
                files = self._wanted(found, cfg)
                notify = walk["kind"] == "full"
                fresh = self._remember(files, notify=notify)
                if notify and fresh:
                    self._notify(cfg["root"], fresh)
                walk["files"] += len(files)
                walk["new"] += len(fresh)
                if walk["queue"]:
                    self._walk_save(walk)
                    notes.append("%s: идёт, найдено %d файлов, папок в очереди %d" % (
                        "первый обход" if walk["kind"] == "baseline" else "ночной обход",
                        walk["files"], len(walk["queue"])))
                if error:
                    raise error
                if not walk["queue"]:
                    self._walk_save(None)
                    if walk["kind"] == "baseline":
                        icp.set_param(P + "baseline_root", cfg["root"])
                        notes.append("первый обход готов за %d запусков: %d файлов запомнено, в группу "
                                     "не слали — дальше только новые" % (walk["runs"], walk["files"]))
                    else:
                        notes.append("ночной обход: %d файлов, новых %d" % (walk["files"], walk["new"]))
        except WebDavError as e:
            _logger.warning("облако: %s", e)
            notes.append("ошибка: %s" % e)
        self._status("%s — %s" % (now_txt, "; ".join(notes) or "нечего проверять"))

    @api.model
    def _remember(self, files, notify=True, detect_moves=False):
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
            # Перенос узнаём только в свежих папках: при обходе частями прежний путь мог ещё
            # не попасть в очередь — копия файла в другой папке «увела» бы его запись.
            moved = self.search([("name", "=", f["name"]), ("size", "=", f["size"]),
                                 ("mtime", "=", f["mtime"]), ("path", "not in", [x["path"] for x in files])],
                                limit=1) if (detect_moves and f["mtime"]) else self.browse()
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
