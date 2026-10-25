# -*- coding: utf-8 -*-
"""Таблица изделий — таблица Бутика (правило Антона 21.10: ввод строк везде одной таблицей).

Виджет pmk_zk_grid — наследник pmk_butik/static/src/js/butik_grid.js: те же клавиши,
вставка столбика марок из Excel, сохранение ячейки при уходе. Строка — изделие:
короткая запись в ячейке («мн 201-5 12шт», «мн 104-1 1200 10шт», «м1-9-7 4шт»), под ней —
причина, если марку не понял или серия её не поддерживает (строка жёлтым). Состав
выбранного изделия и его чертёж — панелью под таблицей (прототип, принят 25.10.2026).
Ключ строки — «z<id>».
"""
from odoo import _, models
from odoo.exceptions import UserError

from ..tools import catalog

KEY = "z"
DRAW_LABEL = {"none": "", "queued": "в очереди", "done": "готов", "stale": "устарел", "error": "ошибка"}


def _to_float(value):
    text = str(value or "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _key(line):
    return "%s%s" % (KEY, line.id)


def _parse_key(key):
    key = str(key or "")
    return int(key[1:]) if len(key) > 1 and key[0] == KEY and key[1:].isdigit() else 0


def _kg(v):
    return round(v or 0.0, 2)


class ZkLineGrid(models.Model):
    _inherit = "pmk.zk.line"

    def _grid_entry(self):
        """Что стоит в ячейке «Марка»: как набрали (если не понял) или марка с длиной."""
        self.ensure_one()
        if self.parse_error:
            return self.pmk_text or ""
        if not self.mark:
            return ""
        return self.mark + (" L%s" % ("%g" % self.length) if self.length else "")

    def _grid_row(self, number):
        self.ensure_one()
        bad = bool(self.parse_error or self.build_error)
        record = self.sudo()
        has_pdf = self.draw_state in ("done", "stale") and bool(record.pdf)
        unique = (self.drawing_key or "").replace("|", "-")
        return {
            "id": _key(self), "kind": "product", "number": number,
            "name": self._grid_entry(),
            "label": self.parse_error or self.build_error or "", "bad": bad,
            "warning": "" if bad else (self.warning or ""),
            "series": catalog.series_label(self.series) if self.mark else "",
            "pogon": catalog.is_pogon(self.mark) if self.mark and not self.parse_error else False,
            "length": self.length or 0,
            "product_qty": self.qty or 0,
            "plate": self.plate or "", "anchors": self.anchors or "",
            "mass": _kg(self.mass_one), "mass_total": round(self.mass_total or 0.0, 1),
            "draw": self.draw_state if self._zk_ok() else "",
            "draw_label": DRAW_LABEL.get(self.draw_state, "") if self._zk_ok() else "",
            "draw_error": self.draw_error or "",
            # Панель под таблицей (выбранная строка).
            "full_mark": self.full_mark or "", "weld": self.weld or "",
            "site_mass": self.site_mass or 0.0,
            "comp": self._zk_composition() if self._zk_ok() else [],
            "pdf_url": ("/web/content/pmk.zk.line/%d/pdf/%s.pdf?download=false&unique=%s"
                        % (self.id, (self.full_mark or "чертёж"), unique)) if has_pdf else "",
            "png_url": ("/web/image/pmk.zk.line/%d/png?unique=%s" % (self.id, unique))
                       if has_pdf and record.png else "",
            "dxf_url": "/pmk_zakladnye/line/%d/dxf.zip" % self.id if self._zk_ok() else "",
        }

    def _grid_apply_text(self, text):
        """Короткая запись → марка, серия, длина, кол-во. Не понял — запись остаётся с причиной."""
        self.ensure_one()
        text = (text or "").strip()
        if not text:
            self.write({"pmk_text": False, "parse_error": False, "mark": False, "series": False, "length": 0.0})
            return
        res = catalog.parse(text)
        if res.get("error"):
            self.write({"pmk_text": text, "parse_error": res["error"]})
            return
        vals = {"mark": res["mark"], "series": res["series"], "length": res["length"] or 0.0,
                "pmk_text": False, "parse_error": False}
        if res.get("qty"):
            vals["qty"] = res["qty"]
        elif not self.qty:
            vals["qty"] = 1
        self.write(vals)


class ZkCalcGrid(models.Model):
    _inherit = "pmk.zk.calc"

    def _grid_lines(self):
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))

    def zk_rows(self):
        self.ensure_one()
        self.check_access("read")
        if not self.line_ids and self.has_access("write"):
            self.env["pmk.zk.line"].create({"calc_id": self.id, "sequence": 10})
        # Таблица опрашивает, пока чертежи рисуются: забрать готовое, не дожидаясь cron.
        for job in self.job_ids.filtered(lambda j: j.state == "running"):
            try:
                with self.env.cr.savepoint():
                    job.sudo()._poll()
            except Exception:  # noqa: BLE001 — cron повторит и запишет причину
                pass
        rows = [line._grid_row(i) for i, line in enumerate(self._grid_lines(), 1)]
        return {
            "rows": rows, "products": self.mark_count, "count": self.total_qty,
            "weight_kg": self.total_weight, "can_write": self.has_access("write"),
            "draw_text": self.draw_text or "", "draw_busy": self.draw_busy,
        }

    def _grid_record(self, key):
        rid = _parse_key(key)
        return self.line_ids.filtered(lambda l: l.id == rid)

    def _grid_new(self, after, text=""):
        lines = self._grid_lines()
        seq = after.sequence if after else max(lines.mapped("sequence") or [0])
        for other in lines.filtered(lambda l: l.sequence > seq):
            other.sequence += 10
        line = self.env["pmk.zk.line"].create({"calc_id": self.id, "sequence": seq + 5})
        if text:
            line._grid_apply_text(text)
        return line

    def zk_save_row(self, row_key, vals):
        """Правка ячейки (или новая строка: row_key = False, vals["after_id"])."""
        self.ensure_one()
        self.check_access("write")
        vals = vals or {}
        if not row_key:
            self._grid_new(self._grid_record(vals.get("after_id")), vals.get("name") or "")
            return self.zk_rows()
        line = self._grid_record(row_key)
        if not line:
            return self.zk_rows()
        if "name" in vals:
            line._grid_apply_text(vals["name"])
        if "product_qty" in vals:
            line.qty = max(1, int(_to_float(vals["product_qty"]) or 1))
        if "length" in vals:
            length = _to_float(vals["length"])
            if line.mark and not line.parse_error:
                line.length = length
        return self.zk_rows()

    def zk_insert_rows(self, after_key, rows):
        """Вставка из Excel или письма: каждая строка — изделие («МН 201-5 | 12»)."""
        self.ensure_one()
        self.check_access("write")
        texts = [" ".join(str(v).strip() for v in (row or {}).values() if str(v or "").strip())
                 for row in rows or []]
        texts = [t for t in texts if t]
        line = self._grid_record(after_key)
        if line and not (line.mark or line.pmk_text) and texts:
            line._grid_apply_text(texts.pop(0))
        for text in texts:
            line = self._grid_new(line, text)
        return self.zk_rows()

    def zk_add_product(self):
        self.ensure_one()
        self.check_access("write")
        self._grid_new(self._grid_lines()[-1:])
        return self.zk_rows()

    def zk_delete_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        self._grid_record(row_key).unlink()
        return self.zk_rows()

    def zk_duplicate_row(self, row_key):
        self.ensure_one()
        self.check_access("write")
        line = self._grid_record(row_key)
        if line:
            for other in self.line_ids.filtered(lambda l, s=line.sequence: l.sequence > s):
                other.sequence += 10
            line.copy({"calc_id": self.id, "sequence": line.sequence + 5})
        return self.zk_rows()

    def zk_move_row(self, row_key, target_key, below):
        """№312: перетащить строку над/под другую."""
        self.ensure_one()
        self.check_access("write")
        line, target = self._grid_record(row_key), self._grid_record(target_key)
        if not line or not target or line == target:
            return self.zk_rows()
        lines = [l for l in self._grid_lines() if l != line]
        lines.insert(lines.index(target) + (1 if below else 0), line)
        for number, item in enumerate(lines, 1):
            if item.sequence != number * 10:
                item.sequence = number * 10
        return self.zk_rows()

    def zk_set_position(self, row_key, key):
        raise UserError(_("У закладных нет подсказок справочника — марку разбирает сервер."))
