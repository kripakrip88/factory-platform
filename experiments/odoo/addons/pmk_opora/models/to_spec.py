# -*- coding: utf-8 -*-
"""Опоры → расчёт изделием «Конструкций» (Антон 25.10.2026, вариант 1).

Антон: «это же листовой материал, и он должен отображаться в спецификации соответствующей
номенклатурой». Калькулятор опор подбирает состав по ОСТ, в расчёт опора идёт изделием
«Конструкций»:

    листовые детали — лист (толщина, марка стали опоры, заготовка a×b);
    своя листовая деталь без размеров — лист «по КМ» (масса);
    болты, гайки, свои покупные строки — метизы, цена за штуку (как вписана в калькуляторе).

Цена изделия — цена опоры из калькулятора (с наценкой). Повторный перенос пересобирает то же
изделие. Расчёт: указанный → главный расчёт сделки → новый (как у болтов, pmk_bolt/to_spec.py).
"""
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

BUY_RE = re.compile(r"^(Болт|Гайка|Шайба)\s+(М[\d.,]+(?:[×x]\d+)?)\s*(ГОСТ\s*[\d.\-]+)?", re.I)
BUY_TYPE = {"болт": "bolt", "гайка": "nut", "шайба": "washer"}


class OporaLineKonstr(models.Model):
    _inherit = "pmk.opora.line"

    konstr_product_id = fields.Many2one("pmk.metal.spec.product", "Изделие в расчёте", copy=False,
                                        ondelete="set null", index=True)

    def _pmk_konstr_details(self):
        self.ensure_one()
        out = []
        for part in self.part_ids.filtered("name").sorted(lambda p: (p.sequence, p.id)):
            name = part.name.split(" — ")[0]
            if part._pmk_is_metal() and part.thickness:
                d = {"name": name, "thickness": part.thickness, "qty": part.qty, "grade": self.steel or False}
                if part.a_mm and part.b_mm:
                    d.update(kind="sheet", a=part.a_mm, b=part.b_mm)
                else:
                    d.update(kind="mass", mass=part.unit_mass)
                out.append(d)
                continue
            m = BUY_RE.match(part.name or "")
            d = {"name": name, "kind": "fastener", "qty": part.qty, "weight": part.unit_mass,
                 "price_unit": part.price_unit, "label": part.name, "type": "other"}
            if m:
                d.update(type=BUY_TYPE[m.group(1).lower()], size=m.group(2).replace("x", "×"),
                         gost=(m.group(3) or "").strip() or False, label=part.name)
            out.append(d)
        return out


class OporaCalcKonstr(models.Model):
    _inherit = "pmk.opora.calc"

    spec_id = fields.Many2one("pmk.metal.spec", "Расчёт", index=True, copy=False, ondelete="set null",
                              help="Куда опоры переносятся изделиями «Конструкций» (кнопка «В расчёт»). Пусто — "
                                   "главный расчёт сделки или новый.")

    def _pmk_target_spec(self):
        self.ensure_one()
        if self.spec_id:
            return self.spec_id
        Spec = self.env["pmk.metal.spec"]
        deal = self.opportunity_id
        if deal and "spec_ids" in deal._fields:
            from odoo.addons.pmk_deal.models.deal_money import main_spec
            spec = main_spec(deal.spec_ids)
            if spec:
                return spec
        vals = {"partner_id": self.partner_id.id or (deal.partner_id.id if deal else False)}
        if deal and "opportunity_id" in Spec._fields:
            vals["opportunity_id"] = deal.id
        return Spec.create(vals)

    def _pmk_to_konstr(self, spec):
        self.ensure_one()
        products = self.env["pmk.metal.spec.product"]
        for line in self.line_ids.filtered(lambda l: l.name and l._pmk_ok()).sorted(lambda l: (l.sequence, l.id)):
            product = spec._pmk_konstr_put(line.name, line.qty, line.price_unit, line._pmk_konstr_details(),
                                           product=line.konstr_product_id)
            line.konstr_product_id = product
            products |= product
        if self.spec_id != spec:
            self.spec_id = spec
        return products

    def action_opora_to_spec(self):
        """«В расчёт»: опоры — изделиями «Конструкций»; открыть расчёт."""
        self.ensure_one()
        if not self.line_ids.filtered(lambda l: l.name and l._pmk_ok()):
            raise UserError(_("Нет опор, которые можно перенести: впишите опору («кх а12 57 10шт»)."))
        spec = self._pmk_target_spec()
        products = self._pmk_to_konstr(spec)
        self.message_post(body=_("Перенесено в расчёт %(spec)s: изделий %(n)d.", spec=spec.display_name,
                                 n=len(products)), subtype_xmlid="mail.mt_note")
        return {"type": "ir.actions.act_window", "res_model": "pmk.metal.spec", "res_id": spec.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}
