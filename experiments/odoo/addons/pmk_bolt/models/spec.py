# -*- coding: utf-8 -*-
"""Болты в расчёте — категория «Фундаментные болты» (Антон 21.10.2026: «встраиваем
сначала в счёт и расчёт»), тем же приёмом, что доборка и вентзонты (pmk_calc
spec_categories.py): включили категорию — к расчёту заводится расчёт болтов БЛТ-…
(клиент, сделка); выключили — болты черновиком, в сводку и счёт не идут; пустой
черновик удаляется.

Вкладка «Фундаментные болты» в расчёте — та же таблица, что в калькуляторе (метод
bolt_* расчёта передаёт вызов его документу болтов): вводят прямо в расчёте, как в
«Конструкциях». Сводка «Металлоизделия» — болты строками с составом.
"""
from odoo import _, api, fields, models


class BoltCalcSpec(models.Model):
    _inherit = "pmk.bolt.calc"

    spec_id = fields.Many2one("pmk.metal.spec", "Расчёт", index=True, copy=False, ondelete="cascade",
                              help="Расчёт заказа, к которому относятся эти болты (категория «Фундаментные "
                                   "болты»). Пусто — расчёт болтов сам по себе (прикидка).")


class MetalSpecBolt(models.Model):
    _inherit = "pmk.metal.spec"

    cat_bolt = fields.Boolean("Фундаментные болты",
                              help="Включено — болты в расчёте. Выключено — черновик: болты целы, в расчёт не входят.")
    bolt_calc_ids = fields.One2many("pmk.bolt.calc", "spec_id", "Болты")
    bolt_line_ids = fields.Many2many("pmk.bolt.line", compute="_compute_bolt_lines", string="Болты расчёта")

    @api.depends("bolt_calc_ids.line_ids")
    def _compute_bolt_lines(self):
        for spec in self:
            spec.bolt_line_ids = spec.bolt_calc_ids.line_ids

    def _pmk_bolt_sync(self):
        """Категория включена — документ болтов есть; выключена — пустой удаляем."""
        Calc = self.env["pmk.bolt.calc"]
        for spec in self:
            if spec.cat_bolt and not spec.bolt_calc_ids:
                Calc.create({"spec_id": spec.id, "partner_id": spec.partner_id.id or False,
                             "opportunity_id": spec.opportunity_id.id if "opportunity_id" in spec._fields else False,
                             "note": spec.note or False})
            elif not spec.cat_bolt:
                spec.bolt_calc_ids.filtered(lambda c: not c.line_ids.filtered("bolt_type")).unlink()

    @api.model_create_multi
    def create(self, vals_list):
        specs = super().create(vals_list)
        specs.filtered("cat_bolt")._pmk_bolt_sync()
        return specs

    def write(self, vals):
        res = super().write(vals)
        if "cat_bolt" in vals:
            self._pmk_bolt_sync()
            if hasattr(self, "_pmk_sync_draft_invoices"):
                self._pmk_sync_draft_invoices()  # болты вошли в расчёт или вышли — черновик счёта следом
        if "partner_id" in vals or "opportunity_id" in vals:
            for spec in self:
                spec.bolt_calc_ids.write({"partner_id": spec.partner_id.id or False,
                                          "opportunity_id": spec.opportunity_id.id or False})
        return res

    def copy(self, default=None):
        """Копия расчёта получает копию болтов, а не пустой черновик (как доборка и зонты)."""
        new = super().copy(default)
        for src, dst in zip(self, new):
            if src.bolt_calc_ids:
                dst.bolt_calc_ids.filtered(lambda c: not c.line_ids.filtered("bolt_type")).unlink()
                for doc in src.bolt_calc_ids:
                    doc.copy({"spec_id": dst.id})
        return new

    def action_open_bolts(self):
        self.ensure_one()
        doc = self.bolt_calc_ids[:1]
        if not doc:
            return False
        return {"type": "ir.actions.act_window", "res_model": doc._name, "res_id": doc.id,
                "views": [(False, "form")], "target": "current"}

    # ─── Таблица во вкладке: вызовы — документу болтов ──────────────────
    def _pmk_bolt_doc(self):
        self.ensure_one()
        if not self.bolt_calc_ids:
            self.cat_bolt = True  # таблицу открыли — категория включена
        return self.bolt_calc_ids[:1]

    def _bolt_call(self, method, *args):
        self.ensure_one()
        data = getattr(self._pmk_bolt_doc(), method)(*args)
        self.invalidate_recordset()
        return data

    def bolt_rows(self):
        return self._bolt_call("bolt_rows")

    def bolt_save_row(self, row_key, vals):
        return self._bolt_call("bolt_save_row", row_key, vals)

    def bolt_insert_rows(self, after_key, rows):
        return self._bolt_call("bolt_insert_rows", after_key, rows)

    def bolt_add_product(self):
        return self._bolt_call("bolt_add_product")

    def bolt_delete_row(self, row_key):
        return self._bolt_call("bolt_delete_row", row_key)

    def bolt_duplicate_row(self, row_key):
        return self._bolt_call("bolt_duplicate_row", row_key)

    # ─── Сводка «Металлоизделия»: болты строками с составом ─────────────
    # Зависимости сводки pmk_bridge (spec_summary.py) — те же, плюс болты: метод
    # переопределён, и без повтора @api.depends форма перестала бы обновлять сводку.
    @api.depends("cat_metal", "cat_dobor", "cat_vent",
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
        "cat_bolt", "bolt_calc_ids.line_ids.name", "bolt_calc_ids.line_ids.qty",
        "bolt_calc_ids.line_ids.price_unit", "bolt_calc_ids.line_ids.mass_one",
        "bolt_calc_ids.line_ids.part_ids.cost")
    def _compute_pmk_summary(self):
        super()._compute_pmk_summary()
        for spec in self:
            if not spec.cat_bolt:
                continue
            summary = dict(spec.pmk_summary or {"rows": []})
            rows = list(summary.get("rows", []))
            for line in spec.bolt_calc_ids.line_ids.filtered("name").sorted(lambda l: (l.sequence, l.id)):
                rows.append(spec._pmk_summary_bolt(line))
            summary["rows"] = rows
            summary["weight"] = round(sum(r.get("weight") or 0 for r in rows), 1)
            summary["total"] = round(sum(r.get("total") or 0 for r in rows), 2)
            summary["unpriced"] = sum(1 for r in rows if not r.get("price_unit"))
            spec.pmk_summary = summary

    def _pmk_summary_bolt(self, line):
        return {
            "key": "bolt-%s" % line.id, "source": "bolt", "name": line.name or "",
            "qty": line.qty, "weight": round(line.mass_one * line.qty, 1),
            "price_unit": round(line.price_unit, 2), "total": round(line.price_total, 2),
            "details": [{
                "name": part.name or "", "qty": part.qty, "qty_total": part.qty * line.qty,
                "weight": round(part.mass, 3), "cost": round(part.cost, 2),
                "price": part.price_ton if part.auto_key == "stud" else part.price_unit,
                "price_label": _("₽/т") if part.auto_key == "stud" else _("₽/шт"),
            } for part in line.part_ids.filtered("name").sorted(lambda p: (p.sequence, p.id))],  # пустая строка ввода — не состав
            "foot": {"weight_one": round(line.mass_one, 2), "cost_one": round(line.cost_one, 2),
                     "warning": line.warning or ""},
        }

    # ─── Шапка расчёта: вес, изделия, цена, себестоимость, «нет цены» ────
    # Антон 22.10.2026: шапка — по всем категориям. Зависимости ниже складываются с
    # основными (pmk_calc metal_spec.py, pmk_bridge spec_cost.py).
    def _pmk_bolt_lines(self):
        return self.bolt_calc_ids.line_ids.filtered("name") if self.cat_bolt else self.env["pmk.bolt.line"]

    def _pmk_cat_totals(self):
        out = super()._pmk_cat_totals()
        lines = self._pmk_bolt_lines()
        if self.cat_bolt:
            out.append({"key": "bolt", "count": len(lines),
                        "weight": sum(l.mass_one * l.qty for l in lines),
                        "price": sum(lines.mapped("price_total")),
                        "cost": sum(l.cost_one * l.qty for l in lines),
                        "unpriced": len(lines.filtered(lambda l: not l.price_unit))})
        return out

    def _pmk_bolt_missing(self):
        """Состав болтов без цены (круг не в прайсах, шайба не вписана): названия по разу."""
        names = []
        for part in self._pmk_bolt_lines().part_ids.filtered("name"):
            price = part.price_ton if part.auto_key == "stud" else part.price_unit
            name = part.name.split(" — ")[0]  # «Круг 30 09Г2С — шпилька поз. 3, …» → «Круг 30 09Г2С»
            if not price and name not in names:
                names.append(name)
        return names

    @api.depends("cat_bolt", "bolt_calc_ids.line_ids.mass_one", "bolt_calc_ids.line_ids.qty",
                 "bolt_calc_ids.line_ids.name")
    def _compute_totals(self):
        super()._compute_totals()

    @api.depends("cat_bolt", "bolt_calc_ids.line_ids.price_total", "bolt_calc_ids.line_ids.cost_one",
                 "bolt_calc_ids.line_ids.qty", "bolt_calc_ids.line_ids.name")
    def _compute_customer_totals(self):
        super()._compute_customer_totals()

    @api.depends("cat_bolt", "bolt_calc_ids.line_ids.name", "bolt_calc_ids.line_ids.part_ids.price_unit",
                 "bolt_calc_ids.line_ids.part_ids.price_ton", "bolt_calc_ids.line_ids.part_ids.name")
    def _compute_cost_totals(self):
        """«Нет цены у N поз.» — и состав болтов без цены: себестоимость болтов занижена."""
        super()._compute_cost_totals()
        for spec in self:
            missing = len(spec._pmk_bolt_missing())
            if missing:
                spec.no_price_count += missing
                spec.price_incomplete = True

    def _compute_price_missing_text(self):
        super()._compute_price_missing_text()
        for spec in self:
            names = spec._pmk_bolt_missing()
            if names:
                bolts = _("болты: %s") % ", ".join(names)
                spec.price_missing_text = "; ".join(t for t in (spec.price_missing_text, bolts) if t)
