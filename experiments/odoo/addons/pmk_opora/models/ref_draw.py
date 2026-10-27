# -*- coding: utf-8 -*-
"""Чертежи марки справочника опор: PDF + DXF по кнопке (Антон 27.10.2026: «Игорь выбрал нужный
размер, исполнение — и ему сразу выкатились чертежи в PDF с DXF»).

Рисует не Odoo: PyMuPDF есть только в образе чертёжного процесса закладных (odoo-zk-worker), и
страница ждать не должна (правило «доработка не замедляет систему»). Обмен — папкой задания в
его очереди (<данные Odoo>/zakladnye/<база>/opora-<id>-<время>/): input.json, файл «runner» с
исполнителем pmk_opora/worker/runner.py, метка «queued». Готовое забирает opora_draw_state(),
его опрашивает окно марки раз в 2 с: PDF, картинка листа 1 и zip DXF — вложениями марки.
Правила в.2 (по чертежам И. Бутова) — lib/; сменились правила — DRAW_RULES, старые чертежи
считаются устаревшими.
"""
import io
import json
import logging
import os
import shutil
import time
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import config

_logger = logging.getLogger(__name__)

DRAW_RULES = "v2"
# Что умеет генератор в.2: категория → исполнения (у ОПП1 «исполнение» — высота 100/70).
DRAW_KINDS = {"kx": ("А12",), "kp": ("А12",), "opp1": ("100", "70")}
WORKER_ALIVE = ".worker_alive"
WORKER_FRESH = 30          # с — отметка процесса свежее этого: процесс жив
DRAW_TIMEOUT = 180         # с — задание дольше этого: ошибка
STEEL = "Ст3пс"


def _age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class OporaRefDraw(models.Model):
    _inherit = "pmk.opora.ref"

    draw_state = fields.Selection([("none", "Нет"), ("queued", "Рисуется"), ("done", "Готов"), ("error", "Ошибка")],
                                  "Чертёж", default="none", readonly=True)
    draw_error = fields.Char("Почему нет чертежа", readonly=True)
    draw_rules = fields.Char("Правила чертежа", readonly=True)
    draw_workdir = fields.Char("Папка задания", readonly=True)
    draw_started = fields.Datetime("Чертёж заказан", readonly=True)
    draw_at = fields.Datetime("Чертёж нарисован", readonly=True)
    draw_pdf_id = fields.Many2one("ir.attachment", "Чертёж PDF", readonly=True, ondelete="set null")
    draw_png_id = fields.Many2one("ir.attachment", "Лист 1 картинкой", readonly=True, ondelete="set null")
    draw_zip_id = fields.Many2one("ir.attachment", "DXF для лазера", readonly=True, ondelete="set null")

    # ------------------------------------------------------------ очередь
    @staticmethod
    def _draw_root():
        return os.environ.get("PMK_ZK_QUEUE") or os.path.join(config["data_dir"], "zakladnye")

    def _draw_supported(self):
        self.ensure_one()
        return self.execution in DRAW_KINDS.get(self.opora_type or "", ())

    def _draw_info(self):
        self.ensure_one()
        fresh = self.draw_state == "done" and self.draw_rules == DRAW_RULES and self.draw_pdf_id
        return {
            "supported": self._draw_supported(),
            "state": "done" if fresh else ("none" if self.draw_state == "done" else self.draw_state),
            "error": self.draw_error or "",
            "rules": DRAW_RULES,
            "at": fields.Datetime.to_string(self.draw_at) if self.draw_at else "",
            "pdf": self.draw_pdf_id.id if fresh else False,
            "png": self.draw_png_id.id if fresh else False,
            "zip": self.draw_zip_id.id if fresh else False,
            "designation": self.designation,
        }

    def opora_draw(self):
        """Кнопка «Сделать чертежи»: задание в очередь чертёжного процесса."""
        self.ensure_one()
        if not self._draw_supported():
            raise UserError(_("Чертежи пока есть для КХ А12, КП А12 и ОПП1. «%s» — позже.") % self.designation)
        if self.draw_state == "queued":
            return self.opora_draw_state()
        root = self._draw_root()
        alive = _age(os.path.join(root, WORKER_ALIVE))
        if alive is None or alive > WORKER_FRESH:
            self.sudo().write({"draw_state": "error", "draw_error": _(
                "Чертёжный процесс не отвечает (контейнер odoo-zk-worker) — скажите разработчику.")})
            return self._draw_info()
        workdir = os.path.join(root, self.env.cr.dbname, "opora-%s-%d" % (self.id, int(time.time())))
        os.makedirs(workdir)
        item = {"key": str(self.id), "kind": self.opora_type, "dn": self.dn, "exe": self.execution, "steel": STEEL}
        with open(os.path.join(workdir, "input.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [item], "name": self.designation}, f, ensure_ascii=False)
        with open(os.path.join(workdir, "runner"), "w", encoding="utf-8") as f:
            f.write("pmk_opora/worker/runner.py")
        with open(os.path.join(workdir, "queued"), "w") as f:
            f.write(str(self.id))
        self.sudo().write({"draw_state": "queued", "draw_error": False, "draw_workdir": workdir,
                           "draw_started": fields.Datetime.now()})
        return self._draw_info()

    def opora_draw_state(self):
        """Опрос окна марки: готово — забрать файлы вложениями; зависло — ошибка."""
        self.ensure_one()
        if self.draw_state == "queued":
            try:
                self._draw_collect()
            except Exception:  # noqa: BLE001 — сломанное задание не роняет окно
                _logger.exception("опоры: не удалось забрать чертёж марки %s", self.id)
                self._draw_finish(_("Не удалось забрать чертёж — передано разработчику."))
        return self._draw_info()

    def _draw_finish(self, error=None, vals=None):
        wd = self.draw_workdir
        self.sudo().write(dict(vals or {}, draw_state="error" if error else "done", draw_error=error or False,
                               draw_workdir=False))
        if wd and wd.startswith(self._draw_root()):
            shutil.rmtree(wd, ignore_errors=True)

    def _draw_collect(self):
        wd = self.draw_workdir or ""
        result = _read_json(os.path.join(wd, "result.json"))
        if result is None:
            err = _read_json(os.path.join(wd, "error.json"))
            if err is not None:
                _logger.error("опоры %s: сбой чертёжного процесса\n%s", self.id, err.get("message"))
                return self._draw_finish(_("Сбой при рисовании — передано разработчику."))
            started = self.draw_started or fields.Datetime.now()
            if (fields.Datetime.now() - started).total_seconds() > DRAW_TIMEOUT:
                return self._draw_finish(_("Чертёж не нарисован за 3 минуты — повторите или скажите разработчику."))
            return
        item = next((i for i in result.get("items") or [] if i.get("key") == str(self.id)), None)
        if not item or item.get("error"):
            return self._draw_finish((item or {}).get("error") or _("Чертёж не построен."))
        name = self.designation
        Att = self.env["ir.attachment"].sudo()
        old = self.draw_pdf_id | self.draw_png_id | self.draw_zip_id

        def attach(fname, data, mimetype):
            return Att.create({"name": fname, "raw": data, "mimetype": mimetype,
                               "res_model": self._name, "res_id": self.id})

        with open(os.path.join(wd, item["pdf"]), "rb") as f:
            pdf = attach("%s.pdf" % name, f.read(), "application/pdf")
        png = Att
        if item.get("png"):
            with open(os.path.join(wd, item["png"][0]), "rb") as f:
                png = attach("%s — лист 1.png" % name, f.read(), "image/png")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for d in item.get("dxf") or []:
                zf.write(os.path.join(wd, d["file"]), os.path.basename(d["file"]))
        zipped = attach("%s — DXF.zip" % name, buf.getvalue(), "application/zip")
        self._draw_finish(vals={"draw_pdf_id": pdf.id, "draw_png_id": png.id or False, "draw_zip_id": zipped.id,
                                "draw_rules": item.get("rules") or DRAW_RULES, "draw_at": fields.Datetime.now()})
        old.unlink()
