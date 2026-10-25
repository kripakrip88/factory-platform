# -*- coding: utf-8 -*-
"""Изделие «Конструкций» из деталей калькулятора — одна дверь для опор и болтов.

Антон 25.10.2026: детали опоры («Корпус гнутый — лист 3, развёртка 257×340») — это листовой
материал, и в расчёте он должен стоять номенклатурой. Решение — вариант 1: опора и болт
переносятся в расчёт изделием «Конструкций», детали — строками на номенклатуре: лист (марка,
a×b), прокат (длина), метизы (штуки, цена вручную). Дальше всё как у любого изделия: масса и
цена по справочнику и прайсам, вкладка «Металл», раскрой, заявка на металл, счёт.

    details = [
        {"name": "Корпус", "kind": "sheet", "thickness": 3, "a": 257, "b": 340, "qty": 1, "grade": "Ст3пс"},
        {"name": "Шпилька", "kind": "linear", "profile_type": "Круг", "size": "d30", "length": 640, "qty": 1},
        {"name": "Гайка", "kind": "fastener", "type": "nut", "size": "М30", "gost": "ГОСТ 5915-70",
         "label": "Гайка М30 ГОСТ 5915-70", "weight": 0.21, "qty": 2, "price_unit": 45},
        {"name": "Своя деталь", "kind": "mass", "thickness": 10, "mass": 1.5, "qty": 1},
    ]
    product = spec._pmk_konstr_put("Опора КХ А12 Дн57", 10, 850.0, details, product=old_or_None)
"""
import math

from odoo import _, fields, models
from odoo.exceptions import UserError


def _qty(value):
    """Кол-во детали на изделие — целое (у строки расчёта целое ≥ 1)."""
    value = float(value or 0)
    return max(1, int(math.ceil(value - 1e-9)))


class MetalSpecKonstrPut(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_konstr_put(self, name, qty, price_unit, details, product=None, entry_text=None):
        """Создать (или пересобрать product) изделие «Конструкций» с деталями. → изделие."""
        self.ensure_one()
        if not self.cat_metal:
            self.cat_metal = True
        lines = [fields.Command.create(self._pmk_konstr_line(i, d)) for i, d in enumerate(details, 1)]
        vals = {"name": name, "qty": max(1, int(qty or 1)), "price_customer_unit": price_unit or 0.0}
        if entry_text:
            vals["pmk_entry_text"] = entry_text
        if product and product.exists() and product.spec_id == self:
            product.line_ids.unlink()
            product.write(dict(vals, line_ids=lines))
            return product
        seq = max(self.product_ids.mapped("sequence") or [0]) + 10
        return self.env["pmk.metal.spec.product"].create(dict(vals, spec_id=self.id, sequence=seq, line_ids=lines))

    def _pmk_konstr_line(self, seq, d):
        kind = d.get("kind")
        vals = {"sequence": seq, "detail_name": (d.get("name") or "")[:250] or False, "qty": _qty(d.get("qty", 1))}
        if d.get("grade"):
            vals.update(self._konstr_grade(d["grade"]))
        if kind in ("sheet", "mass") and d.get("thickness"):
            sheet = self._pmk_konstr_sheet(d["thickness"], d.get("sheet_type") or "Гладкий")
            vals.update(calc_mode="sheet", sheet_id=sheet.id)
            if kind == "sheet" and d.get("a") and d.get("b"):
                vals.update(a_mm=float(d["a"]), b_mm=float(d["b"]))
            else:
                # Своя деталь без размеров — «по КМ»: масса строки на одно изделие.
                vals["pmk_mass_kg"] = float(d.get("mass") or 0.0) * vals["qty"]
            vals["pmk_text"] = _("Лист %s") % ("%g" % float(d["thickness"])).replace(".", ",")
            return vals
        if kind == "linear":
            profile = self.env["pmk.metal.profile"].search(
                [("profile_type", "=", d["profile_type"]), ("size_label", "=", d["size"])], limit=1)
            if not profile:
                raise UserError(_("В справочнике проката нет «%(t)s %(s)s» — заведите позицию.",
                                  t=d["profile_type"], s=d["size"]))
            vals.update(calc_mode="linear", profile_id=profile.id, length_mm=float(d.get("length") or 0.0),
                        pmk_text="%s %s" % (d["profile_type"], d["size"]))
            return vals
        # Метиз (и прочая покупная деталь) — справочник метизов, цена за штуку вручную.
        fastener = self._pmk_konstr_fastener(d)
        vals.update(calc_mode="fastener", fastener_id=fastener.id, pmk_text=fastener.name,
                    pmk_manual_price_unit=float(d.get("price_unit") or 0.0))
        vals.pop("grade_id", None)
        vals.pop("pmk_grade_text", None)
        return vals

    def _pmk_konstr_sheet(self, thickness, sheet_type="Гладкий"):
        sheet = self.env["pmk.metal.sheet"].search(
            [("sheet_type", "=", sheet_type), ("thickness_mm", "=", float(thickness))], limit=1)
        if not sheet:
            raise UserError(_("В справочнике листа нет «%(t)s %(s)s мм» — заведите позицию.",
                              t=sheet_type, s=("%g" % float(thickness)).replace(".", ",")))
        return sheet

    def _pmk_konstr_fastener(self, d):
        """Метиз справочника по виду, размеру и ГОСТ; нет — заводим (масса из калькулятора).
        Справочник метизов правят не все — заводим от имени системы."""
        Fastener = self.env["pmk.metal.fastener"].sudo()
        label = (d.get("label") or d.get("name") or "").strip()
        domain = [("fastener_type", "=", d.get("type") or "other")]
        if d.get("size"):
            domain += [("size_label", "=", d["size"])]
            if d.get("gost"):
                domain += [("gost", "=", d["gost"])]
        else:
            domain += [("name", "=", label)]
        found = Fastener.search(domain, limit=1)
        if found:
            if not found.weight_kg and d.get("weight"):
                found.weight_kg = float(d["weight"])
            return found
        return Fastener.create({
            "name": label or _("Метиз"), "fastener_type": d.get("type") or "other",
            "size_label": d.get("size") or False, "gost": d.get("gost") or False,
            "weight_kg": float(d.get("weight") or 0.0),
        })
