# -*- coding: utf-8 -*-
"""Болты → расчёт изделием «Конструкций» (Антон 25.10.2026: «да, делай вариант 1 и болты тоже»).

Раньше болты жили в расчёте своей категорией (вкладка «Фундаментные болты»): состав текстом,
круг и лист плиты не попадали ни во вкладку «Металл», ни в заявку на металл. Теперь калькулятор
болтов — подборщик по ГОСТ, а в расчёт болт идёт изделием «Конструкций», детали — на номенклатуре:

    шпилька — прокат «Круг d1», длина заготовки, марка болта;
    плита   — лист t, b×b, марка болта;
    гайки, шайба, свои строки состава — метизы, цена за штуку (как вписана в калькуляторе).

Цена изделия — цена болта из калькулятора (с наценкой). Повторный перенос пересобирает то же
изделие (konstr_product_id), второго не заводит.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools import gost


class BoltLineKonstr(models.Model):
    _inherit = "pmk.bolt.line"

    konstr_product_id = fields.Many2one("pmk.metal.spec.product", "Изделие в расчёте", copy=False,
                                        ondelete="set null", index=True)

    def _pmk_konstr_details(self):
        """Детали болта для «Конструкций»."""
        self.ensure_one()
        d = int(self.diameter)
        spec, s = gost.TYPES[self.bolt_type], gost.SIZES[d]
        grade = self.steel or False
        out = []
        for part in self.part_ids.filtered("name").sorted(lambda p: (p.sequence, p.id)):
            if part.auto_key == "stud":
                out.append({"name": _("Шпилька поз. %s") % spec["pos"], "kind": "linear", "profile_type": "Круг",
                            "size": "d%s" % s["d1"], "length": round(gost.blank_mm(self.bolt_type, d, self.length)),
                            "qty": part.qty, "grade": grade})
            elif part.auto_key == "plate" and spec["plate"]:
                b, t, _kg = s["plate"]
                out.append({"name": _("Плита %(b)s×%(b)s×%(t)s", b=b, t=t), "kind": "sheet", "thickness": t,
                            "a": b, "b": b, "qty": part.qty, "grade": grade})
            elif part.auto_key == "nut":
                out.append({"name": _("Гайка"), "kind": "fastener", "type": "nut", "size": "М%s" % d,
                            "gost": gost.NUT_GOST[d], "label": part.name.split(" — ")[0],
                            "weight": gost.NUT_KG[d], "qty": part.qty, "price_unit": part.price_unit})
            elif part.auto_key == "washer":
                out.append({"name": _("Шайба"), "kind": "fastener", "type": "washer", "size": "М%s" % d,
                            "gost": "ГОСТ 24379.1-2012", "label": part.name, "weight": s["w"],
                            "qty": part.qty, "price_unit": part.price_unit})
            else:
                # Своя строка состава («гайка м30 калён 2шт 45») — покупная деталь, цена за штуку.
                out.append({"name": part.name, "kind": "fastener", "type": "other", "label": part.name,
                            "weight": part.unit_mass, "qty": part.qty, "price_unit": part.price_unit})
        return out


class BoltCalcKonstr(models.Model):
    _inherit = "pmk.bolt.calc"

    def _pmk_target_spec(self):
        """Куда переносить: указанный расчёт → главный расчёт сделки → новый расчёт."""
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

    def _pmk_to_konstr(self, spec, entry_text=None):
        """Болты документа → изделия «Конструкций» расчёта spec. → изделия."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l._pmk_ok() and not l.parse_error).sorted(lambda l: (l.sequence, l.id))
        products = self.env["pmk.metal.spec.product"]
        for line in lines:
            product = spec._pmk_konstr_put(line.name, line.qty, line.price_unit, line._pmk_konstr_details(),
                                           product=line.konstr_product_id, entry_text=entry_text)
            line.konstr_product_id = product
            products |= product
        if self.spec_id != spec:
            self.spec_id = spec
        return products

    def action_bolt_to_spec(self):
        """«В расчёт»: болты — изделиями «Конструкций»; открыть расчёт."""
        self.ensure_one()
        if not self.line_ids.filtered(lambda l: l._pmk_ok() and not l.parse_error):
            raise UserError(_("Нет болтов, которые можно перенести: впишите болт («бф 2.1 м30 640мм ст3 10шт»)."))
        spec = self._pmk_target_spec()
        products = self._pmk_to_konstr(spec)
        self.message_post(body=_("Перенесено в расчёт %(spec)s: изделий %(n)d.", spec=spec.display_name,
                                 n=len(products)), subtype_xmlid="mail.mt_note")
        return {"type": "ir.actions.act_window", "res_model": "pmk.metal.spec", "res_id": spec.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}
