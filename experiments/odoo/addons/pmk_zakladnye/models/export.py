# -*- coding: utf-8 -*-
"""Выгрузки закладных: меню «Создать ▾» и «Печать ▾» шапки (виджет pmk_deal_doc_menu).

Печать: все чертежи одним PDF, DXF для лазера (zip: пластины и шайбы по толщинам, количество
на весь документ в имени «…_12шт»), ведомость металла (Excel). Создать: задание на резку —
пластины и шайбы деталями в «Задания на резку» → «Детали к раскрою» → «Раскрой листа».

DXF строит генератор прямо в Odoo (чистый Python, без PyMuPDF) — фоновый процесс для них не нужен.
"""
import base64
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.pdf import merge_pdf

from ..tools import catalog

DXF_NAME = re.compile(r"_поз(\d+)_(.+?)_t([\d,]+)_(\d+)шт\.dxf$")


def _fmt(v):
    return ("%g" % v).replace(".", ",")


def _safe(name):
    return re.sub(r"[\\/:*?\"<>|]+", "_", name or "").strip() or "изделие"


class ZkLineExport(models.Model):
    _inherit = "pmk.zk.line"

    def _zk_dxf_parts(self):
        """Детали для лазера одного изделия: [{pos, kind, thickness, qty, data, name}] на 1 шт."""
        self.ensure_one()
        M, _ms, why = self._zk_model()
        if not M:
            raise UserError(_("%(mark)s: %(why)s", mark=self.mark, why=why))
        g = catalog.gen()
        out = []
        with tempfile.TemporaryDirectory(prefix="pmk_zk_") as tmp:
            for fname in g.dxf_parts(M, Path(tmp)):
                m = DXF_NAME.search(fname)
                with open(os.path.join(tmp, fname), "rb") as f:
                    data = f.read()
                if not m:
                    continue
                out.append({"pos": int(m[1]), "kind": m[2].replace("_", " "),
                            "thickness": float(m[3].replace(",", ".")), "qty": int(m[4]), "data": data,
                            "name": "%s поз.%s %s" % (M["mark"], m[1], m[2].replace("_", " "))})
        return out

    def _zk_dxf_file_name(self, part, qty):
        # «МН 201-5_поз1_пластина_10мм_12шт.dxf»: толщину «10мм» понимает загрузка заданий на резку,
        # «_12шт» — раскрой листа (qty_from_filename).
        return "%s_поз%s_%s_%sмм_%sшт.dxf" % (_safe(self.full_mark or self.mark), part["pos"],
                                              part["kind"].replace(" ", "_"), _fmt(part["thickness"]), qty)


class ZkCalcExport(models.Model):
    _inherit = "pmk.zk.calc"

    laser_task_id = fields.Many2one("pmk.laser.task", "Задание на резку", copy=False, readonly=True)

    def _zk_good(self):
        lines = self.line_ids.filtered(lambda l: l._zk_ok()).sorted(lambda l: (l.sequence, l.id))
        if not lines:
            raise UserError(_("Нет изделий: впишите марки в таблицу (например, «мн 201-5 12шт»)."))
        return lines

    # ------------------------------------------------------------ меню шапки
    def pmk_doc_menu(self):
        menu = {"create": [], "print": [], "send": []}
        if self.env["pmk.laser.task"].has_access("create"):
            menu["create"].append({"key": "laser", "label": _("Задание на резку (пластины, шайбы)"),
                                   "icon": "fa-scissors", "method": "action_zk_laser_task"})
        menu["print"] += [
            {"key": "pdf", "label": _("Все чертежи (PDF)"), "icon": "fa-file-pdf-o", "method": "action_zk_pdf_all"},
            {"key": "dxf", "label": _("DXF для лазера (zip)"), "icon": "fa-file-archive-o", "method": "action_zk_dxf_zip"},
            {"key": "xlsx", "label": _("Ведомость металла (Excel)"), "icon": "fa-file-excel-o",
             "method": "action_zk_metal_xlsx"},
        ]
        return menu

    def _zk_url(self, what):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "download" if what != "drawings.pdf" else "new",
                "url": "/pmk_zakladnye/calc/%d/%s" % (self.id, what)}

    def action_zk_pdf_all(self):
        self.ensure_one()
        lines = self._zk_good()
        missing = lines.filtered(lambda l: l.draw_state != "done")
        if missing:
            raise UserError(_("Чертежи готовы не для всех изделий (%(n)d из %(t)d): нажмите «Подготовить чертежи» "
                              "и дождитесь уведомления.", n=len(lines) - len(missing), t=len(lines)))
        return self._zk_url("drawings.pdf")

    def action_zk_dxf_zip(self):
        self._zk_good()
        return self._zk_url("dxf.zip")

    def action_zk_metal_xlsx(self):
        self._zk_good()
        return self._zk_url("metal.xlsx")

    # ------------------------------------------------------------ файлы
    def _zk_drawings_pdf(self):
        self.ensure_one()
        lines = self._zk_good().filtered(lambda l: l.draw_state == "done")
        datas = [base64.b64decode(l.sudo().pdf) for l in lines if l.sudo().pdf]
        if not datas:
            raise UserError(_("Готовых чертежей нет — нажмите «Подготовить чертежи»."))
        return merge_pdf(datas)

    def _zk_dxf_zip(self, lines=None):
        """zip: папка «10 мм/» — детали этой толщины, количество на все изделия документа."""
        self.ensure_one()
        lines = lines or self._zk_good()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for line in lines:
                for part in line._zk_dxf_parts():
                    qty = part["qty"] * (line.qty or 1)
                    zf.writestr("%s мм/%s" % (_fmt(part["thickness"]), line._zk_dxf_file_name(part, qty)), part["data"])
        return buf.getvalue()

    def _zk_metal_rows(self):
        """Ведомость: по изделиям и сводно по профилям (лист по толщинам, арматура по Ø)."""
        self.ensure_one()
        g = catalog.gen()
        items, sheets, rebar, dep = [], {}, {}, 0.0
        for line in self._zk_good():
            M, ms, _why = line._zk_model()
            if not M:
                continue
            q = line.qty or 1
            items.append((line.full_mark, catalog.series_label(line.series), line.plate, line.anchors, q,
                          ms["all"], ms["all"] * q))
            for t, mass in ms["sheets"].items():
                sheets[t] = sheets.get(t, 0.0) + mass * q
            for d, mass in ms["rebar"].items():
                rebar[d] = rebar.get(d, 0.0) + mass * q
            dep += ms["dep"] * q
        metal = [(g.SHEET, g.STEEL, "t = %s" % _fmt(t), m) for t, m in sorted(sheets.items())]
        metal += [(g.REBAR, g.CLS, "Ø%s" % d, m) for d, m in sorted(rebar.items())]
        metal.append((_("Наплавленный металл 1%"), "", "", dep))
        return items, metal

    def _zk_metal_xlsx(self):
        import xlsxwriter
        self.ensure_one()
        items, metal = self._zk_metal_rows()
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {"in_memory": True})
        bold = wb.add_format({"bold": True})
        head = wb.add_format({"bold": True, "bg_color": "#EDEDED", "border": 1, "text_wrap": True, "valign": "top"})
        cell = wb.add_format({"border": 1})
        kg = wb.add_format({"border": 1, "num_format": "0.00"})
        kg1 = wb.add_format({"border": 1, "num_format": "0.0", "bold": True})
        ws = wb.add_worksheet(_("Изделия"))
        title = "%s · %s" % (self.name, self.object_name or self.partner_id.display_name or "")
        ws.write(0, 0, _("Закладные изделия — %s") % title.strip(" ·"), bold)
        cols = [(_("Изделие"), 22), (_("Серия"), 12), (_("Пластина"), 16), (_("Анкеры"), 30), (_("Кол-во"), 8),
                (_("Масса 1 шт, кг"), 12), (_("Всего, кг"), 12)]
        for c, (name, width) in enumerate(cols):
            ws.write(2, c, name, head)
            ws.set_column(c, c, width)
        r = 3
        for row in items:
            for c, v in enumerate(row):
                ws.write(r, c, v, kg if c >= 5 else cell)
            r += 1
        ws.write(r, 4, sum(i[4] for i in items), kg1)
        ws.write(r, 6, sum(i[6] for i in items), kg1)
        ws2 = wb.add_worksheet(_("Металл"))
        ws2.write(0, 0, _("Ведомость металла — %s") % title.strip(" ·"), bold)
        for c, (name, width) in enumerate([(_("Профиль, ГОСТ"), 30), (_("Марка"), 24), (_("Размер"), 12),
                                           (_("Масса, кг"), 12)]):
            ws2.write(2, c, name, head)
            ws2.set_column(c, c, width)
        r = 3
        for row in metal:
            for c, v in enumerate(row):
                ws2.write(r, c, v, kg if c == 3 else cell)
            r += 1
        ws2.write(r, 0, _("Всего"), bold)
        ws2.write(r, 3, sum(m[3] for m in metal), kg1)
        wb.close()
        return buf.getvalue()

    # ------------------------------------------------------------ задание на резку
    def action_zk_laser_task(self):
        """Пластины и шайбы всех изделий — деталями задания на резку (лазер). Задание уже есть —
        открываем его: второе задание задвоило бы детали в раскрое."""
        self.ensure_one()
        task = self.laser_task_id.exists()
        if not task:
            lines = self._zk_good()
            task = self.env["pmk.laser.task"].create({
                "partner_id": self.partner_id.id or False,
                "note": " · ".join(x for x in (_("Закладные %s") % self.name, self.object_name) if x),
            })
            rows = []
            for line in lines:
                for part in line._zk_dxf_parts():
                    qty = part["qty"] * (line.qty or 1)
                    rows.append({"file": line._zk_dxf_file_name(part, qty), "action": "new",
                                 "data": base64.b64encode(part["data"]).decode(), "name": part["name"],
                                 "thickness": part["thickness"], "qty": qty})
            res = task.pmk_upload_apply(rows)
            self.laser_task_id = task
            self.message_post(body=_("Задание на резку %(task)s: деталей %(n)d.", task=task.name, n=res["created"]),
                              subtype_xmlid="mail.mt_note")
        return {"type": "ir.actions.act_window", "res_model": "pmk.laser.task", "res_id": task.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}
