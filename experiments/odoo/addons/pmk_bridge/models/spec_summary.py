# -*- coding: utf-8 -*-
"""Вкладка «Металлоизделия» — сводка всех изделий расчёта (Антон 20.10.2026).

«Вкладка металлоизделия будет суммарно по всем калькуляторам на разные типы
металлоизделий»: изделия «Конструкций» (бывший состав расчёта; Бутик встанет
сюда шагом 2), позиции доборки и вентзонты — одной таблицей. Строка
раскрывается и показывает состав — только смотреть («можно раскрыть, но не
редактировать»); правят во вкладке своего калькулятора. Цена клиенту здесь
тоже не правится — вопрос открыт (Антон 20.10).

Категория выключена («черновик — в расчёт не входит») — её позиций в сводке
нет. Изделие без деталей — «Вручную» (типовое из счёта): раскрывать нечего.

Считается на лету (поле не хранится): строк — десятки, база не нагружается, а
сводка видит и несохранённые правки «Конструкций».
"""
import json

from odoo import api, fields, models


def _r(value, digits=3):
    return round(value or 0.0, digits)


def _mm(value):
    """114085 → «114 085», 0,7 → «0,7»: длину в мм читают глазами, с разрядами."""
    text = "{:,.1f}".format(value or 0.0).rstrip("0").rstrip(".")
    return text.replace(",", "\u202f").replace(".", ",")


class MetalSpecSummary(models.Model):
    _inherit = "pmk.metal.spec"

    pmk_summary = fields.Json(
        "Сводка изделий", compute="_compute_pmk_summary",
        help="Все изделия расчёта: конструкции, доборка, вентзонты — с составом для просмотра.")

    @api.depends(
        "cat_metal", "cat_dobor", "cat_vent",
        "product_ids.name", "product_ids.qty", "product_ids.sequence",
        "product_ids.weight_one", "product_ids.weight_total",
        "product_ids.price_customer_unit", "product_ids.price_customer_total",
        "product_ids.cost_fact_one", "product_ids.no_price_count",
        "product_ids.line_ids.detail_name", "product_ids.line_ids.calc_mode",
        "product_ids.line_ids.profile_id", "product_ids.line_ids.sheet_id",
        "product_ids.line_ids.fastener_id", "product_ids.line_ids.paint_id",
        "product_ids.line_ids.grade_id", "product_ids.line_ids.length_mm",
        "product_ids.line_ids.a_mm", "product_ids.line_ids.b_mm", "product_ids.line_ids.qty",
        "product_ids.line_ids.weight_total", "product_ids.line_ids.cost_fact_total",
        "product_ids.line_ids.pmk_mass_kg",
        "dobor_line_ids", "vent_line_ids",
        "product_ids.pmk_kp_seq", "dobor_order_ids.line_ids.pmk_kp_seq", "vent_order_ids.line_ids.pmk_kp_seq")
    def _compute_pmk_summary(self):
        for spec in self:
            rows = []
            if spec.cat_metal:
                rows += [spec._pmk_summary_product(p) for p in spec.product_ids.sorted(lambda p: (p.sequence, p.id or 0))]
            if spec.cat_dobor:
                rows += [spec._pmk_summary_dobor(l) for l in spec.dobor_line_ids]
            if spec.cat_vent:
                rows += [spec._pmk_summary_vent(h) for h in spec.vent_line_ids]
            rows = spec._pmk_summary_sorted(rows)  # №312: сквозной порядок (порядок в КП)
            spec.pmk_summary = {
                "rows": rows,
                "weight": _r(sum(r["weight"] for r in rows), 1),
                "total": _r(sum(r["total"] for r in rows), 2),
                "unpriced": sum(1 for r in rows if not r["price_unit"]),
            }

    # ─── Конструкции ────────────────────────────────────────────────────
    def _pmk_summary_product(self, product):
        details = []
        for line in product.line_ids.sorted(lambda l: (l.sequence, l.id or 0)):
            item = line.profile_id or line.sheet_id or line.fastener_id or line.paint_id
            size = ""
            if line.pmk_mass_kg and line.calc_mode in ("linear", "sheet"):
                # №307: деталь «по КМ» — масса из спецификации, размеров нет.
                size = "по КМ %s кг" % _mm(line.pmk_mass_kg)
            elif line.calc_mode == "sheet" and (line.a_mm or line.b_mm):
                size = "%s × %s мм" % (_mm(line.a_mm), _mm(line.b_mm))
            elif line.calc_mode == "linear" and line.length_mm:
                size = "%s мм" % _mm(line.length_mm)
            details.append({
                "name": line.detail_name or "",
                "item": item.display_name if item else "",
                "kind": dict(line._fields["calc_mode"].selection).get(line.calc_mode, ""),
                "size": size,
                "grade": line.grade_id.display_name or "",
                "qty": line.qty,
                "qty_total": line.qty * (product.qty or 0),
                "weight": _r(line.weight_total, 2),
                "cost": _r(line.cost_fact_total, 2),
            })
        key = product.id if isinstance(product.id, int) else str(product.id)
        return {
            "key": "metal-%s" % key,
            "kp": product.pmk_kp_seq,
            "source": "metal" if details else "manual",
            "name": product.name or "",
            "qty": product.qty,
            "weight": _r(product.weight_total, 1),
            "price_unit": _r(product.price_customer_unit, 2),
            "total": _r(product.price_customer_total, 2),
            "details": details,
            "foot": {
                "weight_one": _r(product.weight_one, 2),
                "cost_one": _r(product.cost_fact_one, 2),
                "no_price": product.no_price_count,
            } if details else {},
        }

    # ─── Доборка ────────────────────────────────────────────────────────
    def _pmk_summary_dobor(self, line):
        hems = [side for side, on in (("слева", line.hem_left), ("справа", line.hem_right)) if on]
        bends = "%d гиб." % line.bends if line.bends else ""
        if hems:
            bends += (", " if bends else "") + "завальцовка " + " и ".join(hems)
        if line.lock:
            bends += (", " if bends else "") + "замок"
        coating = line.coating_id
        return {
            "key": "dobor-%s" % line.id,
            "kp": line.pmk_kp_seq,
            "source": "dobor",
            "name": line.display_name or "",
            "qty": line.qty,
            "weight": _r(line.weight_total, 1),
            "price_unit": _r(line.price_unit, 2),
            "total": _r(line.price_total, 2),
            "dobor": {
                "sketch": line.sketch or "",
                "sheet": line.sheet_id.display_name or "",
                # «RAL 8017 Шоколад» уже с кодом — второй раз «RAL 8017» не пишем.
                "coating": " · ".join(p for p in (coating.name, coating.ral_code and coating.ral_code not in
                                                  (coating.name or "") and "RAL %s" % coating.ral_code) if p)
                if coating else "",
                "developed": _r(line.developed_width, 1),
                "bends": bends,
                "length": _r(line.plank_length, 1),
                "area_one": _r(line.area_one, 3),
                "area_total": _r(line.area_total, 2),
                "weight_one": _r(line.weight_one, 2),
                "strips": line.strips,
            },
        }

    # ─── Вентзонты ──────────────────────────────────────────────────────
    def _pmk_summary_vent(self, hood):
        try:
            spec = json.loads(hood.spec_json or "{}")
        except ValueError:
            spec = {}
        qty = hood.qty or 0
        parts = []
        for part in spec.get("parts") or []:
            size = part.get("size_mm") or []
            parts.append({
                "name": part.get("name") or "",
                "size": " × ".join(("%g" % s).replace(".", ",") for s in size[:2]),
                "qty": part.get("qty") or 0,
                "qty_total": (part.get("qty") or 0) * qty,
            })
        if hood.lapki:
            holes = spec.get("lapki_holes_d7")
            parts.append({"name": "Лапки" + (" (отв. Ø7 — %d)" % holes if holes else ""), "size": "",
                          "qty": hood.lapki, "qty_total": hood.lapki * qty})
        if hood.klepki:
            parts.append({"name": "Заклёпки", "size": "", "qty": hood.klepki, "qty_total": hood.klepki * qty})
        head = [hood.material_name or (hood.sheet_id.display_name or "")]
        if hood.sves:
            head.append("свес %d мм" % hood.sves)
        if hood.layout:
            head.append(hood.layout)
        return {
            "key": "vent-%s" % hood.id,
            "kp": hood.pmk_kp_seq,
            "source": "vent",
            "name": "Зонт %s" % (hood.hood_label or hood.display_name or ""),
            "qty": qty,
            "weight": _r(hood.total_mass_net_kg, 1),
            "price_unit": _r(hood.price_unit, 2),
            "total": _r(hood.price_total, 2),
            "vent": {
                "head": " · ".join(h for h in head if h),
                "parts": parts,
                "metal_m2": _r(hood.metal_net_m2, 2),
                "sheet_m": _r(hood.sheet_1250_m, 2),
                "weight_one": _r(hood.mass_net_kg, 2),
                "error": hood.spec_error or "",
            },
        }
